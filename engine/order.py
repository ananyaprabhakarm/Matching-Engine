from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import uuid
from enum import Enum
from typing import Optional

class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    IOC = "ioc"
    FOK = "fok"
    STOP = "stop"            # generic stop (market-on-trigger)
    STOP_LIMIT = "stop_limit" # converts to limit on trigger
    TAKE_PROFIT = "take_profit"

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

@dataclass
class Order:
    symbol: str
    order_type: OrderType
    side: OrderSide
    quantity: Decimal
    price: Optional[Decimal] = None   # limit price for LIMIT or STOP_LIMIT
    stop_price: Optional[Decimal] = None  # trigger price for stop orders
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    filled: Decimal = field(default_factory=lambda: Decimal("0"))
    post_only: bool = False  # future use
    meta: dict = field(default_factory=dict)  # extra fields

    @property
    def remaining(self) -> Decimal:
        return self.quantity - self.filled

    def __repr__(self):
        return f"<Order {self.id[:8]} {self.side} {self.quantity}@{self.price} stop={self.stop_price} remaining={self.remaining}>"
