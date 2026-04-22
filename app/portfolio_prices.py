"""Fetch live and historical prices for crypto and precious metals."""

import json
import logging
import urllib.request
import urllib.error
from datetime import date, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)

# Timeout for HTTP requests (seconds)
FETCH_TIMEOUT = 10


def fetch_price(symbol: str, asset_class: str) -> Decimal | None:
    """Fetch current EUR price for an asset. Returns None on failure."""
    try:
        if asset_class == "crypto":
            return _fetch_crypto_price(symbol)
        elif asset_class == "metal":
            return _fetch_metal_price(symbol)
    except Exception as e:
        logger.warning(f"Price fetch failed for {symbol}: {e}")
    return None


def _fetch_crypto_price(coingecko_id: str) -> Decimal | None:
    """Fetch crypto price from CoinGecko (free, no API key).

    symbol should be a CoinGecko ID like 'bitcoin', 'ethereum', 'solana'.
    """
    url = (
        f"https://api.coingecko.com/api/v3/simple/price"
        f"?ids={coingecko_id}&vs_currencies=eur"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        data = json.loads(resp.read())

    price = data.get(coingecko_id, {}).get("eur")
    if price is not None:
        return Decimal(str(price))
    return None


def _fetch_metal_price(symbol: str) -> Decimal | None:
    """Fetch gold/silver price via fawazahmed0 currency API (free, no key).

    symbol: 'XAU' for gold, 'XAG' for silver (price per troy ounce in EUR).
    """
    sym = symbol.lower()  # xau or xag
    url = f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{sym}.json"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        data = json.loads(resp.read())

    eur_rate = data.get(sym, {}).get("eur")
    if eur_rate is not None:
        return Decimal(str(eur_rate))
    return None


def fetch_historical_prices(symbol: str, asset_class: str, months: int = 12) -> dict:
    """Fetch monthly historical prices for the past N months.

    Returns dict: {(year, month): Decimal price_eur}
    """
    try:
        if asset_class == "crypto":
            return _fetch_crypto_history(symbol, months)
        elif asset_class == "metal":
            return _fetch_metal_history(symbol, months)
    except Exception as e:
        logger.warning(f"Historical price fetch failed for {symbol}: {e}")
    return {}


def _fetch_crypto_history(coingecko_id: str, months: int) -> dict:
    """Fetch crypto historical prices from CoinGecko market_chart endpoint.

    Returns monthly prices (1st of each month) for the past N months.
    """
    days = months * 31 + 10  # a bit extra to ensure coverage
    url = (
        f"https://api.coingecko.com/api/v3/coins/{coingecko_id}/market_chart"
        f"?vs_currency=eur&days={days}&interval=daily"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    prices = data.get("prices", [])
    if not prices:
        return {}

    # Group by (year, month) — pick the first data point of each month
    monthly = {}
    for timestamp_ms, price in prices:
        d = date.fromtimestamp(timestamp_ms / 1000)
        key = (d.year, d.month)
        if key not in monthly:
            monthly[key] = Decimal(str(round(price, 4)))

    return monthly


def _fetch_metal_history(symbol: str, months: int) -> dict:
    """Fetch metal historical prices from fawazahmed0 date-based API.

    Fetches the 1st of each month for the past N months.
    """
    sym = symbol.lower()
    monthly = {}
    today = date.today()

    for i in range(months):
        # Calculate 1st of each past month
        target_month = today.month - i
        target_year = today.year
        while target_month <= 0:
            target_month += 12
            target_year -= 1
        target_date = date(target_year, target_month, 1)

        # Skip future dates
        if target_date > today:
            target_date = today

        date_str = target_date.strftime("%Y-%m-%d")
        url = f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date_str}/v1/currencies/{sym}.json"

        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                data = json.loads(resp.read())
            eur_rate = data.get(sym, {}).get("eur")
            if eur_rate is not None:
                monthly[(target_year, target_month)] = Decimal(str(eur_rate))
        except Exception as e:
            logger.debug(f"Metal history fetch for {sym} on {date_str}: {e}")

    return monthly


# Common preset assets with their API symbols. spread_pct = % onder spot dat
# wordt toegepast op de gefetchte prijs (raw spot − spread). Voor edelmetalen
# benadert 0,6% de Goldrepublic-prijs goed; crypto's hebben kleinere spreads
# en blijven op 0.
PRESET_ASSETS = [
    {"name": "Goud", "symbol": "XAU", "asset_class": "metal", "unit": "troy oz", "spread_pct": "0.60"},
    {"name": "Zilver", "symbol": "XAG", "asset_class": "metal", "unit": "troy oz", "spread_pct": "0.60"},
    {"name": "Bitcoin", "symbol": "bitcoin", "asset_class": "crypto", "unit": "BTC", "spread_pct": "0"},
    {"name": "Ethereum", "symbol": "ethereum", "asset_class": "crypto", "unit": "ETH", "spread_pct": "0"},
    {"name": "Solana", "symbol": "solana", "asset_class": "crypto", "unit": "SOL", "spread_pct": "0"},
    {"name": "XRP", "symbol": "ripple", "asset_class": "crypto", "unit": "XRP", "spread_pct": "0"},
    {"name": "Cardano", "symbol": "cardano", "asset_class": "crypto", "unit": "ADA", "spread_pct": "0"},
]


def apply_spread(price: Decimal | None, spread_pct: Decimal | None) -> Decimal | None:
    """Pas een spread (% onder spot) toe op een raw prijs.

    Goldrepublic-style brokers verkopen onder de spot-prijs; door spread_pct
    op `asset.spread_pct` te zetten benaderen we hun werkelijke koers zonder
    een aparte data-feed. None of 0 → ongewijzigd.
    """
    if price is None:
        return None
    if not spread_pct:
        return price
    factor = Decimal("1") - (Decimal(spread_pct) / Decimal("100"))
    return price * factor
