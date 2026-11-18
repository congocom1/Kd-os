"""
actions/currency.py — Currency conversion for JARVIS.

Fetches live exchange rates from a public, no-API-key endpoint
(https://api.frankfurter.app) using the already-installed `requests` package.
Results are cached briefly so repeated calls don't hammer the server.

Actions:
  convert   — convert an amount between two currencies (needs 'amount',
              'from', 'to')
  rates     — list rates for a base currency (needs 'base')
  currencies — list all supported currency codes
"""

from __future__ import annotations

import time
from typing import Optional

import requests

from core import outcome

_BASE = "https://api.frankfurter.app/latest"
_CACHE: dict = {}
_CACHE_TTL_SEC = 300  # 5 minutes


def _fetch_rates(base: str) -> Optional[dict]:
    now = time.time()
    cached = _CACHE.get(base)
    if cached and now - cached["ts"] < _CACHE_TTL_SEC:
        return cached["data"]
    try:
        resp = requests.get(_BASE, params={"base": base}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        _CACHE[base] = {"ts": now, "data": data}
        return data
    except Exception:
        return None


def _list_currencies() -> Optional[dict]:
    try:
        resp = requests.get("https://api.frankfurter.app/currencies", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "convert").strip().lower()

    try:
        if action == "convert":
            amount = parameters.get("amount")
            frm = (parameters.get("from") or "").strip().upper()
            to = (parameters.get("to") or "").strip().upper()
            if amount is None or not frm or not to:
                return outcome.failed(
                    "currency", "convert needs 'amount', 'from', and 'to'"
                )
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                return outcome.failed("currency", f"invalid amount: {amount}")
            data = _fetch_rates(frm)
            if not data:
                return outcome.failed(
                    "currency", f"could not fetch rates for base '{frm}'"
                )
            rates = data.get("rates", {})
            if to not in rates:
                return outcome.failed(
                    "currency", f"unsupported target currency '{to}'"
                )
            result = round(amount * rates[to], 4)
            if player:
                try:
                    player.write_log(
                        f"[Currency] {amount} {frm} = {result} {to}"
                    )
                except Exception:
                    pass
            return outcome.done(
                "currency",
                amount=amount,
                from_currency=frm,
                to_currency=to,
                result=result,
                rate=rates[to],
                date=data.get("date"),
            )

        if action == "rates":
            base = (parameters.get("base") or "USD").strip().upper()
            data = _fetch_rates(base)
            if not data:
                return outcome.failed(
                    "currency", f"could not fetch rates for base '{base}'"
                )
            rates = data.get("rates", {})
            top = sorted(rates.items(), key=lambda kv: kv[0])[:10]
            return outcome.done(
                "currency",
                base=base,
                rates=dict(top),
                date=data.get("date"),
                note="showing first 10 currencies alphabetically",
            )

        if action == "currencies":
            data = _list_currencies()
            if not data:
                return outcome.failed("currency", "could not fetch currency list")
            items = sorted(data.items())
            return outcome.done(
                "currency",
                currencies=dict(items),
                count=len(items),
            )

        return outcome.failed("currency", f"unknown action: {action}")

    except Exception as e:
        return outcome.failed("currency", str(e))


TOOL = {
    "name": "currency",
    "description": (
        "Convert currencies using live exchange rates (frankfurter.app, no API "
        "key needed). Actions: 'convert' (needs 'amount', 'from', 'to'), "
        "'rates' (list rates for a base currency), 'currencies' (list all "
        "supported codes). Results are cached for 5 minutes."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "convert | rates | currencies",
            },
            "amount": {
                "type": "NUMBER",
                "description": "Amount to convert (action='convert')",
            },
            "from": {
                "type": "STRING",
                "description": "Source currency code, e.g. 'USD' (action='convert')",
            },
            "to": {
                "type": "STRING",
                "description": "Target currency code, e.g. 'EUR' (action='convert')",
            },
            "base": {
                "type": "STRING",
                "description": "Base currency code for rates (default 'USD')",
            },
        },
        "required": ["action"],
    },
    "handler": run,
}
