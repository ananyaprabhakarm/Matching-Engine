from enum import Enum
from datetime import datetime
import uuid

class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    IOC = "ioc"
    FOK = "fok"

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

class Order:
    def __init__(self, symbol: str, order_type: OrderType, side: OrderSide, quantity: float, price: float = None):
        self.id = str(uuid.uuid4())
        self.symbol = symbol
        self.order_type = order_type
        self.side = side
        self.quantity = quantity
        self.price = price
        self.timestamp = datetime.utcnow()
        self.filled = 0

    @property
    def remaining(self):
        return self.quantity - self.filled

    def __repr__(self):
        return f"<Order {self.id} {self.side} {self.quantity}@{self.price} remaining={self.remaining}>"
