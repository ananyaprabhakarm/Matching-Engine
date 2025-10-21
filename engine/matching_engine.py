# engine/matching_engine.py
from decimal import Decimal, getcontext
from engine.order_book import OrderBook
from engine.order import Order, OrderType, OrderSide
from engine.trade import Trade
from typing import List, Tuple

# set decimal precision (adjust as needed)
getcontext().prec = 18

class MatchingEngine:
    def __init__(self):
        # symbol -> OrderBook
        self.order_books = {}
        # store trades for audit
        self.trades: List[Trade] = []

    def get_book(self, symbol: str) -> OrderBook:
        if symbol not in self.order_books:
            self.order_books[symbol] = OrderBook(symbol)
        return self.order_books[symbol]

    def bbo(self, symbol: str):
        book = self.get_book(symbol)
        return {"bid": str(book.best_bid()) if book.best_bid() is not None else None,
                "ask": str(book.best_ask()) if book.best_ask() is not None else None}

    def process_order(self, order: Order) -> Tuple[List[Trade], dict]:
        """
        Process an incoming order and return (list_of_trades, resulting_bbo_snapshot).
        This enforces:
          - price-time priority (FIFO at each price)
          - no internal trade-throughs: always match at best prices first
          - correct behavior for MARKET, LIMIT, IOC, FOK
        """
        book = self.get_book(order.symbol)
        trades: List[Trade] = []

        # Determine counter side maps
        if order.side == OrderSide.BUY:
            counter_map = book.asks_map
            counter_prices = book.asks_prices  # ascending
            is_incoming_buy = True
        else:
            counter_map = book.bids_map
            counter_prices = book.bids_prices  # descending
            is_incoming_buy = False

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

        # For FOK: pre-check whether total available at marketable prices >= order.quantity
        if order.order_type == OrderType.FOK:
            total_avail = Decimal("0")
            # sum over all marketable price levels
            for p in list(counter_prices):
                if not price_level_marketable(p):
                    break_if = False
                    # for asks (ascending) if p > order.price then not marketable (and further prices won't be marketable)
                    # for bids (descending) if p < order.price then not marketable
                if price_level_marketable(p):
                    total_avail += sum(o.remaining for o in counter_map.get(p, []))
            if total_avail < order.remaining:
                # Cannot fill entirely -> cancel
                return [], self.bbo(order.symbol)

        # For IOC: we will attempt matching as far as marketable prices and then cancel remainder

        # Matching loop: respect price-time priority:
        # For buys: iterate asks ascending (best asks first). For sells: iterate bids descending (best bids first).
        price_index = 0
        # Using a copy of price list because we may mutate maps during matching
        prices_snapshot = list(counter_prices)
        while order.remaining > 0 and prices_snapshot:
            # pick next price level
            # For buy incoming, prices_snapshot is ascending asks; for sell incoming, descending bids
            level_price = prices_snapshot[0]  # snapshot[0] is best available level
            # check if this level is marketable given order type & price
            if not price_level_marketable(level_price):
                break  # cannot match further without trade-through

            queue = counter_map.get(level_price)
            if not queue:
                # remove this price from snapshot and continue
                prices_snapshot.pop(0)
                continue

            # match against orders at this price FIFO
            while queue and order.remaining > 0:
                resting_order = queue[0]
                # Determine execution price (maker price)
                exec_price = resting_order.price
                exec_qty = min(order.remaining, resting_order.remaining)

                # Create trade
                aggressor_side = order.side.value if isinstance(order.side, OrderSide) else order.side
                trade = Trade(
                    symbol=order.symbol,
                    price=exec_price,
                    quantity=exec_qty,
                    maker_order_id=resting_order.id,
                    taker_order_id=order.id,
                    aggressor_side=aggressor_side
                )
                trades.append(trade)
                self.trades.append(trade)

                # update fills
                resting_order.filled += exec_qty
                order.filled += exec_qty

                # pop resting order if fully filled
                if resting_order.remaining == 0:
                    queue.popleft()

            # after exhausting queue at that price remove empty price level from actual book
            if not queue:
                # remove from the real book maps & price lists
                if order.side == OrderSide.BUY:
                    # We were matching against asks
                    if level_price in book.asks_map and not book.asks_map[level_price]:
                        del book.asks_map[level_price]
                        book._remove_ask_price(level_price)
                else:
                    # matching against bids
                    if level_price in book.bids_map and not book.bids_map[level_price]:
                        del book.bids_map[level_price]
                        book._remove_bid_price(level_price)
                # pop the snapshot front as well
                prices_snapshot.pop(0)
            # else continue at same price level if still have resting orders

            # continue loop until order.remaining == 0 or no marketable levels left

        # Post-matching behavior depending on order type:
        if order.remaining > 0:
            if order.order_type == OrderType.MARKET:
                # Market order: any remaining quantity is canceled (no external book)
                pass  # simply leave remaining unfilled
            elif order.order_type == OrderType.IOC:
                # Immediate-Or-Cancel: matched part stays, remaining is cancelled
                pass
            elif order.order_type == OrderType.FOK:
                # should never be here because we prechecked; if here, we cancel everything and need to rollback trades.
                # BUT we already pre-checked FOK and returned early if not fillable, so we won't reach here.
                pass
            elif order.order_type == OrderType.LIMIT:
                # Limit order: rest the remaining quantity on the book (no trade-through)
                book.add_order(order)
        # If fully filled, do not rest on book

        # Return executed trades and current BBO snapshot
        return trades, {"bid": str(book.best_bid()) if book.best_bid() is not None else None,
                        "ask": str(book.best_ask()) if book.best_ask() is not None else None}
