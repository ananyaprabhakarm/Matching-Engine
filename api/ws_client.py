import asyncio
import websockets
import json

async def listen():
    uri = "ws://127.0.0.1:8000/ws"
    async with websockets.connect(uri) as websocket:
        subscribe_msg = {
            "action" : "subscribe",
            "feed" : "bbo",
            "symbol" : "BTC-USDT"
        }
        await websocket.send(json.dumps(subscribe_msg))
        print("Subscribed to BBO feed for BTC-USDT....")
        
        while True:
            try:
                msg = await websocket.recv()
                data = json.loads(msg)
                print(json.dumps(data,indent=2))
            except websockets.ConnectionClosed: 
                print("Connection closed by the server")
                break   

asyncio.run(listen())            