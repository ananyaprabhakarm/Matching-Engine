# api/server.py
import asyncio
import json
from typing import Dict, Set, Tuple
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

from api.schemas import OrderRequest, WSSubscribe
from engine.matching_engine import MatchingEngine
from engine.order import Order, OrderType, OrderSide
from decimal import Decimal

app = FastAPI(title="Matching Engine API")

# single matching engine instance (in-memory)
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
            price=req.price
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # ensure serial processing per symbol
    lock = get_symbol_lock(order.symbol)
    async with lock:
        trades, bbo = engine.process_order(order)

    # Build payloads and broadcast
    # 1) trade events
    for t in trades:
        # t is Trade dataclass with to_dict()
        await broadcast_to_feed("trades", order.symbol, {"type": "trade", "data": t.to_dict()})

    # 2) book snapshot (top 10) + BBO
    book = engine.get_book(order.symbol)
    top = book.top_n(10)
    snapshot = {
        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "symbol": order.symbol,
        "bbo": bbo,
        "asks": top["asks"],
        "bids": top["bids"]
    }
    await broadcast_to_feed("book", order.symbol, {"type": "l2_update", "data": snapshot})
    # broadcast bbo separately (many clients may subscribe only to bbo)
    await broadcast_to_feed("bbo", order.symbol, {"type": "bbo", "data": {"timestamp": snapshot["timestamp"], "symbol": order.symbol, "bid": bbo["bid"], "ask": bbo["ask"]}})

    # respond with order accepted + trades and bbo
    # convert trades to JSON serializable
    trades_json = [t.to_dict() for t in trades]
    response = {"status": "accepted", "order_id": order.id, "trades": trades_json, "bbo": bbo}
    return JSONResponse(status_code=200, content=response)

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

            if msg.action == "subscribe":
                await register_subscription(ws, msg.feed, msg.symbol)
                # on subscribe, send immediate snapshot so client has state
                book = engine.get_book(msg.symbol)
                top = book.top_n(10)
                bbo = {"bid": str(book.best_bid()) if book.best_bid() is not None else None,
                       "ask": str(book.best_ask()) if book.best_ask() is not None else None}
                await safe_send(ws, json.dumps({"type": "subscribed", "feed": msg.feed, "symbol": msg.symbol}))
                if msg.feed == "bbo":
                    await safe_send(ws, json.dumps({"type":"bbo", "data":{"timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z", "symbol": msg.symbol, "bid": bbo["bid"], "ask": bbo["ask"]}}))
                elif msg.feed == "book":
                    await safe_send(ws, json.dumps({"type":"l2_update", "data":{"timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z", "symbol": msg.symbol, "asks": top["asks"], "bids": top["bids"]}}))
                elif msg.feed == "trades":
                    await safe_send(ws, json.dumps({"type":"info", "message": "subscribed to trades for " + msg.symbol}))
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
# Run with: uvicorn api.server:app --reload
# ---------------------------
if __name__ == "__main__":
    uvicorn.run("api.server:app", host="127.0.0.1", port=8000, reload=True)
