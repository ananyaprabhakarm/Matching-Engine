# engine/trade.py
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
    aggressor_side: str  # "buy" or "sell"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self):
        # Convert Decimal to string for JSON serialization
        return {
            "trade_id": self.trade_id,
            "timestamp": self.timestamp.isoformat() + "Z",
            "symbol": self.symbol,
            "price": str(self.price),
            "quantity": str(self.quantity),
            "maker_order_id": self.maker_order_id,
            "taker_order_id": self.taker_order_id,
            "aggressor_side": self.aggressor_side,
        }
