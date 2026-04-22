"""Tests voor de spread-helper die spot-prijzen corrigeert naar
broker-achtige (Goldrepublic) prijzen voor edelmetalen."""
from decimal import Decimal

from app.portfolio_prices import apply_spread


def test_apply_spread_zero_returns_input():
    assert apply_spread(Decimal("100"), Decimal("0")) == Decimal("100")


def test_apply_spread_none_spread_returns_input():
    assert apply_spread(Decimal("100"), None) == Decimal("100")


def test_apply_spread_none_price_returns_none():
    assert apply_spread(None, Decimal("0.6")) is None


def test_apply_spread_goldrepublic_default():
    """0,6% onder spot voor edelmetalen: 4081.63 → ~4057,14."""
    spot = Decimal("4081.63")
    out = apply_spread(spot, Decimal("0.6"))
    # 4081.63 * (1 - 0.006) = 4057.14022
    assert out is not None
    assert abs(out - Decimal("4057.14022")) < Decimal("0.001")


def test_apply_spread_silver_consistent():
    spot = Decimal("67.22")
    out = apply_spread(spot, Decimal("0.6"))
    # 67.22 * 0.994 = 66.81668
    assert out is not None
    assert abs(out - Decimal("66.81668")) < Decimal("0.001")


def test_apply_spread_negative_spread_increases_price():
    """Als de bron juist lager is dan markt: negatieve spread → opwaardering."""
    out = apply_spread(Decimal("100"), Decimal("-2"))
    assert out == Decimal("102")
