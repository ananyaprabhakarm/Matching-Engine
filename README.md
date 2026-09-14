# ⚡ Cryptocurrency Matching Engine

A **simple and efficient cryptocurrency matching engine** built with **FastAPI** and **WebSockets**, supporting multiple order types (LIMIT, MARKET, IOC, FOK) and a **maker-taker fee model**.  

This project demonstrates how a basic exchange engine works — matching buy/sell orders based on price-time priority and returning real-time trade execution reports.

---

## 🚀 Features

- **Order Types Supported:**
  - LIMIT (rest on book if not fully matched)
  - MARKET (match immediately or cancel)
  - IOC (Immediate or Cancel)
  - FOK (Fill or Kill)
  - STOP / STOP_LIMIT / TAKE_PROFIT (rest as pending triggers, activate on a crossing trade)
- **Symbols:** Supports multiple trading pairs (e.g., BTC-USDT)
- **Trader Identity:** Every order carries a `trader_id` (a plain client-supplied string, not a login system) - enough to support cancellation and self-trade prevention
- **Order Cancellation:** Cancel your own resting orders; other traders' orders can't be discovered or cancelled
- **Self-Trade Prevention:** An order never matches against its own trader's resting orders - it skips them and matches everyone else at that price level instead
- **Maker-Taker Fee Model:**  
  - Maker: 0.1%  
  - Taker: 0.2%
- **Real-Time Matching:** Uses price-time priority (FIFO)
- **WebSocket Trade Feed:** Sends executed trades instantly
- **Lightweight Design:** Focused on clarity and speed

---

## 🧠 System Architecture

### Components Overview

| Component | Description |
|------------|--------------|
| **Matching Engine** | Core logic that matches buy and sell orders |
| **Order Book** | Stores bids and asks with efficient lookup |
| **API Layer (FastAPI)** | Handles order submission and WebSocket connections |
| **Fee Engine** | Calculates maker and taker fees |
| **Trade Reporter** | Returns trade details including fees and best bid/ask snapshot |

---

### Basic Architecture Diagram
```
 ┌──────────────────────────────┐
 │          Clients             │
 │ (Traders / Bots / Systems)   │
 └──────────────┬───────────────┘
                │
         HTTP / WebSocket
                │
    ┌───────────┴───────────┐
    │       FastAPI App     │
    │  - /order endpoint    │
    │  - /ws/trades feed    │
    └───────────┬───────────┘
                │
       ┌────────┴────────┐
       │ Matching Engine │
       │  - Order Book   │
       │  - Fee System   │
       │  - Trade Logic  │
       └─────────────────┘

```
## 🧩 Data Structures

| Structure | Purpose |
|------------|----------|
| **`deque` (FIFO)** | To store orders at each price level |
| **`list` of prices** | To track sorted price levels for matching |
| **`dict` of orders** | To quickly access orders by ID |
| **`Trade` list** | To store all executed trades for reporting |

**Order matching priority:**
- Highest bid matches lowest ask first.
- Within a price, earlier (older) orders have priority (FIFO).

---

## ⚙️ Matching Algorithm

**Steps:**

1. A new order arrives (buy or sell).  
2. It’s matched against opposite orders in the book based on price and time priority.  
3. Trades are executed at the **maker’s price**.  
4. Fees are calculated and included in the trade report.  
5. If the order isn’t fully filled:
   - LIMIT → rests in book  
   - MARKET/IOC → remainder canceled  
   - FOK → only executes if full quantity is available  

**Example Trade Report:**

```json
{
  "symbol": "BTC-USDT",
  "price": 65000,
  "quantity": 0.5,
  "maker_order_id": "c18c...",
  "taker_order_id": "b92f...",
  "aggressor_side": "buy",
  "fees": {
    "maker_fee": 32.5,
    "taker_fee": 65.0,
    "maker_fee_rate": 0.001,
    "taker_fee_rate": 0.002
  }
}
```
## 💸 Maker-Taker Fee Model

### Defined in config.py:
MAKER_FEE_RATE = 0.001  # 0.1%
TAKER_FEE_RATE = 0.002  # 0.2%

Maker: Adds liquidity (resting order).
Taker: Removes liquidity (immediate match).

Both fees are automatically included in each trade execution report.

## 🌐 API Endpoints
### 1. Submit Order

POST /order

Request Example:
```json
{
  "symbol": "BTC-USDT",
  "order_type": "limit",
  "side": "buy",
  "quantity": "0.5",
  "price": "65000",
  "trader_id": "alice"
}
```
For `stop` / `stop_limit` / `take_profit`, also include `stop_price` (the trigger price); `stop_limit` additionally needs `price` (the limit price it converts to once triggered).

