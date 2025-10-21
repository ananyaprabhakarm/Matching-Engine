# engine/order.py
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import uuid
from enum import Enum

class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    IOC = "ioc"
    FOK = "fok"

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

@dataclass
class Order:
    symbol: str
    order_type: OrderType
    side: OrderSide
    quantity: Decimal
    price: Decimal | None = None  # None for market orders
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    filled: Decimal = field(default_factory=lambda: Decimal("0"))

    @property
    def remaining(self) -> Decimal:
        return self.quantity - self.filled

    def __repr__(self):
        return (
            f"Order(id={self.id[:8]}, {self.side} {self.quantity}@{self.price}, "
            f"remaining={self.remaining}, ts={self.timestamp.isoformat()})"
        )
