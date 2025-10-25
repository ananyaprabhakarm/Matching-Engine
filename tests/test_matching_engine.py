import pytest
from decimal import Decimal
from engine.matching_engine import MatchingEngine
from engine.order import Order, OrderType, OrderSide

@pytest.fixture
def engine():
    return MatchingEngine()

def test_limit_order_matching(engine):
    # Step 1: Add resting limit order
    sell_order = Order(symbol="BTC-USDT", order_type=OrderType.LIMIT,
                       side=OrderSide.SELL, price=Decimal("100"), quantity=Decimal("1"))
    engine.process_order(sell_order)

    # Step 2: Match with a buy order
    buy_order = Order(symbol="BTC-USDT", order_type=OrderType.LIMIT,
                      side=OrderSide.BUY, price=Decimal("105"), quantity=Decimal("1"))
    trades, bbo = engine.process_order(buy_order)

    assert len(trades) == 1
    assert trades[0].price == Decimal("100")
    assert trades[0].quantity == Decimal("1")
    assert bbo["bid"] is None and bbo["ask"] is None
