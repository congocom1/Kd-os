"""
Unit Converter skill — converts between common units of length, weight, and temperature.

Auto-discovered by core/plugin_loader at startup.
"""

PLUGIN = {
    "name": "unit_converter",
    "description": (
        "Converts a value between units. Supports length (m, km, mi, ft, in, cm, mm), "
        "weight (kg, g, lb, oz), and temperature (C, F, K). "
        "Specify value, from_unit, and to_unit."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "value": {
                "type": "STRING",
                "description": "The numeric value to convert, e.g. '100'",
            },
            "from_unit": {
                "type": "STRING",
                "description": "Source unit, e.g. 'celsius', 'fahrenheit', 'meters', 'miles', 'kg', 'lbs'",
            },
            "to_unit": {
                "type": "STRING",
                "description": "Target unit, e.g. 'fahrenheit', 'celsius', 'feet', 'kilometers', 'lbs', 'kg'",
            },
        },
        "required": ["value", "from_unit", "to_unit"],
    },
}

def _test_convert(values: dict) -> tuple[bool, str]:
    """Quick sanity check that conversion works."""
    try:
        result = _convert_length(1, "m", "cm")
        return True, f"OK — 1 m = {result} cm"
    except Exception as e:
        return False, f"Error: {e}"


# ── Plugin settings (shown in ⚙ → PLUGINS → unit_converter) ──────────────
PLUGIN_SETTINGS = {
    "namespace": "unit_converter",
    "title": "Unit Converter",
    "fields": [
        {
            "key": "default_precision",
            "label": "Default decimal precision",
            "type": "number",
            "default": 4,
            "placeholder": "4",
        },
    ],
    "action": {
        "label": "TEST CONVERT",
        "run": _test_convert,
    },
}


_LENGTH_TO_M = {  # to metres
    "mm": 0.001, "millimeter": 0.001, "millimetre": 0.001,
    "cm": 0.01, "centimeter": 0.01, "centimetre": 0.01,
    "m": 1.0, "meter": 1.0, "metre": 1.0,
    "km": 1000.0, "kilometer": 1000.0, "kilometre": 1000.0,
    "in": 0.0254, "inch": 0.0254, "inches": 0.0254,
    "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
    "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
    "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
}

_WEIGHT_TO_KG = {
    "g": 0.001, "gram": 0.001, "grams": 0.001,
    "kg": 1.0, "kilogram": 1.0, "kilograms": 1.0,
    "mg": 0.000001, "milligram": 0.000001,
    "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237, "pounds": 0.45359237,
    "oz": 0.02834952, "ounce": 0.02834952, "ounces": 0.02834952,
}

_TEMP_UNITS = {"c", "celsius", "f", "fahrenheit", "k", "kelvin"}


def _norm(s: str) -> str:
    return s.strip().lower()


def _convert_length(value, frm, to):
    """Convert length units.

    Args:
        value: Numeric value to convert.
        frm: From unit (e.g., "m", "km", "ft", "in").
        to: To unit (e.g., "m", "km", "ft", "in").

    Returns:
        Converted value.
    """
    if frm not in _LENGTH_TO_M or to not in _LENGTH_TO_M:
        return None
    return value * _LENGTH_TO_M[frm] / _LENGTH_TO_M[to]


def _convert_weight(value, frm, to):
    """Convert weight units.

    Args:
        value: Numeric value to convert.
        frm: From unit (e.g., "kg", "lb", "g").
        to: To unit (e.g., "kg", "lb", "g").

    Returns:
        Converted value.
    """
    if frm not in _WEIGHT_TO_KG or to not in _WEIGHT_TO_KG:
        return None
    return value * _WEIGHT_TO_KG[frm] / _WEIGHT_TO_KG[to]


def _convert_temp(value, frm, to):
    """Convert temperature units.

    Args:
        value: Numeric value to convert.
        frm: From unit (e.g., "C", "F", "K").
        to: To unit (e.g., "C", "F", "K").

    Returns:
        Converted value.
    """
    # Normalise to Celsius first
    if frm == "c" or frm == "celsius":
        c = value
    elif frm == "f" or frm == "fahrenheit":
        c = (value - 32) * 5 / 9
    elif frm == "k" or frm == "kelvin":
        c = value - 273.15
    else:
        return None
    if to == "c" or to == "celsius":
        return c
    if to == "f" or to == "fahrenheit":
        return c * 9 / 5 + 32
    if to == "k" or to == "kelvin":
        return c + 273.15
    return None


def _tidy(num: float) -> str:
    if abs(num) < 1e-9:
        return "0"
    if num == int(num):
        return str(int(num))
    return f"{num:g}"


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Run unit conversion operation.

    Supports length, weight, and temperature conversions.

    Parameters:
        parameters: Dict with "value", "from_unit", "to_unit" keys.

    Returns:
        Conversion result or error message.
    """
    try:
        value = float(parameters.get("value", ""))
    except (TypeError, ValueError):
        return "Sir, I need a numeric value to convert."

    frm = _norm(parameters.get("from_unit", ""))
    to = _norm(parameters.get("to_unit", ""))
    if not frm or not to:
        return "Sir, please specify both the source and target units."

    result = None
    if frm in _LENGTH_TO_M or to in _LENGTH_TO_M:
        result = _convert_length(value, frm, to)
    elif frm in _WEIGHT_TO_KG or to in _WEIGHT_TO_KG:
        result = _convert_weight(value, frm, to)
    elif frm in _TEMP_UNITS and to in _TEMP_UNITS:
        result = _convert_temp(value, frm, to)

    if result is None:
        return (
            f"Sir, I can't convert '{parameters.get('from_unit')}' to "
            f"'{parameters.get('to_unit')}'. Try metres, miles, kilograms, "
            "pounds, celsius, or fahrenheit."
        )

    if player:
        try:
            player.write_log(
                f"JARVIS: {_tidy(value)} {parameters.get('from_unit')} = "
                f"{_tidy(result)} {parameters.get('to_unit')}"
            )
        except Exception:
            pass
    return (
        f"{_tidy(value)} {parameters.get('from_unit')} = "
        f"{_tidy(result)} {parameters.get('to_unit')}"
    )
