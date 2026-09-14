import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Set, Tuple
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from api.schemas import OrderRequest, WSSubscribe
from engine.matching_engine import MatchingEngine
from engine.order import Order, OrderType, OrderSide
from decimal import Decimal

app = FastAPI(title="Matching Engine API")

# Single in-process matching engine instance. This MUST stay a single process:
# `engine`, `symbol_locks`, and every OrderBook are plain in-memory Python objects
# with no shared/external store behind them. Running this with `uvicorn --workers 4`
# (or any multi-process setup) gives each worker its own separate, unsynchronized
# copy - an order placed against worker 1 would be invisible to worker 2's book.
# Scaling this for real would mean either sharding by symbol across processes with a
# router in front, or moving shared state into Redis/a dedicated matching service.
engine = MatchingEngine()

# per-symbol asyncio.Lock to ensure serial processing per symbol
symbol_locks: Dict[str, asyncio.Lock] = {}

def get_symbol_lock(symbol: str) -> asyncio.Lock:
    if symbol not in symbol_locks:
        symbol_locks[symbol] = asyncio.Lock()
    return symbol_locks[symbol]

# Manage WebSocket subscriptions:
# mapping: websocket -> set of (feed, symbol)
ws_subscriptions: Dict[WebSocket, Set[Tuple[str, str]]] = {}
# helper mapping to quickly find sockets subscribed to (feed, symbol)
subscribers_index: Dict[Tuple[str, str], Set[WebSocket]] = {}

async def register_subscription(ws: WebSocket, feed: str, symbol: str):
    key = (feed, symbol)
    ws_subscriptions.setdefault(ws, set()).add(key)
    subscribers_index.setdefault(key, set()).add(ws)

async def unregister_subscription(ws: WebSocket, feed: str, symbol: str):
    key = (feed, symbol)
    if ws in ws_subscriptions:
        ws_subscriptions[ws].discard(key)
        if not ws_subscriptions[ws]:
            ws_subscriptions.pop(ws, None)
    if key in subscribers_index:
        subscribers_index[key].discard(ws)
        if not subscribers_index[key]:
            subscribers_index.pop(key, None)

async def unregister_all(ws: WebSocket):
    for key in list(ws_subscriptions.get(ws, [])):
        await unregister_subscription(ws, key[0], key[1])

async def broadcast_to_feed(feed: str, symbol: str, payload: dict):
    """Send payload (JSON-serializable) to all subscribers of (feed, symbol)."""
    key = (feed, symbol)
    subs = list(subscribers_index.get(key, set()))
    if not subs:
        return
    msg = json.dumps(payload)
    # send concurrently but ignore failures
    await asyncio.gather(*[safe_send(ws, msg) for ws in subs], return_exceptions=True)

async def safe_send(ws: WebSocket, msg: str):
    try:
        await ws.send_text(msg)
    except Exception:
        # If send fails (client disconnected), cleanup
        await unregister_all(ws)

def _orderbook_snapshot(symbol: str) -> dict:
    book = engine.get_book(symbol)
    top = book.top_n(10)
    bbo = engine.bbo(symbol)
    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "symbol": symbol,
        "bbo": bbo,
        "asks": top["asks"],
        "bids": top["bids"],
    }

async def broadcast_book_and_bbo(symbol: str):
    """Shared by any endpoint that mutates a book (submit/cancel) and needs to
    push the resulting book/BBO state to live WS subscribers."""
    snapshot = _orderbook_snapshot(symbol)
    await broadcast_to_feed("book", symbol, {"type": "l2_update", "data": snapshot})
    await broadcast_to_feed("bbo", symbol, {"type": "bbo", "data": {
        "timestamp": snapshot["timestamp"], "symbol": symbol,
        "bid": snapshot["bbo"]["bid"], "ask": snapshot["bbo"]["ask"],
    }})

