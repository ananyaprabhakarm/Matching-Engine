from dataclasses import dataclass, asdict, field
from datetime import datetime
from decimal import Decimal
import uuid

@dataclass
class Trade:
    symbol: str
    price: Decimal
    quantity: Decimal
    maker_order_id: str
    taker_order_id: str
    aggressor_side: str             
    maker_fee: Decimal = field(default_factory=lambda: Decimal("0"))
    taker_fee: Decimal = field(default_factory=lambda: Decimal("0"))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self):
        return {
            "timestamp": self.timestamp.isoformat() + "Z",
            "symbol": self.symbol,
            "trade_id": self.trade_id,
            "price": str(self.price),
            "quantity": str(self.quantity),
            "aggressor_side": self.aggressor_side,
            "maker_order_id": self.maker_order_id,
            "taker_order_id": self.taker_order_id,
            "maker_fee": str(self.maker_fee),
            "taker_fee": str(self.taker_fee),
        }
