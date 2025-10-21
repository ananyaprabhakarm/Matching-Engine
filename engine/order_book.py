from collections import defaultdict, deque
from engine.order import Order, OrderSide

class OrderBook:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids = defaultdict(deque)  # price -> deque of orders
        self.asks = defaultdict(deque)
        self.bbo = {"bid": None, "ask": None}

    def add_order(self, order: Order):
        book = self.bids if order.side == OrderSide.BUY else self.asks
        book[order.price].append(order)
        self.update_bbo()

    def remove_order(self, order: Order):
        book = self.bids if order.side == OrderSide.BUY else self.asks
        if order.price in book and order in book[order.price]:
            book[order.price].remove(order)
            if not book[order.price]:
                del book[order.price]
        self.update_bbo()

    def update_bbo(self):
        self.bbo["bid"] = max(self.bids.keys()) if self.bids else None
        self.bbo["ask"] = min(self.asks.keys()) if self.asks else None

    def get_best_bid(self):
        return self.bbo["bid"]

    def get_best_ask(self):
        return self.bbo["ask"]

    def __repr__(self):
        return f"<OrderBook {self.symbol} BBO: {self.bbo}>"
