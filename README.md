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
- **Symbols:** Supports multiple trading pairs (e.g., BTC-USDT)
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
  "price": "65000"
}
```
Response Example:
```json
{
  "status": "accepted",
  "order_id": "6491a6cf-c1d8-4044-9da2-ef673bd9cae0",
  "trades": [],
  "bbo": {
    "bid": "65000",
    "ask": null
  }
}
```
### 2. WebSocket Trade Feed

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

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn main:app --reload
```
Then open:
➡️ http://127.0.0.1:8000/docs to view API documentation.

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

Add persistent storage (e.g., Redis/PostgreSQL)

Add order cancellation and modification support

Add proper logging and audit trails

Add performance benchmarking

Expose /orderbook snapshot endpoint

## 🧪 Performance Note

Currently, the system is in-memory and single-threaded — you can expect hundreds of orders/sec easily.
Performance can be scaled to 1000+ orders/sec by:

Using async APIs for bulk order ingestion

Running on a production ASGI server like uvicorn --workers 4

Optimizing data structures (e.g., heaps or SortedDicts)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details. 
