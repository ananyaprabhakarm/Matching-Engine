import pytest
from decimal import Decimal
from engine.matching_engine import MatchingEngine
from engine.order import Order, OrderType, OrderSide
from engine.persistence import SNAPSHOT_FILE, EVENT_LOG_FILE


@pytest.fixture(autouse=True)
def clean_snapshot():
    # MatchingEngine() loads any existing snapshot AND replays any existing event
    # log on init - make sure tests never pick up state left behind by a previous
    # run, a manually-started server, or a previous test in this same session.
    for f in (SNAPSHOT_FILE, EVENT_LOG_FILE):
        if f.exists():
            f.unlink()
    yield
    for f in (SNAPSHOT_FILE, EVENT_LOG_FILE):
        if f.exists():
            f.unlink()


@pytest.fixture
def engine():
    return MatchingEngine()


def make_order(**kwargs):
    defaults = dict(symbol="BTC-USDT", trader_id="trader")
    defaults.update(kwargs)
    return Order(**defaults)


def test_limit_order_matching(engine):
    # Step 1: Add resting limit order
    sell_order = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL,
                             price=Decimal("100"), quantity=Decimal("1"), trader_id="bob")
    engine.process_order(sell_order)

    # Step 2: Match with a buy order
    buy_order = make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY,
                            price=Decimal("105"), quantity=Decimal("1"), trader_id="alice")
    trades, bbo, stp = engine.process_order(buy_order)

    assert len(trades) == 1
    assert trades[0].price == Decimal("100")
    assert trades[0].quantity == Decimal("1")
    assert bbo["bid"] is None and bbo["ask"] is None
    assert stp is False


def test_market_order_fills_and_cancels_remainder(engine):
    sell = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("100"),
                       quantity=Decimal("1"), trader_id="bob")
    engine.process_order(sell)

    buy = make_order(order_type=OrderType.MARKET, side=OrderSide.BUY, quantity=Decimal("3"),
                      trader_id="alice")
    trades, bbo, stp = engine.process_order(buy)

    assert len(trades) == 1
    assert trades[0].quantity == Decimal("1")
    assert buy.remaining == Decimal("2")  # unfilled remainder is simply dropped, not rested
    assert bbo["ask"] is None


def test_ioc_partial_fill_cancels_remainder(engine):
    sell = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("100"),
                       quantity=Decimal("1"), trader_id="bob")
    engine.process_order(sell)

    buy = make_order(order_type=OrderType.IOC, side=OrderSide.BUY, price=Decimal("100"),
                      quantity=Decimal("3"), trader_id="alice")
    trades, bbo, stp = engine.process_order(buy)

    assert len(trades) == 1
    assert trades[0].quantity == Decimal("1")
    assert buy.remaining == Decimal("2")
    assert bbo["bid"] is None  # remainder never rests on the book


def test_fok_rejects_when_insufficient_liquidity(engine):
    sell = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("100"),
                       quantity=Decimal("1"), trader_id="bob")
    engine.process_order(sell)

    buy = make_order(order_type=OrderType.FOK, side=OrderSide.BUY, price=Decimal("100"),
                      quantity=Decimal("5"), trader_id="alice")
    trades, bbo, stp = engine.process_order(buy)

    assert trades == []
    assert buy.remaining == Decimal("5")  # rejected outright, nothing touched
    assert bbo["ask"] == "100"  # bob's resting sell is untouched


def test_fok_fills_when_liquidity_sufficient(engine):
    sell = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("100"),
                       quantity=Decimal("5"), trader_id="bob")
    engine.process_order(sell)

    buy = make_order(order_type=OrderType.FOK, side=OrderSide.BUY, price=Decimal("100"),
                      quantity=Decimal("5"), trader_id="alice")
    trades, bbo, stp = engine.process_order(buy)

    assert len(trades) == 1
    assert trades[0].quantity == Decimal("5")
    assert buy.remaining == Decimal("0")


def test_fok_excludes_self_liquidity_from_availability_check(engine):
    # the only liquidity at this price belongs to alice herself - it can never be
    # matched (self-trade prevention), so it must not count toward "is this fillable".
    alice_sell = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("100"),
                             quantity=Decimal("5"), trader_id="alice")
    engine.process_order(alice_sell)

    alice_buy = make_order(order_type=OrderType.FOK, side=OrderSide.BUY, price=Decimal("100"),
                            quantity=Decimal("5"), trader_id="alice")
    trades, bbo, stp = engine.process_order(alice_buy)

    assert trades == []
    assert bbo["ask"] == "100"  # alice_sell still rests, untouched


def test_fee_calculation_maker_taker(engine):
    sell = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("100"),
                       quantity=Decimal("2"), trader_id="bob")
    engine.process_order(sell)

    buy = make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY, price=Decimal("100"),
                      quantity=Decimal("2"), trader_id="alice")
    trades, bbo, stp = engine.process_order(buy)

    trade = trades[0]
    trade_value = Decimal("100") * Decimal("2")
    assert trade.maker_fee == trade_value * Decimal("0.001")
    assert trade.taker_fee == trade_value * Decimal("0.002")
    assert trade.maker_trader_id == "bob"
    assert trade.taker_trader_id == "alice"


