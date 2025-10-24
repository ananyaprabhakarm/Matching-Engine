import asyncio, time, aiohttp, json
URL = "http://127.0.0.1:8000/order"

async def send_one(session, payload):
    async with session.post(URL, json=payload) as r:
        return await r.text()

async def run(total=10000, concurrency=200):
    sem = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession() as session:
        start = time.time()
        async def task(i):
            async with sem:
                payload = {
                    "symbol": "BTC-USDT",
                    "order_type": "limit",
                    "side": "buy" if i % 2 == 0 else "sell",
                    "quantity": "0.001",
                    "price": str(6500 + (i % 20))
                }
                await send_one(session, payload)
        tasks = [asyncio.create_task(task(i)) for i in range(total)]
        await asyncio.gather(*tasks)
        elapsed = time.time() - start
        print(f"total={total} elapsed={elapsed:.2f} ops/s={total/elapsed:.2f}")

if __name__ == "__main__":
    asyncio.run(run(total=2000, concurrency=400))
