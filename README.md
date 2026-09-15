# Matching Engine

A crypto matching engine built with FastAPI and WebSockets: price-time priority order matching, a maker-taker fee model, self-trade prevention, stop/take-profit orders, and a live trading dashboard — all backed by a real (if intentionally single-process) engine, not a mock.

## Features

- **Order types**: LIMIT, MARKET, IOC (Immediate-or-Cancel), FOK (Fill-or-Kill), STOP, STOP_LIMIT, TAKE_PROFIT
- **Price-time priority matching**: best price first, FIFO within a price level
- **Maker-taker fees**: maker 0.1%, taker 0.2% (`utils/config.py`)
- **Trader identity**: every order carries a `trader_id` — a plain client-supplied string, not a login system, but enough to support cancellation and self-trade prevention
- **Order cancellation**: cancel your own resting orders; other traders' orders can't be discovered or cancelled through the API
- **Self-trade prevention**: an order never matches against its own trader's resting orders — it skips them (preserving their place in the queue) and matches everyone else at that price level instead
- **Stop orders**: STOP / STOP_LIMIT / TAKE_PROFIT rest as pending triggers and activate automatically when a trade crosses their trigger price, including cascading triggers
- **Live dashboard**: a single-page UI served by the API itself — order entry, live order book, BBO, trade tape, and your own open orders with cancel buttons
- **Durable persistence**: every order/trade/cancel is appended to a human-readable event log, replayed on startup on top of a periodic snapshot — see [Persistence](#persistence) below

## Architecture

```
 Clients (traders / bots)
        │
   HTTP + WebSocket
        │
   FastAPI app (api/server.py)
    - POST /order, DELETE /order/{id}
    - GET /orderbook/{symbol}, GET /orders/{trader_id}
    - WS /ws  (bbo / book / trades feeds)
    - GET /   (dashboard, served from web/)
        │
   MatchingEngine (engine/matching_engine.py)
    - one OrderBook per symbol (engine/order_book.py)
    - fee calculation, trade construction (engine/trade.py)
    - event log + snapshot persistence (engine/persistence.py)
```

**Per-symbol data structures** (`engine/order_book.py`):
- `bids_map` / `asks_map`: `price -> deque[Order]`, FIFO within a price level
- `bids_prices` / `asks_prices`: `sortedcontainers.SortedList` of active price levels (O(log n) insert/remove), descending for bids, ascending for asks
- `orders_by_id`: `order_id -> Order`, for O(1) cancellation lookup
- `trigger_orders`: pending STOP/STOP_LIMIT/TAKE_PROFIT orders, evaluated against each trade's price

## Running it

```bash
git clone <this repo>
cd Matching-Engine

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# single worker only - see "Scaling" below for why
uvicorn api.server:app --host 127.0.0.1 --port 8000
```

Then open:
- `http://127.0.0.1:8000/` — the live trading dashboard
- `http://127.0.0.1:8000/docs` — interactive API docs (Swagger UI)

## API

### `POST /order`

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
`price` is required for `limit`/`ioc`/`fok`/`stop_limit`. `stop_price` is required for `stop`/`stop_limit`/`take_profit`, and `stop_limit` additionally needs `price` (the limit price it converts to once triggered).

```json
{
  "status": "accepted",
  "order_id": "6491a6cf-c1d8-4044-9da2-ef673bd9cae0",
  "trades": [],
  "bbo": { "bid": "65000", "ask": null },
  "self_trade_prevented": false
}
```

### `DELETE /order/{order_id}?trader_id=alice`

Cancels a resting order. Returns `404` if the order doesn't exist *or* belongs to a different trader (deliberately not distinguished, so you can't probe for other traders' order IDs), and `400` if it's already fully filled.

### `GET /orderbook/{symbol}`

Top-10 bids/asks + BBO, same shape as the WebSocket `l2_update` payload — for a client that just wants one read without holding a socket open.

### `GET /orders/{trader_id}`

That trader's currently-resting orders (what the dashboard's "My Open Orders" panel polls).

### `GET /health`

Trivial liveness check.

### `WS /ws`

Subscribe/unsubscribe to live feeds per symbol:
```json
{"action": "subscribe", "feed": "bbo", "symbol": "BTC-USDT"}
```
`feed` is one of `bbo`, `book`, `trades`. On subscribe you immediately get a snapshot, then live updates as they happen:
```json
{"type": "bbo", "data": {"symbol": "BTC-USDT", "bid": "65000", "ask": null}}
{"type": "l2_update", "data": {"symbol": "BTC-USDT", "bids": [...], "asks": [...]}}
{"type": "trade", "data": {"symbol": "BTC-USDT", "price": "65000", "quantity": "0.5", "maker_trader_id": "bob", "taker_trader_id": "alice", ...}}
```

## Persistence

Two layers, working together:

1. **Event log** (`data/events.jsonl`) — every accepted order, executed trade, and cancellation is appended as one JSON line the moment it happens. Human-readable, append-only, genuinely crash-safe.
2. **Periodic snapshot** (`data/order_books_snapshot.pkl`) — the full in-memory state, pickled every few seconds as a fast-recovery checkpoint. Taking one truncates the event log, since everything in it up to that point is now captured in the snapshot.

On startup: load the last snapshot (if any), then replay the event log on top of it. Replay only ever needs to cover the gap since the last snapshot, not the full history — standard snapshot + replay-the-tail.

## Scaling

This is intentionally a **single process**: `MatchingEngine` and every `OrderBook` are plain in-memory Python objects with no external shared store. That's why the run command above doesn't use `--workers` — each `uvicorn` worker would be a separate process with its own private copy of the engine, so an order placed against worker 1 would be invisible to worker 2's book. That's a correctness bug, not a performance tradeoff.

Within that one process, real concurrency is still handled well: FastAPI/`asyncio` serve many connections concurrently, and a per-symbol `asyncio.Lock` serializes only orders for the *same* symbol — BTC-USDT and ETH-USDT orders never block each other.

To scale beyond one process for real: shard by symbol across multiple processes with a router in front, or move the shared state out of process entirely (Redis, or a dedicated matching microservice). Both are legitimate next steps — neither is "just add `--workers`."

## Testing

```bash
pytest tests/ -v
```

20 tests across `tests/test_matching_engine.py` (every order type, fees, FIFO, cancellation, self-trade prevention, stop-order triggering) and `tests/test_persistence.py` (crash recovery via log replay and via snapshot, append-only log format, snapshot-triggered truncation).

## Known limitations / next steps

- `trader_id` is a plain client-supplied string, not real authentication — fine for a demo, not for production.
- No order modification (cancel + resubmit works, but there's no in-place amend).
- No sharding/Redis backend yet — see [Scaling](#scaling).

## Tech stack

Python 3.9+, FastAPI, Uvicorn, `websockets`, `sortedcontainers`, `Decimal` throughout for exact price/quantity arithmetic.