def test_price_time_priority_fifo(engine):
    first = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("100"),
                        quantity=Decimal("1"), trader_id="bob")
    second = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("100"),
                         quantity=Decimal("1"), trader_id="carol")
    engine.process_order(first)
    engine.process_order(second)

    buy = make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY, price=Decimal("100"),
                      quantity=Decimal("1"), trader_id="alice")
    trades, bbo, stp = engine.process_order(buy)

    assert len(trades) == 1
    assert trades[0].maker_order_id == first.id  # earlier order at the same price fills first
    assert bbo["ask"] == "100"  # carol's order still rests


def test_cancel_order_success(engine):
    order = make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY, price=Decimal("100"),
                        quantity=Decimal("1"), trader_id="alice")
    engine.process_order(order)

    result = engine.cancel_order(order.id, "alice")

    assert result == "ok"
    assert engine.bbo("BTC-USDT")["bid"] is None
    assert engine.get_open_orders("alice") == []


def test_cancel_order_wrong_trader_rejected(engine):
    order = make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY, price=Decimal("100"),
                        quantity=Decimal("1"), trader_id="alice")
    engine.process_order(order)

    result = engine.cancel_order(order.id, "bob")

    assert result == "forbidden"
    assert engine.bbo("BTC-USDT")["bid"] == "100"  # order untouched


def test_cancel_order_not_found(engine):
    assert engine.cancel_order("does-not-exist", "alice") == "not_found"


def test_cancel_order_already_filled_rejected(engine):
    sell = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("100"),
                       quantity=Decimal("1"), trader_id="bob")
    engine.process_order(sell)
    buy = make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY, price=Decimal("100"),
                      quantity=Decimal("1"), trader_id="alice")
    engine.process_order(buy)  # fully fills sell

    result = engine.cancel_order(sell.id, "bob")

    assert result == "already_filled"


def test_self_trade_prevention_skips_own_order_but_matches_others(engine):
    alice_sell = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("100"),
                             quantity=Decimal("1"), trader_id="alice")
    bob_sell = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("100"),
                           quantity=Decimal("1"), trader_id="bob")
    engine.process_order(alice_sell)
    engine.process_order(bob_sell)

    alice_buy = make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY, price=Decimal("100"),
                            quantity=Decimal("1"), trader_id="alice")
    trades, bbo, stp = engine.process_order(alice_buy)

    assert stp is True
    assert len(trades) == 1
    assert trades[0].maker_order_id == bob_sell.id  # matched bob's order, skipped her own
    # alice's own resting sell must still be there, untouched
    assert any(o.id == alice_sell.id for o in engine.get_open_orders("alice"))


def test_stop_order_triggers_on_crossing_trade(engine):
    stop = make_order(order_type=OrderType.STOP, side=OrderSide.SELL, quantity=Decimal("1"),
                       stop_price=Decimal("95"), trader_id="alice")
    trades, bbo, stp_flag = engine.process_order(stop)
    assert trades == []  # rests as a pending trigger, doesn't match anything yet

    bid = make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY, price=Decimal("90"),
                      quantity=Decimal("5"), trader_id="carol")
    engine.process_order(bid)

    # a trade at/below 95 should trigger alice's stop-sell
    crossing_sell = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("90"),
                                quantity=Decimal("1"), trader_id="dave")
    trades, bbo, stp_flag = engine.process_order(crossing_sell)

    # dave's sell trades against carol's bid; that trade price (90) triggers alice's
    # stop, which becomes a market sell that also matches carol's remaining bid
    assert len(trades) == 2
    taker_ids = {t.taker_trader_id for t in trades}
    assert taker_ids == {"dave", "alice"}


def test_stop_limit_order_triggers_and_rests(engine):
    stop_limit = make_order(order_type=OrderType.STOP_LIMIT, side=OrderSide.SELL, quantity=Decimal("1"),
                             stop_price=Decimal("95"), price=Decimal("94"), trader_id="alice")
    engine.process_order(stop_limit)

    bid = make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY, price=Decimal("90"),
                      quantity=Decimal("1"), trader_id="carol")
    engine.process_order(bid)

    sell_trigger = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("90"),
                               quantity=Decimal("1"), trader_id="dave")
    engine.process_order(sell_trigger)

    open_orders = engine.get_open_orders("alice")
    assert len(open_orders) == 1
    assert open_orders[0].order_type == OrderType.LIMIT
    assert open_orders[0].price == Decimal("94")


def test_take_profit_triggers(engine):
    take_profit = make_order(order_type=OrderType.TAKE_PROFIT, side=OrderSide.SELL, quantity=Decimal("1"),
                              stop_price=Decimal("110"), trader_id="alice")
    engine.process_order(take_profit)

    bid = make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY, price=Decimal("110"),
                      quantity=Decimal("5"), trader_id="carol")
    engine.process_order(bid)

    crossing_sell = make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL, price=Decimal("110"),
                                quantity=Decimal("1"), trader_id="dave")
    trades, bbo, stp_flag = engine.process_order(crossing_sell)

    taker_ids = {t.taker_trader_id for t in trades}
    assert "alice" in taker_ids