Response Example:
```json
{
  "status": "accepted",
  "order_id": "6491a6cf-c1d8-4044-9da2-ef673bd9cae0",
  "trades": [],
  "bbo": {
    "bid": "65000",
    "ask": null
  },
  "self_trade_prevented": false
}
```

### 2. Cancel Order

DELETE /order/{order_id}?trader_id=alice

Cancels a resting order. Returns 404 if the order doesn't exist *or* belongs to a different trader (the two aren't distinguished, so you can't probe for other traders' order IDs), and 400 if the order is already fully filled.

### 3. Order Book Snapshot

GET /orderbook/{symbol}

Same shape as the WebSocket `l2_update` payload (top 10 bids/asks + BBO), for clients that don't want to hold a socket open just to check the book once.

### 4. A Trader's Open Orders

GET /orders/{trader_id}

Lists that trader's currently-resting orders (used by the dashboard to show cancel buttons next to your own open orders).

### 5. WebSocket Trade Feed

Endpoint: ws://127.0.0.1:8000/ws/trades

Clients receive updates on every executed trade in real time.

Example message:
```json
{
  "symbol": "BTC-USDT",
  "price": 65000,
  "quantity": 0.5,
  "aggressor_side": "buy",
  "fees": {
    "maker_fee": 32.5,
    "taker_fee": 65.0
  }
}
```
## 🧰 Tech Stack

Python 3.10+

FastAPI (for REST + WebSocket APIs)

Uvicorn (ASGI server)

Collections / Decimal / UUID (for precise order handling)

## 🧱 Running the Project
```
# Clone repo
git clone https://github.com/yourusername/matching-engine.git
cd matching-engine

# Create Virual Enviornment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the server (single worker only - see "Scaling this" below)
uvicorn api.server:app --host 127.0.0.1 --port 8000
```
Then open:
➡️ http://127.0.0.1:8000/ for the live trading dashboard (order entry, live order book, BBO, trade tape)
➡️ http://127.0.0.1:8000/docs to view API documentation.

## 🖥️ Live Dashboard

A single-page dashboard is served directly by the API at `/` (see [web/](web/)) — no separate frontend build or server needed. It connects to `/order` and `/ws` in real time so you can place orders and watch the book, BBO, and trade tape update live, straight from the actual matching engine.

## 🧪 Testing with Postman

POST request to /order for creating buy/sell orders.

WebSocket connect to ws://127.0.0.1:8000/ws/trades to see trade feed live.

Example curl command:
```
curl -X POST http://127.0.0.1:8000/order \
  -H "Content-Type: application/json" \
  -d '{"symbol": "BTC-USDT", "order_type": "limit", "side": "buy", "quantity": "1", "price": "65000"}'
```
## 📈 Future Improvements

Add persistent storage as an append-only event log (current pickle-snapshot persistence exists but isn't wired into the server lifecycle yet)

Add order modification support (cancellation already exists)

Add proper logging and audit trails

Add performance benchmarking

Swap the price-level `list` + `bisect` structure for something with better insert/remove complexity at scale (e.g. `sortedcontainers.SortedList`) - the current approach is correct, just not optimal under heavy order-book churn

Real authentication (today `trader_id` is just a client-supplied string, not a login system - fine for a demo, not for production)

## ⚖️ Scaling This

This engine is intentionally a **single process** right now: `MatchingEngine` and every `OrderBook` are plain in-memory Python objects with no external shared store behind them. That's why the run command above does *not* use `--workers`  - each `uvicorn` worker is a separate process with its own private copy of the engine, so an order placed against worker 1 would be completely invisible to worker 2's order book. That's a correctness bug, not a performance tradeoff.

Within a single process, this already handles real concurrency well: FastAPI/`asyncio` serve many connections concurrently, and a per-symbol `asyncio.Lock` serializes only the orders for the *same* symbol, so BTC-USDT and ETH-USDT orders never block each other.

To actually scale beyond one process, the real options are:
- **Shard by symbol** across multiple processes, with a lightweight router in front that sends each symbol's orders to its own dedicated process.
- **Move the shared state out of process** entirely (e.g. into Redis or a dedicated matching microservice) so multiple API workers can all submit to the same source of truth.

Either is a legitimate next step - just not something you get for free by adding `--workers`.

## 🧪 Performance Note

Currently, the system is in-memory and single-process — you can expect hundreds of orders/sec easily within that one process.
Performance can be scaled further by:

Using async APIs for bulk order ingestion

Sharding by symbol or moving shared state to Redis (see "Scaling This" above) - not by adding uvicorn workers, which breaks correctness for this architecture

Optimizing data structures (e.g., heaps or SortedDicts)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details. 
