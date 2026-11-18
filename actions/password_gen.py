"""
actions/password_gen.py — Secure password and passphrase generation for JARVIS.

Generates cryptographically strong passwords and memorable passphrases using
Python's `secrets` module and the installed `cryptography` package. Nothing is
ever logged, stored, or transmitted — generated values exist only for the
response.

Actions:
  password   — random password (needs 'length', optional 'symbols')
  passphrase — memorable word-based passphrase (needs 'words')
  pin        — numeric PIN (needs 'length')
  uuid       — random UUID v4
"""

from __future__ import annotations

import secrets
import string
import uuid

from core import outcome

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    _CRYPTO = True
except Exception:
    _CRYPTO = False

_WORDLIST = (
    "abbey actor alert alpine amber ancient angel apple apricot arctic "
    "arrow atlas autumn azure banana breeze brilliant bronze bubble "
    "canyon castle cedar chaos chrome compass copper crystal cyclone "
    "daffodil delta desert diamond dragon echo emerald eagle energy "
    "falcon fern fiesta flint forest frost galaxy garden glacier grace "
    "haven hawk helium horizon hydra icon jade jupiter kelp key kingfisher "
    "koi lab lantern laser legacy lemon lion lotus luck lunar magma magnet "
    "mantle maple marble mars mellow mercury meteor mist moon mosaic moss "
    "nebula neon nest night north nova ocean octopus omega onyx opal orbit "
    "orca oxy pacific panda paper parrot pebble penguin pepper petal photon "
    "pine platinum polar puma puzzle quartz quasar quiet quill rabbit radar "
    "rain ranger realm reef relic ridge river rocket rose ruby runway sage "
    "sahara sapphire satellite saturn seal shadow shard shell shift silk "
    "silver skeleton sky slab sloth snow solar solstice sonic south spark "
    "spire squid star steel storm sugar summit sun sunset swan swift tiger "
    "topaz torus tower trail triangle triton turtle twilight umber union "
    "uranus valley vanta vault venus vesta vista vortex wave west whale "
    "willow wind winter wizard wolf yellow yonder zenith zenith"
).split()


def _generate_password(length: int, include_symbols: bool) -> str:
    if length < 4:
        length = 4
    if length > 128:
        length = 128
    alphabet = string.ascii_letters + string.digits
    if include_symbols:
        alphabet += "!@#$%^&*()-_=+[]{}|;:,.<>?/"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _generate_passphrase(words: int, separator: str = "-") -> str:
    if words < 1:
        words = 1
    if words > 12:
        words = 12
    chosen = [secrets.choice(_WORDLIST) for _ in range(words)]
    return separator.join(chosen)


def _generate_pin(length: int) -> str:
    if length < 2:
        length = 2
    if length > 16:
        length = 16
    return "".join(secrets.choice(string.digits) for _ in range(length))


def _strength(length: int, include_symbols: bool) -> str:
    score = length
    if include_symbols:
        score += 10
    if score >= 60:
        return "very strong"
    if score >= 40:
        return "strong"
    if score >= 25:
        return "moderate"
    return "weak"


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "password").strip().lower()

    try:
        if action == "password":
            length = int(parameters.get("length", 16) or 16)
            include_symbols = str(parameters.get("symbols", "true")).lower() in (
                "true", "1", "yes", "y"
            )
            pwd = _generate_password(length, include_symbols)
            if player:
                try:
                    player.write_log(f"[PasswordGen] generated {length}-char password")
                except Exception:
                    pass
            return outcome.done(
                "password_gen",
                password=pwd,
                length=length,
                strength=_strength(length, include_symbols),
            )

        if action == "passphrase":
            words = int(parameters.get("words", 4) or 4)
            sep = parameters.get("separator", "-") or "-"
            phrase = _generate_passphrase(words, sep)
            if player:
                try:
                    player.write_log(f"[PasswordGen] generated {words}-word passphrase")
                except Exception:
                    pass
            return outcome.done(
                "password_gen",
                passphrase=phrase,
                words=words,
                separator=sep,
            )

        if action == "pin":
            length = int(parameters.get("length", 6) or 6)
            pin = _generate_pin(length)
            if player:
                try:
                    player.write_log(f"[PasswordGen] generated {length}-digit PIN")
                except Exception:
                    pass
            return outcome.done("password_gen", pin=pin, length=length)

        if action == "uuid":
            uid = str(uuid.uuid4())
            if player:
                try:
                    player.write_log("[PasswordGen] generated UUID v4")
                except Exception:
                    pass
            return outcome.done("password_gen", uuid=uid)

        return outcome.failed("password_gen", f"unknown action: {action}")

    except Exception as e:
        return outcome.failed("password_gen", str(e))


TOOL = {
    "name": "password_gen",
    "description": (
        "Generate cryptographically secure passwords, passphrases, PINs, and "
        "UUIDs locally. Actions: 'password' (random, needs 'length'), "
        "'passphrase' (memorable words, needs 'words'), 'pin' (numeric, needs "
        "'length'), 'uuid' (random UUID v4). Nothing is logged or stored — "
        "generated values exist only for this response."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "password | passphrase | pin | uuid",
            },
            "length": {
                "type": "INTEGER",
                "description": "Length for password or PIN (default 16 / 6)",
            },
            "symbols": {
                "type": "BOOLEAN",
                "description": "Include symbols in password (default true)",
            },
            "words": {
                "type": "INTEGER",
                "description": "Number of words for passphrase (default 4)",
            },
            "separator": {
                "type": "STRING",
                "description": "Separator between passphrase words (default '-')",
            },
        },
        "required": ["action"],
    },
    "handler": run,
}
