### [TonClick repository](https://github.com/tonred/tonclick/)

Off-chain demo site: https://demo.ton.click/
###Workflow:
1. Service generates a random temporary key and passes it to the user via WebSockets 
2. User input this value in Surf DeBot(QR code or manually)
3. DeBot shows user domain of the Service he is trying to access and asks to sign payload with his private key. Payload contains user public key, Service domain, and temp key from backend 
4. After payload signing, hash of payload and user public key sends to Service vai https request.
5. Service check signature with pubkey
6. Checks if user with such public key has active matching subscriptions
5. Service grants JWT token to user via websockets, which will provide access to the private methods of service API 
