from decimal import Decimal, getcontext
from engine.order_book import OrderBook
from engine.order import Order, OrderType, OrderSide
from engine.trade import Trade
from typing import Dict, List, Optional, Tuple
from engine.persistence import load_snapshot, save_snapshot
from utils.config import MAKER_FEE_RATE, TAKER_FEE_RATE
import asyncio

# set decimal precision (adjust as needed)
getcontext().prec = 18

# Order types that never match immediately - they rest as pending triggers
# until a crossing trade activates them (see _activate_trigger_orders).
TRIGGER_ORDER_TYPES = (OrderType.STOP, OrderType.STOP_LIMIT, OrderType.TAKE_PROFIT)


class MatchingEngine:
    def __init__(self, persist_interval_seconds: int = 5):
        # symbol -> OrderBook
        self.order_books = {}
        # store trades for audit
        self.trades: List[Trade] = []
        data = load_snapshot()
        if data:
            self.order_books, self.trades = data.get("order_books", {}), data.get("trades", [])
        self._persist_interval = persist_interval_seconds
        self._persist_task = None
        # order_id -> symbol. Lets a bare order_id (all DELETE /order/{id} has)
        # be routed to the right OrderBook without scanning every symbol.
        self.order_symbol_index: Dict[str, str] = {}

    async def start_persistence_task(self):
        if self._persist_task:
            return
        self._persist_task = asyncio.create_task(self._persist_loop())

    async def _persist_loop(self):
        while True:
            await asyncio.sleep(self._persist_interval)
            try:
                save_snapshot({"order_books": self.order_books, "trades": self.trades})
            except Exception:
                # don't crash engine
                pass

    def save_state_now(self):
        save_snapshot({"order_books": self.order_books, "trades": self.trades})

    def get_book(self, symbol: str) -> OrderBook:
        if symbol not in self.order_books:
            self.order_books[symbol] = OrderBook(symbol)
        return self.order_books[symbol]

    def bbo(self, symbol: str):
        book = self.get_book(symbol)
        return {"bid": str(book.best_bid()) if book.best_bid() is not None else None,
                "ask": str(book.best_ask()) if book.best_ask() is not None else None}

    def process_order(self, order: Order) -> Tuple[List[Trade], dict, bool]:
        """
        Process an incoming order and return (trades, bbo_snapshot, self_trade_prevented).
        This enforces:
          - price-time priority (FIFO at each price)
          - no internal trade-throughs: always match at best prices first
          - correct behavior for MARKET, LIMIT, IOC, FOK
          - self-trade prevention: an order never matches against its own trader's resting orders
          - STOP / STOP_LIMIT / TAKE_PROFIT rest as pending triggers instead of matching
        """
        book = self.get_book(order.symbol)

        if order.order_type in TRIGGER_ORDER_TYPES:
            book.add_trigger_order(order)
            return [], self.bbo(order.symbol), False

        trades: List[Trade] = []
        self_trade_prevented = False

        # Determine counter side maps
        if order.side == OrderSide.BUY:
            counter_map = book.asks_map
            counter_prices = book.asks_prices  # ascending
            # available_qty_on_side_up_to_price's `side` param means "which side to sum":
            # non-BUY sums asks, which is what a buy taker needs.
            resting_liquidity_side = OrderSide.SELL
        else:
            counter_map = book.bids_map
            counter_prices = book.bids_prices  # descending
            resting_liquidity_side = OrderSide.BUY

        # Helper to check marketability of a price level against incoming order
        def price_level_marketable(level_price: Decimal) -> bool:
            if order.order_type == OrderType.MARKET:
                return True
            if order.order_type in (OrderType.LIMIT, OrderType.IOC, OrderType.FOK):
                # for buy: level_price <= order.price (asks priced <= buy limit)
                if order.side == OrderSide.BUY:
                    return level_price <= order.price
                else:
                    return level_price >= order.price
            return False

        # For FOK: pre-check whether total available at marketable prices >= order.quantity.
        # Own resting orders are excluded - they can never be matched (self-trade prevention),
        # so they must not count toward "is there enough liquidity to fill this".
        if order.order_type == OrderType.FOK:
            total_avail = book.available_qty_on_side_up_to_price(
                resting_liquidity_side, limit_price=order.price, exclude_trader_id=order.trader_id
            )
            if total_avail < order.remaining:
                # Cannot fill entirely -> cancel
                return [], self.bbo(order.symbol), False

        # For IOC: we will attempt matching as far as marketable prices and then cancel remainder

        # Matching loop: respect price-time priority:
        # For buys: iterate asks ascending (best asks first). For sells: iterate bids descending (best bids first).
        # Using a copy of price list because we may mutate maps during matching
        prices_snapshot = list(counter_prices)
        while order.remaining > 0 and prices_snapshot:
            # pick next price level
            level_price = prices_snapshot[0]  # snapshot[0] is best available level
            if not price_level_marketable(level_price):
                break  # cannot match further without trade-through

            queue = counter_map.get(level_price)
            if not queue:
                prices_snapshot.pop(0)
                continue

            # Self-trade prevention: skip past any resting order owned by the same trader,
            # matching everyone else at this price level first (FIFO otherwise preserved).
            skipped_self_orders = []

            while queue and order.remaining > 0:
                resting_order = queue[0]

                if resting_order.trader_id == order.trader_id:
                    queue.popleft()
                    skipped_self_orders.append(resting_order)
                    self_trade_prevented = True
                    continue

                exec_price = resting_order.price
                exec_qty = min(order.remaining, resting_order.remaining)

                aggressor_side = order.side.value if isinstance(order.side, OrderSide) else order.side
                trade_value = exec_price * exec_qty

                trade = Trade(
                    symbol=order.symbol,
                    price=exec_price,
                    quantity=exec_qty,
                    maker_order_id=resting_order.id,
                    taker_order_id=order.id,
                    aggressor_side=aggressor_side,
                    maker_trader_id=resting_order.trader_id,
                    taker_trader_id=order.trader_id,
                    maker_fee=trade_value * MAKER_FEE_RATE,
                    taker_fee=trade_value * TAKER_FEE_RATE
                )

                trades.append(trade)
                self.trades.append(trade)

                # update fills
                resting_order.filled += exec_qty
                order.filled += exec_qty

                # pop resting order if fully filled
                if resting_order.remaining == 0:
                    queue.popleft()

            # Restore any self-owned orders we skipped, back at the front, in their
            # original relative order - they're still resting, untouched, in the book.
            for skipped in reversed(skipped_self_orders):
                queue.appendleft(skipped)

            if not queue:
                # genuinely empty price level -> remove from the real book maps & price lists
                if order.side == OrderSide.BUY:
                    if level_price in book.asks_map and not book.asks_map[level_price]:
                        del book.asks_map[level_price]
                        book._remove_ask_price(level_price)
                else:
                    if level_price in book.bids_map and not book.bids_map[level_price]:
                        del book.bids_map[level_price]
                        book._remove_bid_price(level_price)
                prices_snapshot.pop(0)
            elif order.remaining > 0:
                # Only this trader's own orders are left here - nothing more to match
                # at this level, but the level stays in the book (those orders still rest).
                prices_snapshot.pop(0)
            # else: order fully filled, with other-trader liquidity still queued behind it

        # Post-matching behavior depending on order type:
        if order.remaining > 0:
            if order.order_type == OrderType.MARKET:
                # Market order: any remaining quantity is canceled (no external book)
                pass
            elif order.order_type == OrderType.IOC:
                # Immediate-Or-Cancel: matched part stays, remaining is cancelled
                pass
            elif order.order_type == OrderType.FOK:
                # unreachable: pre-checked above and returned early if not fillable
                pass
            elif order.order_type == OrderType.LIMIT:
                # Limit order: rest the remaining quantity on the book (no trade-through)
                book.add_order(order)
                self.order_symbol_index[order.id] = order.symbol
        # If fully filled, do not rest on book

        # Activate any stop/stop-limit/take-profit orders the last trade price crossed.
        # Recursion here (process_order -> _activate_trigger_orders -> process_order) lets
        # one trade cascade into further triggers naturally.
        if trades:
            triggered_trades = self._activate_trigger_orders(order.symbol, trades[-1].price)
            trades.extend(triggered_trades)

        return trades, self.bbo(order.symbol), self_trade_prevented

    def cancel_order(self, order_id: str, trader_id: str) -> str:
        """
        Cancel a resting order. Returns one of: "ok", "not_found", "forbidden", "already_filled".
        """
        symbol = self.order_symbol_index.get(order_id)
        if symbol is None:
            return "not_found"
        book = self.get_book(symbol)
        result = book.cancel_order(order_id, trader_id)
        if result == "ok":
            self.order_symbol_index.pop(order_id, None)
        return result

    def get_open_orders(self, trader_id: str, symbol: Optional[str] = None) -> List[Order]:
        books = [self.get_book(symbol)] if symbol else list(self.order_books.values())
        open_orders = []
        for book in books:
            for order in book.orders_by_id.values():
                if order.trader_id == trader_id and order.remaining > 0:
                    open_orders.append(order)
        return open_orders

    def _activate_trigger_orders(self, symbol, last_trade_price: Decimal) -> List[Trade]:
        book = self.get_book(symbol)
        activated = book.check_and_activate_triggers(last_trade_price)
        collected_trades: List[Trade] = []
        for trig in activated:
            # convert STOP to proper order type
            if trig.order_type == OrderType.STOP:
                new_order = Order(symbol=trig.symbol, order_type=OrderType.MARKET, side=trig.side,
                                   quantity=trig.quantity, trader_id=trig.trader_id)
            elif trig.order_type == OrderType.STOP_LIMIT:
                new_order = Order(symbol=trig.symbol, order_type=OrderType.LIMIT, side=trig.side,
                                   quantity=trig.quantity, price=trig.price, trader_id=trig.trader_id)
            elif trig.order_type == OrderType.TAKE_PROFIT:
                new_order = Order(symbol=trig.symbol, order_type=OrderType.MARKET, side=trig.side,
                                   quantity=trig.quantity, trader_id=trig.trader_id)
            else:
                continue
            sub_trades, _, _ = self.process_order(new_order)
            collected_trades.extend(sub_trades)
        return collected_trades
