from collections import deque
from decimal import Decimal
from typing import Deque, Dict, List, Tuple
from engine.order import Order, OrderSide, OrderType
import bisect

class OrderBook:
    """
    Maintain price levels for bids and asks.
    bids_prices: list of Decimal prices sorted DESC (best bid first)
    asks_prices: list of Decimal prices sorted ASC (best ask first)
    price_map: price -> deque[Order] for FIFO at that price
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        # price -> deque of orders (FIFO)
        self.bids_map: Dict[Decimal, Deque[Order]] = {}
        self.asks_map: Dict[Decimal, Deque[Order]] = {}
        # sorted price lists for efficient best price lookups
        self.bids_prices: List[Decimal] = []  # descending
        self.asks_prices: List[Decimal] = []  # ascending
        # inside OrderBook.__init__
        self.trigger_orders = []  # list[Order] - orders waiting for trigger

    def add_trigger_order(self, order: Order):
        self.trigger_orders.append(order)

    def check_and_activate_triggers(self, last_trade_price: Decimal = None):
        """
        Evaluate trigger orders and return list of orders that should be activated now.
        Activation rules:
        - Stop-Loss SELL: trigger if last_trade_price <= stop_price
        - Stop-Loss BUY: trigger if last_trade_price >= stop_price (buy stop triggers above)
        - Take-Profit SELL: trigger if last_trade_price >= stop_price
        - etc...
        On activation, remove from trigger_orders and return list of activated orders.
        """
        activated = []
        remaining = []
        for o in self.trigger_orders:
            triggered = False
            sp = o.stop_price
            if sp is None:
                continue
            if o.order_type == OrderType.STOP:
                # STOP -> market-on-trigger
                if o.side == OrderSide.SELL and last_trade_price is not None and last_trade_price <= sp:
                    triggered = True
                if o.side == OrderSide.BUY and last_trade_price is not None and last_trade_price >= sp:
                    triggered = True
            elif o.order_type == OrderType.STOP_LIMIT:
                # STOP_LIMIT -> becomes LIMIT at `price` when triggered
                if o.side == OrderSide.SELL and last_trade_price is not None and last_trade_price <= sp:
                    triggered = True
                if o.side == OrderSide.BUY and last_trade_price is not None and last_trade_price >= sp:
                    triggered = True
            elif o.order_type == OrderType.TAKE_PROFIT:
                # take profit: SELL take profit triggers when price >= sp
                if o.side == OrderSide.SELL and last_trade_price is not None and last_trade_price >= sp:
                    triggered = True
                if o.side == OrderSide.BUY and last_trade_price is not None and last_trade_price <= sp:
                    triggered = True

            if triggered:
                activated.append(o)
            else:
                remaining.append(o)
        self.trigger_orders = remaining
        return activated


    # -------------------------
    # helpers for price lists
    # -------------------------
    def _insert_bid_price(self, price: Decimal):
        # bids_prices is sorted descending
        idx = bisect.bisect_left([ -p for p in self.bids_prices ], -price)
        self.bids_prices.insert(idx, price)

    def _insert_ask_price(self, price: Decimal):
        # asks_prices is sorted ascending
        idx = bisect.bisect_left(self.asks_prices, price)
        self.asks_prices.insert(idx, price)

    def _remove_bid_price(self, price: Decimal):
        try:
            self.bids_prices.remove(price)
        except ValueError:
            pass

    def _remove_ask_price(self, price: Decimal):
        try:
            self.asks_prices.remove(price)
        except ValueError:
            pass

    # -------------------------
    # add/remove orders
    # -------------------------
    def add_order(self, order: Order):
        if order.side == OrderSide.BUY:
            pm = self.bids_map
            if order.price not in pm:
                pm[order.price] = deque()
                self._insert_bid_price(order.price)
            pm[order.price].append(order)
        else:
            pm = self.asks_map
            if order.price not in pm:
                pm[order.price] = deque()
                self._insert_ask_price(order.price)
            pm[order.price].append(order)

    def remove_empty_price_level(self, side: OrderSide, price):
        if side == OrderSide.BUY:
            pm = self.bids_map
            if price in pm and not pm[price]:
                del pm[price]
                self._remove_bid_price(price)
        else:
            pm = self.asks_map
            if price in pm and not pm[price]:
                del pm[price]
                self._remove_ask_price(price)

    # -------------------------
    # best bid / ask (BBO)
    # -------------------------
    def best_bid(self):
        return self.bids_prices[0] if self.bids_prices else None

    def best_ask(self):
        return self.asks_prices[0] if self.asks_prices else None

    def top_n(self, n=10):
        """Return top n levels as list of (price, total_qty) for bids and asks"""
        bids = []
        asks = []
        for p in self.bids_prices[:n]:
            total = sum(o.remaining for o in self.bids_map.get(p, []))
            bids.append((str(p), str(total)))
        for p in self.asks_prices[:n]:
            total = sum(o.remaining for o in self.asks_map.get(p, []))
            asks.append((str(p), str(total)))
        return {"bids": bids, "asks": asks}

    # -------------------------
    # helper to compute available quantities up to a limit price
    # -------------------------
    def available_qty_on_side_up_to_price(self, side: OrderSide, limit_price=None) -> Decimal:
        """
        Calculate aggregate available qty on the given side that is marketable
        relative to a given limit price.
        For a taker buy with limit_price P, available asks priced <= P are considered.
        For market taker (limit_price is None) all opposite side levels count.
        """
        from decimal import Decimal
        total = Decimal("0")
        if side == OrderSide.BUY:
            # count bids (we usually use this if incoming is sell)
            price_list = self.bids_prices
            pm = self.bids_map
            # descending price list for bids
            for p in price_list:
                if limit_price is not None and p > limit_price:
                    continue
                total += sum(o.remaining for o in pm.get(p, []))
        else:
            # count asks (incoming buy)
            price_list = self.asks_prices
            pm = self.asks_map
            for p in price_list:
                if limit_price is not None and p < limit_price:
                    continue
                total += sum(o.remaining for o in pm.get(p, []))
        return total
