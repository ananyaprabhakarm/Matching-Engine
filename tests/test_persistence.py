import json

import pytest
from decimal import Decimal

from engine.matching_engine import MatchingEngine
from engine.order import Order, OrderType, OrderSide
from engine.persistence import SNAPSHOT_FILE, EVENT_LOG_FILE


@pytest.fixture(autouse=True)
def clean_files():
    for f in (SNAPSHOT_FILE, EVENT_LOG_FILE):
        if f.exists():
            f.unlink()
    yield
    for f in (SNAPSHOT_FILE, EVENT_LOG_FILE):
        if f.exists():
            f.unlink()


def make_order(**kwargs):
    defaults = dict(symbol="BTC-USDT", trader_id="trader")
    defaults.update(kwargs)
    return Order(**defaults)


def test_crash_recovery_replays_event_log_to_matching_state():
    # No periodic snapshot ever runs in this test (the persist loop isn't started),
    # so the event log is the only record of what happened - simulating a crash
    # before any checkpoint was taken.
    engine1 = MatchingEngine()

    engine1.process_order(make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL,
                                      price=Decimal("100"), quantity=Decimal("1"), trader_id="bob"))
    engine1.process_order(make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY,
                                      price=Decimal("100"), quantity=Decimal("1"), trader_id="alice"))
    carol_order = make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY,
                              price=Decimal("90"), quantity=Decimal("2"), trader_id="carol")
    engine1.process_order(carol_order)

    pre_crash_bbo = engine1.bbo("BTC-USDT")
    pre_crash_trade_count = len(engine1.trades)
    assert pre_crash_trade_count == 1  # alice/bob matched, carol still resting

    # "crash": engine1 is simply dropped, nothing explicitly saved.
    del engine1

    # "restart": a fresh process would construct a fresh MatchingEngine, which
    # replays the event log left on disk.
    engine2 = MatchingEngine()

    assert engine2.bbo("BTC-USDT") == pre_crash_bbo
    assert len(engine2.trades) == pre_crash_trade_count  # replayed once, not duplicated

    carols_open_orders = engine2.get_open_orders("carol")
    assert len(carols_open_orders) == 1
    assert carols_open_orders[0].price == Decimal("90")
    assert carols_open_orders[0].remaining == Decimal("2")


def test_cancellation_survives_replay():
    engine1 = MatchingEngine()
    engine1.process_order(
        make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY, price=Decimal("50"),
                   quantity=Decimal("1"), trader_id="alice")
    )
    # find the order we just placed via the open-orders listing (process_order doesn't
    # hand back the Order object itself, only trades/bbo/stp)
    open_orders = engine1.get_open_orders("alice")
    assert len(open_orders) == 1
    engine1.cancel_order(open_orders[0].id, "alice")
    assert engine1.get_open_orders("alice") == []

    del engine1
    engine2 = MatchingEngine()

    assert engine2.get_open_orders("alice") == []
    assert engine2.bbo("BTC-USDT")["bid"] is None


def test_event_log_is_append_only_and_line_delimited_json():
    engine = MatchingEngine()
    engine.process_order(make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL,
                                     price=Decimal("10"), quantity=Decimal("1"), trader_id="bob"))

    assert EVENT_LOG_FILE.exists()
    with open(EVENT_LOG_FILE) as f:
        lines_after_first = f.readlines()

    for line in lines_after_first:
        event = json.loads(line)  # every line must be independently valid JSON
        assert "type" in event and "ts" in event

    engine.process_order(make_order(order_type=OrderType.LIMIT, side=OrderSide.BUY,
                                     price=Decimal("10"), quantity=Decimal("1"), trader_id="alice"))

    with open(EVENT_LOG_FILE) as f:
        lines_after_second = f.readlines()

    # strictly appended: every previously-written line is untouched, more were added
    assert lines_after_second[: len(lines_after_first)] == lines_after_first
    assert len(lines_after_second) > len(lines_after_first)


def test_periodic_snapshot_truncates_the_event_log():
    engine = MatchingEngine()
    engine.process_order(make_order(order_type=OrderType.LIMIT, side=OrderSide.SELL,
                                     price=Decimal("100"), quantity=Decimal("1"), trader_id="bob"))
    assert EVENT_LOG_FILE.exists()

    engine.save_state_now()  # the same checkpoint the periodic persist loop performs

    assert SNAPSHOT_FILE.exists()
    assert not EVENT_LOG_FILE.exists()  # already captured in the snapshot - nothing left to replay

    engine2 = MatchingEngine()
    assert engine2.bbo("BTC-USDT")["ask"] == "100"
