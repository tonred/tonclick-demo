import io
import time
import typing
import uuid
import httpx
from datetime import timedelta, datetime

from fastapi import FastAPI, WebSocket, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from jose import jwt, JWTError
from pydantic import BaseModel
from starlette import status
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.templating import Jinja2Templates
from starlette.websockets import WebSocketDisconnect

from ton import check_sign, check_user_subscription, get_subscriptions_data, zero
from config import LOGIN_TTL, DOMAIN, SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, DEBOT_ADDRESS

app = FastAPI(
    redoc_url=None,
    docs_url=None,
    openapi_url=None
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)
app.mount('/static', StaticFiles(directory='static', html=True), name='static')

templates = Jinja2Templates(directory='static')

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')


@app.get('/')
async def root(request: Request):
    return templates.TemplateResponse('index.html', {'request': request})


class ConnectionManager:
    def __init__(self):
        self.active_connections: typing.Dict[str, typing.Tuple[WebSocket, str, float]] = {}

    async def connect(self, websocket: WebSocket) -> typing.Tuple[str, str]:
        await websocket.accept()
        cid = str(uuid.uuid4())[:8]
        sid = str(uuid.uuid4())

        self.active_connections[cid] = (websocket, sid, time.time())
        return cid, sid

    def refresh(self, cid) -> typing.Optional[str]:
        if cid in self.active_connections:
            (websocket, _, _) = self.active_connections[cid]
            sid = str(uuid.uuid4())
            self.active_connections[cid] = (websocket, sid, time.time())
            return sid

    def disconnect(self, cid: str):
        del self.active_connections[cid]

    async def send(self, message: str, cid: str):
        await self.active_connections[cid][0].send_text(message)

    def check_sid(self, cid: str, received_sid: str) -> typing.Optional[WebSocket]:
        if cid in self.active_connections:
            (websocket, sid, created_at) = self.active_connections[cid]
            if sid == received_sid and time.time() - created_at <= LOGIN_TTL:
                return websocket
        return


class Token(BaseModel):
    access_token: str
    token_type: str


class Plan(BaseModel):
    address: str
    name: str
    id: str
    duration: str
    ton_price: str
    prices: int


class Plans(BaseModel):
    plans: typing.List[Plan]


class TokenData(BaseModel):
    key: typing.Optional[str] = None
    subscription: typing.Optional[str] = None
    sub_exp: typing.Optional[int] = None


def create_access_token(data: dict, expires_delta: typing.Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({'exp': expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)) -> typing.Optional[TokenData]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail='Could not validate credentials',
        headers={'WWW-Authenticate': 'Bearer'},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        token_data = TokenData.parse_obj(payload.get('user'))
        if token_data.key is None:
            raise credentials_exception
    except JWTError as e:
        raise credentials_exception

    return token_data


async def get_current_active_user(token_data: TokenData = Depends(get_current_user)):
    if time.time() >= token_data.sub_exp:
        raise HTTPException(status_code=400, detail='Inactive user')
    return token_data


manager = ConnectionManager()


def get_access_token(user_data: dict) -> dict:
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={'user': user_data}, expires_delta=access_token_expires
    )
    return {'access_token': access_token, 'token_type': 'bearer'}


@app.post('/login/{cid}/{sid}')
async def login(cid: str, sid: str, request: Request):
    payload = (await request.body()).decode('utf-8')
    (pubkey, signature) = payload.split('|')
    if await check_sign(signature, DOMAIN, pubkey, cid, sid):
        websocket = manager.check_sid(cid, sid)
        subscription_data = await check_user_subscription('0x' + pubkey)
        if websocket and subscription_data:
            (subscription_address, finish_time) = subscription_data
            td = TokenData(key=pubkey, subscription=subscription_address, sub_exp=finish_time)
            await manager.send('access_token|' + get_access_token(td.dict())['access_token'], cid)
            await manager.send('user_data|' + td.json(), cid)
        return 'ok'
    return 'fail'


@app.websocket('/ws/')
async def websocket_endpoint(websocket: WebSocket):
    (cid, sid) = await manager.connect(websocket)
    try:
        # await manager.send(f'debot|{DEBOT_ADDRESS}', cid)
        while True:
            await manager.send(f'login|/{cid}/{sid}', cid)
            data = await websocket.receive_text()
            if data == 'refresh':
                sid = manager.refresh(cid)
    except WebSocketDisconnect:
        manager.disconnect(cid)


@app.get('/plans/', response_model=Plans)
async def active_plans():
    plans_data = await get_subscriptions_data()
    plans = []
    for (address, plan_info, plan_details) in plans_data:
        duration = int(int(plan_info['value0']['duration']) / 86400)
        ton_price = 'Not available'
        if zero in plan_details['prices']:
            ton_price = int(plan_details['prices'][zero]) * (10 ** -9)
            del plan_details['prices'][zero]
        plan = Plan(
            address=address.replace(':', 'x'),
            name=bytes.fromhex(plan_info['value0']['title']).decode('utf-8'),
            id=plan_details['nonce'],
            duration=f'{duration} days',
            ton_price=str(ton_price),
            prices=len(plan_details['prices'].keys())
        )

        plans.append(plan)
    return Plans(plans=plans)


@app.get('/me/', response_model=TokenData)
async def read_users_me(toke_data: TokenData = Depends(get_current_active_user)):
    return toke_data


@app.get('/cats/')
async def cats(toke_data: TokenData = Depends(get_current_active_user)):
    async with httpx.AsyncClient() as client:
        r = await client.get('https://cataas.com/cat/says/Ave%20Free%20TON!')
        image_data = io.BytesIO(r.content)
        return StreamingResponse(image_data, media_type='image/png')


@app.get('/debot/')
async def debot():
    return {'debot': DEBOT_ADDRESS}
