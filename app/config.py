import os

LOGIN_TTL = 60 * 6
DOMAIN = os.environ['DOMAIN']
SECRET_KEY = os.environ['SECRET_KEY']
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12

ENDPOINTS = ['https://net1.ton.dev/', 'https://net5.ton.dev/']
SIGN_CHECKER_ADDRESS = ''
DEBOT_ADDRESS = ''
ALLOWED_SUBSCRIPTIONS = []

