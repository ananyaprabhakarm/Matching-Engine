from datetime import datetime
import uuid

class Trade:
    def __init__(self, symbol: str, price: float, quantity: float, maker_order_id: str, taker_order_id: str, aggressor_side: str):
        self.trade_id = str(uuid.uuid4())
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
        self.maker_order_id = maker_order_id
        self.taker_order_id = taker_order_id
        self.aggressor_side = aggressor_side
        self.timestamp = datetime.utcnow()

    def to_dict(self):
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "price": self.price,
            "quantity": self.quantity,
            "maker_order_id": self.maker_order_id,
            "taker_order_id": self.taker_order_id,
            "aggressor_side": self.aggressor_side,
            "timestamp": self.timestamp.isoformat() + "Z"
        }
