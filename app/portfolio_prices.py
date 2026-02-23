"""Fetch live prices for crypto and precious metals."""

import json
import logging
import urllib.request
import urllib.error
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


# Common preset assets with their API symbols
PRESET_ASSETS = [
    {"name": "Goud", "symbol": "XAU", "asset_class": "metal", "unit": "troy oz"},
    {"name": "Zilver", "symbol": "XAG", "asset_class": "metal", "unit": "troy oz"},
    {"name": "Bitcoin", "symbol": "bitcoin", "asset_class": "crypto", "unit": "BTC"},
    {"name": "Ethereum", "symbol": "ethereum", "asset_class": "crypto", "unit": "ETH"},
    {"name": "Solana", "symbol": "solana", "asset_class": "crypto", "unit": "SOL"},
    {"name": "XRP", "symbol": "ripple", "asset_class": "crypto", "unit": "XRP"},
    {"name": "Cardano", "symbol": "cardano", "asset_class": "crypto", "unit": "ADA"},
]
