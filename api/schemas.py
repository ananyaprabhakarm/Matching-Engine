from pydantic import BaseModel, validator
from decimal import Decimal, InvalidOperation
from typing import Optional, Literal

OrderTypeLiteral = Literal["market", "limit", "ioc", "fok", "stop", "stop_limit", "take_profit"]
SideLiteral = Literal["buy", "sell"]

# Order types whose matching semantics compare against order.price (see
# MatchingEngine.process_order's price_level_marketable) - price is mandatory for these,
# not just "limit". Submitting one without a price would otherwise crash the matching loop.
PRICE_REQUIRED_TYPES = ("limit", "ioc", "fok", "stop_limit")
STOP_PRICE_REQUIRED_TYPES = ("stop", "stop_limit", "take_profit")


class OrderRequest(BaseModel):
    symbol: str
    order_type: OrderTypeLiteral
    side: SideLiteral
    quantity: Decimal
    trader_id: str
    price: Optional[Decimal] = None  # required for limit/ioc/fok/stop_limit
    stop_price: Optional[Decimal] = None  # required for stop/stop_limit/take_profit

    @validator("quantity", pre=True)
    def parse_quantity(cls, v):
        try:
            return Decimal(str(v))
        except (InvalidOperation, TypeError):
            raise ValueError("error hai bhai")

    @validator("trader_id")
    def validate_trader_id(cls, v):
        if not v or not v.strip():
            raise ValueError("trader_id is required")
        return v.strip()

    @validator("price", pre=True, always=True)
    def parse_price(cls, v, values):
        if values.get("order_type") in PRICE_REQUIRED_TYPES:
            if v is None:
                raise ValueError("price is required for this order type")
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

    @validator("stop_price", pre=True, always=True)
    def parse_stop_price(cls, v, values):
        if values.get("order_type") in STOP_PRICE_REQUIRED_TYPES:
            if v is None:
                raise ValueError("stop_price is required for this order type")
            try:
                return Decimal(str(v))
            except (InvalidOperation, TypeError):
                raise ValueError("stop_price must be a decimal")
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except (InvalidOperation, TypeError):
            raise ValueError("stop_price must be a decimal")


# WebSocket subscription message
class WSSubscribe(BaseModel):
    action: Literal["subscribe", "unsubscribe"]
    feed: Literal["bbo", "book", "trades"]
    symbol: str
