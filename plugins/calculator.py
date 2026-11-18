"""
Calculator skill — basic arithmetic for JARVIS.

Auto-discovered by core/plugin_loader at startup. Copy this pattern for new skills.
"""

import logging
logger = logging.getLogger(__name__)

import operator
import re

PLUGIN = {
    "name": "calculator",
    "description": (
        "Evaluates a simple arithmetic expression (add, subtract, multiply, "
        "divide, parentheses, integers or decimals). Use this for any maths "
        "question — do not attempt mental arithmetic. Only handles one "
        "expression at a time."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "expression": {
                "type": "STRING",
                "description": "A single arithmetic expression, e.g. '12 * (4 + 3) / 2'",
            },
        },
        "required": ["expression"],
    },
}

def _test_calc(values: dict) -> tuple[bool, str]:
    """Quick sanity check that arithmetic works."""
    try:
        result = _safe_eval("2 + 2 * 3")
        return True, f"OK — 2 + 2 * 3 = {result}"
    except Exception as e:
        return False, f"Error: {e}"


# ── Plugin settings (shown in ⚙ → PLUGINS → calculator) ───────────────────
PLUGIN_SETTINGS = {
    "namespace": "calculator",
    "title": "Calculator",
    "fields": [
        {
            "key": "max_result_digits",
            "label": "Max result digits",
            "type": "number",
            "default": 10,
            "placeholder": "10",
        },
    ],
    "action": {
        "label": "TEST CALC",
        "run": _test_calc,
    },
}


_OPS = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "//": operator.floordiv,
    "%": operator.mod,
    "**": operator.pow,
}

# Only digits, whitespace, decimal points and the operators above are allowed.
_ALLOWED = re.compile(r"^[0-9\s\.\+\-\*\/\%\(\)]+$")


def _safe_eval(expression: str) -> float:
    """Safely evaluate a mathematical expression.

    Never calls eval(). Parses the expression into tokens and applies them
    with the operator module.

    Args:
        expression: Mathematical expression string.

    Returns:
        Result of the evaluation as float.
    """
    tokens = re.findall(r"\d+\.?\d*|[\(\)\+\-\*/\%]", expression.replace(" ", ""))
    # Convert '**' style: our regex splits '*' so 'a ** b' becomes '*','*' —
    # handle power by folding adjacent '*' pairs.
    folded = []
    i = 0
    while i < len(tokens):
        if tokens[i] == "*" and i + 1 < len(tokens) and tokens[i + 1] == "*":
            folded.append("**")
            i += 2
        else:
            folded.append(tokens[i])
            i += 1
    # Shunting-yard: to postfix (RPN), then evaluate.
    prec = {"+": 1, "-": 1, "*": 2, "/": 2, "//": 2, "%": 2, "**": 3}
    out = []
    stack = []
    for tok in folded:
        if re.match(r"\d+\.?\d*$", tok):
            out.append(float(tok))
        elif tok == "(":
            stack.append(tok)
        elif tok == ")":
            while stack and stack[-1] != "(":
                out.append(stack.pop())
            if not stack:
                raise ValueError("Mismatched parentheses")
            stack.pop()  # discard '('
        else:  # operator
            while (
                stack
                and stack[-1] != "("
                and prec.get(stack[-1], 0) >= prec.get(tok, 0)
            ):
                out.append(stack.pop())
            stack.append(tok)
    while stack:
        if stack[-1] in "()":
            raise ValueError("Mismatched parentheses")
        out.append(stack.pop())

    eval_stack = []
    for item in out:
        if isinstance(item, float):
            eval_stack.append(item)
        else:
            b = eval_stack.pop()
            a = eval_stack.pop()
            if item == "/" and b == 0:
                raise ZeroDivisionError("Division by zero")
            eval_stack.append(_OPS[item](a, b))
    return eval_stack[0]


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Run calculator operation.

    Supports basic arithmetic operations: +, -, *, /, and advanced functions.

    Parameters:
        parameters: Dict with "expression" key containing the math expression.

    Returns:
        Result string or error message.
    """
    expression = (parameters.get("expression") or "").strip()
    if not expression:
        return "Sir, please give me an expression to calculate."

    if not _ALLOWED.match(expression):
        return "Sir, that expression contains characters I can't calculate with."

    try:
        result = _safe_eval(expression)
    except ZeroDivisionError:
        return "Sir, I can't divide by zero."
    except Exception as e:
        logger.error("Expression evaluation error", exc_info=True)
        return "I had trouble evaluating that expression."

    # Tidy up trailing .0 for whole numbers.
    if result == int(result):
        result = int(result)
    answer = f"The answer is {result}."
    if player:
        try:
            player.write_log(f"JARVIS: {answer}")
        except Exception:
            pass
    return answer