# ---------------------------
# REST: submit order endpoint
# ---------------------------
@app.post("/order")
async def submit_order(req: OrderRequest):
    """
    Accept an order and process it via MatchingEngine.
    Returns list of executed trades (if any) and the BBO snapshot.
    """
    # validate and map to engine Order type
    try:
        order = Order(
            symbol=req.symbol,
            order_type=OrderType(req.order_type),
            side=OrderSide(req.side),
            quantity=req.quantity,
            trader_id=req.trader_id,
            price=req.price,
            stop_price=req.stop_price,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # ensure serial processing per symbol
    lock = get_symbol_lock(order.symbol)
    async with lock:
        trades, bbo, self_trade_prevented = engine.process_order(order)

    # Build payloads and broadcast
    # 1) trade events
    for t in trades:
        # t is Trade dataclass with to_dict()
        await broadcast_to_feed("trades", order.symbol, {"type": "trade", "data": t.to_dict()})

    # 2) book snapshot (top 10) + BBO
    await broadcast_book_and_bbo(order.symbol)

    # respond with order accepted + trades and bbo
    trades_json = [t.to_dict() for t in trades]
    response = {
        "status": "accepted",
        "order_id": order.id,
        "trades": trades_json,
        "bbo": bbo,
        "self_trade_prevented": self_trade_prevented,
    }
    return JSONResponse(status_code=200, content=response)

# ---------------------------
# REST: cancel order endpoint
# ---------------------------
@app.delete("/order/{order_id}")
async def cancel_order(order_id: str, trader_id: str):
    """
    Cancel a resting order. `trader_id` is passed as a query param (?trader_id=...)
    rather than a DELETE body, since request bodies on DELETE aren't reliably
    supported across HTTP clients/proxies.
    """
    symbol = engine.order_symbol_index.get(order_id)
    if symbol is None:
        raise HTTPException(status_code=404, detail="Order not found")

    lock = get_symbol_lock(symbol)
    async with lock:
        result = engine.cancel_order(order_id, trader_id)
        if result in ("not_found", "forbidden"):
            # Don't distinguish the two - avoids leaking whether an order_id
            # exists but belongs to someone else.
            raise HTTPException(status_code=404, detail="Order not found")
        if result == "already_filled":
            raise HTTPException(status_code=400, detail="Order already filled - nothing to cancel")

    await broadcast_book_and_bbo(symbol)
    return {"status": "cancelled", "order_id": order_id}

# ---------------------------
# REST: order book snapshot
# ---------------------------
@app.get("/orderbook/{symbol}")
def get_orderbook(symbol: str):
    """Same shape as the WS l2_update payload, for clients that don't want to hold a socket open."""
    return _orderbook_snapshot(symbol)

# ---------------------------
# REST: a trader's open orders
# ---------------------------
@app.get("/orders/{trader_id}")
def get_open_orders(trader_id: str, symbol: Optional[str] = None):
    orders = engine.get_open_orders(trader_id, symbol)
    return {
        "trader_id": trader_id,
        "orders": [
            {
                "order_id": o.id,
                "symbol": o.symbol,
                "side": o.side.value,
                "order_type": o.order_type.value,
                "price": str(o.price) if o.price is not None else None,
                "quantity": str(o.quantity),
                "filled": str(o.filled),
                "remaining": str(o.remaining),
            }
            for o in orders
        ],
    }

# ---------------------------
# WebSocket endpoint
# ---------------------------
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    WebSocket protocol:
      - client may send JSON messages:
          {"action": "subscribe", "feed": "bbo"|"book"|"trades", "symbol": "BTC-USDT"}
          {"action": "unsubscribe", ...}
      - server sends JSON messages for subscribed feeds:
          bbo: {"type":"bbo", "data": {"timestamp", "symbol", "bid","ask"}}
          book: {"type":"l2_update", "data": {timestamp, symbol, asks, bids}}
          trades: {"type":"trade", "data": {...trade fields...}}
    """
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = WSSubscribe.parse_raw(raw)
            except Exception as e:
                # invalid message - send error and continue
                await safe_send(ws, json.dumps({"error": "invalid subscribe message", "detail": str(e)}))
                continue

            if msg.action == 'subscribe':
                await register_subscription(ws, msg.feed, msg.symbol)
                # on subscribe, send immediate snapshot so client has state
                snapshot = _orderbook_snapshot(msg.symbol)
                await safe_send(ws, json.dumps({"type": "subscribed", "feed": msg.feed, "symbol": msg.symbol}))
                if msg.feed == "bbo":
                    await safe_send(ws, json.dumps({"type": "bbo", "data": {
                        "timestamp": snapshot["timestamp"], "symbol": msg.symbol,
                        "bid": snapshot["bbo"]["bid"], "ask": snapshot["bbo"]["ask"],
                    }}))
                elif msg.feed == "book":
                    await safe_send(ws, json.dumps({"type": "l2_update", "data": snapshot}))
                elif msg.feed == "trades":
                    await safe_send(ws, json.dumps({"type": "info", "message": "subscribed to trades for " + msg.symbol}))
            else:
                # unsubscribe
                await unregister_subscription(ws, msg.feed, msg.symbol)
                await safe_send(ws, json.dumps({"type": "unsubscribed", "feed": msg.feed, "symbol": msg.symbol}))

    except WebSocketDisconnect:
        await unregister_all(ws)
    except Exception:
        await unregister_all(ws)

# ---------------------------
# Simple health endpoints
# ---------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

# ---------------------------
# Web dashboard (static demo UI)
# ---------------------------
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(WEB_DIR / "index.html")

if __name__ == "__main__":
    # NOTE: no --workers flag here on purpose - see the comment above `engine = MatchingEngine()`.
    uvicorn.run("api.server:app", host="127.0.0.1", port=8000, reload=True)
