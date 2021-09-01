import asyncio
import base64
import typing

from tonclient.client import TonClient
from tonclient.types import NetworkConfig, AbiConfig, ClientConfig, Abi, CallSet, ParamsOfWaitForCollection, \
    ParamsOfEncodeMessage, Signer, StateInitSource, ParamsOfEncodeAccount, ParamsOfRunTvm, ParamsOfDecodeMessage, \
    DecodedMessageBody

from config import ENDPOINTS, SIGN_CHECKER_ADDRESS, ALLOWED_SUBSCRIPTIONS

SIGN_CHECKER_ABI = Abi.from_path('assets/SignChecker.abi.json')
SUBSCRIPTION_PLAN_ABI = Abi.from_path('assets/SubscriptionPlan.abi.json')
USER_SUBSCRIPTION_ABI = Abi.from_path('assets/UserSubscription.abi.json')
accounts_cache = {}
zero = '0:0000000000000000000000000000000000000000000000000000000000000000'

def get_client():
    network = NetworkConfig(
        server_address=None,
        # endpoints=['https://main2.ton.dev', 'https://main3.ton.dev'],
        endpoints=ENDPOINTS,
        message_retries_count=0,
        sending_endpoint_count=4,
        latency_detection_interval=30000,
        max_latency=30000)
    abi = AbiConfig(message_expiration_timeout=30000)

    return TonClient(config=ClientConfig(network=network, abi=abi), is_async=True)


client = get_client()


async def run_local(
        function_name: str,
        input_: dict,
        address: str,
        abi: Abi.Json,
        cache: bool = False
) -> typing.Optional[DecodedMessageBody]:
    if cache and address in accounts_cache:
        cache_result = accounts_cache[address]
        data = cache_result['data']
        code = cache_result['code']
    else:
        q_params = ParamsOfWaitForCollection(
            collection='accounts',
            filter={'id': {'eq': address}},
            result='data code',
        )
        _result = (await client.net.query_collection(params=q_params)).result
        if _result:
            _result = _result[0]
        else:
            return
        data = _result['data']
        code = _result['code']
        if cache:
            accounts_cache[address] = _result
    call_set = CallSet(function_name=function_name, input=input_)
    encoded_body = await client.abi.encode_message(params=ParamsOfEncodeMessage(
        abi=abi,
        address=address,
        signer=Signer.NoSigner(),
        call_set=call_set,
    ))
    state_init = StateInitSource.StateInit(code=code, data=data)
    account_encode_params = ParamsOfEncodeAccount(state_init=state_init)
    account = await client.abi.encode_account(params=account_encode_params)
    run_params = ParamsOfRunTvm(message=encoded_body.message, account=account.account,
                                abi=abi)
    _result = await client.tvm.run_tvm(params=run_params)
    return await client.abi.decode_message(params=ParamsOfDecodeMessage(abi=abi, message=_result.out_messages[0]))


async def check_sign(signature: str, domain: str, pubkey: str, cid: str, sid: str) -> bool:
    try:
        result = await run_local('checkSign', {
            'signature': base64.b64decode(signature).hex(),
            'domain': domain.encode('utf-8').hex(),
            'pubkey': '0x' + pubkey,
            'cid': cid.encode('utf-8').hex(),
            'sid': sid.encode('utf-8').hex()
        }, SIGN_CHECKER_ADDRESS, SIGN_CHECKER_ABI, True)
        if result:
            return result.value['value0']
    except:
        pass
    return False


async def check_user_subscription(pubkey: str) -> typing.Optional[typing.Tuple[str, int]]:
    try:
        for sub_plan in ALLOWED_SUBSCRIPTIONS:
            result = await run_local('getUserSubscription', {
                'user': zero,
                'pubkey': pubkey,
                'root': sub_plan
            }, sub_plan, SUBSCRIPTION_PLAN_ABI, True)
            if result:
                user = result.value['value0']
                finish_time = await run_local('getFinishTime', {}, user, USER_SUBSCRIPTION_ABI, False)
                if finish_time:
                    return sub_plan, int(finish_time.value['value0'])
    except Exception as e:
        print(repr(e))
        return


async def get_subscriptions_data() -> typing.List[typing.Tuple[str, dict, dict]]:
    plans = []
    for sub_plan in ALLOWED_SUBSCRIPTIONS:
        info = (await run_local('getInfo', {'_answer_id': 0}, sub_plan, SUBSCRIPTION_PLAN_ABI, True)).value
        details = (await run_local('getDetails', {'_answer_id': 0}, sub_plan, SUBSCRIPTION_PLAN_ABI, True)).value
        plans.append((sub_plan, info, details))
    return plans
