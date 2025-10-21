import asyncio
import json
import websockets
from engine.matching_engine import MatchingEngine
from engine.order import OrderType, OrderSide, Order

engine = MatchingEngine()
clients = set()

async def notify_clients(message):
    if clients:
        await asyncio.wait([client.send(message) for client in clients])

async def handle_connection(websocket, path):
    clients.add(websocket)
    try:
        async for message in websocket:
            data = json.loads(message)
            if data.get("action") == "new_order":
                order = Order(
                    symbol=data["symbol"],
                    order_type=OrderType(data["order_type"]),
                    side=OrderSide(data["side"]),
                    quantity=float(data["quantity"]),
                    price=float(data.get("price", 0))
                )
                trades = engine.process_order(order)

                # Send trade updates
                for trade in trades:
                    await notify_clients(json.dumps({"type": "trade", "data": trade.to_dict()}))

                # Send updated BBO
                book = engine.get_order_book(order.symbol)
                await notify_clients(json.dumps({"type": "bbo", "data": book.bbo}))

    finally:
        clients.remove(websocket)

async def main():
    async with websockets.serve(handle_connection, "localhost", 8765):
        print("WebSocket server started at ws://localhost:8765")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
