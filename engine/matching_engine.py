from engine.order_book import OrderBook
from engine.order import OrderType, OrderSide
from engine.trade import Trade

class MatchingEngine:
    def __init__(self):
        self.order_books = {}  # symbol -> OrderBook
        self.trade_history = []  # store executed trades

    def get_order_book(self, symbol: str) -> OrderBook:
        if symbol not in self.order_books:
            self.order_books[symbol] = OrderBook(symbol)
        return self.order_books[symbol]

    def process_order(self, order):
        book = self.get_order_book(order.symbol)
        trades = []

        if order.side == OrderSide.BUY:
            trades = self.match_order(order, book.asks, OrderSide.SELL)
        else:
            trades = self.match_order(order, book.bids, OrderSide.BUY)

        # If remaining quantity, add to book (for limit orders)
        if order.remaining > 0 and order.order_type in [OrderType.LIMIT]:
            book.add_order(order)

        return trades

    def match_order(self, incoming_order, book_side, counter_side):
        trades = []

        # Sort price levels based on priority
        price_levels = sorted(book_side.keys())
        if incoming_order.side == OrderSide.BUY:
            price_levels = sorted(book_side.keys())  # ascending prices for asks
        else:
            price_levels = sorted(book_side.keys(), reverse=True)  # descending prices for bids

        for price in price_levels:
            if incoming_order.remaining <= 0:
                break

            # Check if the price is marketable
            if incoming_order.order_type in [OrderType.MARKET, OrderType.IOC, OrderType.FOK] or \
               (incoming_order.side == OrderSide.BUY and price <= incoming_order.price) or \
               (incoming_order.side == OrderSide.SELL and price >= incoming_order.price):

                orders_at_price = book_side[price]
                while orders_at_price and incoming_order.remaining > 0:
                    resting_order = orders_at_price[0]
                    trade_qty = min(incoming_order.remaining, resting_order.remaining)
                    trade_price = resting_order.price

                    trade = Trade(
                        symbol=incoming_order.symbol,
                        price=trade_price,
                        quantity=trade_qty,
                        maker_order_id=resting_order.id,
                        taker_order_id=incoming_order.id,
                        aggressor_side=incoming_order.side.value
                    )
                    trades.append(trade)
                    self.trade_history.append(trade)

                    # Update filled quantities
                    incoming_order.filled += trade_qty
                    resting_order.filled += trade_qty

                    if resting_order.remaining == 0:
                        orders_at_price.popleft()
                    if not orders_at_price:
                        del book_side[price]

        return trades
