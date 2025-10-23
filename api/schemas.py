# api/schemas.py
from pydantic import BaseModel, validator
from decimal import Decimal, InvalidOperation
from typing import Optional, Literal

OrderTypeLiteral = Literal["market", "limit", "ioc", "fok"]
SideLiteral = Literal["buy", "sell"]

class OrderRequest(BaseModel):
    symbol: str
    order_type: OrderTypeLiteral
    side: SideLiteral
    quantity: Decimal
    price: Optional[Decimal] = None  # required for limit orders

    @validator("quantity", pre=True)
    def parse_quantity(cls, v):
        try:
            return Decimal(str(v))
        except (InvalidOperation, TypeError):
            raise ValueError("error hai bhai")


    @validator("price", pre=True, always=True)
    def parse_price(cls, v, values):
        if values.get("order_type") == "limit":
            if v is None:
                raise ValueError("price is required for limit orders")
            try:
                return Decimal(str(v))
            except (InvalidOperation, TypeError):
                raise ValueError("price must be a decimal")
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except (InvalidOperation, TypeError):
            raise ValueError("price must be a decimal")

# WebSocket subscription message
class WSSubscribe(BaseModel):
    action: Literal["subscribe", "unsubscribe"]
    feed: Literal["bbo", "book", "trades"]
    symbol: str
