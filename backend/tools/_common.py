"""Argument validation for tool calls.

Rule: **never trust raw LLM-generated arguments.** Every arg is validated /
coerced against a small schema before a tool runs. Anything malformed is
rejected with a message; the tool does not execute.

Schema shape::

    {"amount": {"type": "amount", "required": True},
     "horizon": {"type": "int_enum", "values": [7, 30, 60, 90], "default": 30},
     "category": {"type": "string", "max_len": 60}}

Identity keys can never be supplied by a caller.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

FORBIDDEN_KEYS = {"user_id", "student_id", "account_id", "id", "sub", "token"}
MAX_STR = 120


def _amount(raw):
    if isinstance(raw, bool):
        raise ValueError("amount must be a number")
    if isinstance(raw, float):
        # accept but via str to stay Decimal-clean
        raw = repr(raw)
    try:
        value = Decimal(str(raw).strip().replace(",", ""))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("amount must be a number")
    if value.is_nan() or value.is_infinite():
        raise ValueError("amount must be a finite number")
    if value <= 0:
        raise ValueError("amount must be greater than 0")
    return str(value)


def _iso_date(raw):
    if isinstance(raw, date):
        return raw.isoformat()
    try:
        return date.fromisoformat(str(raw).strip()).isoformat()
    except (TypeError, ValueError):
        raise ValueError("date must be a valid YYYY-MM-DD date")


def _string(raw, max_len=MAX_STR):
    s = str(raw).strip()
    if not s:
        raise ValueError("value must not be empty")
    return s[:max_len]


def _as_int(raw):
    if isinstance(raw, bool):
        raise ValueError("value must be an integer")
    if isinstance(raw, float) and not raw.is_integer():
        raise ValueError("value must be an integer")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError("value must be an integer")


def _int_range(raw, lo, hi):
    n = _as_int(raw)
    if not (lo <= n <= hi):
        raise ValueError(f"value must be between {lo} and {hi}")
    return n


def _int_enum(raw, values):
    n = _as_int(raw)
    if n not in values:
        raise ValueError(f"value must be one of {sorted(values)}")
    return n


def _enum(raw, values):
    s = str(raw).strip().lower()
    if s not in values:
        raise ValueError(f"value must be one of {sorted(values)}")
    return s


def validate_args(schema: dict, raw_args) -> dict:
    """Return cleaned args. Raise ``ValueError`` on the first problem.

    Unknown keys are ignored (not passed through). Identity keys raise.
    """
    if raw_args is None:
        raw_args = {}
    if not isinstance(raw_args, dict):
        raise ValueError("arguments must be an object")

    for k in raw_args:
        if str(k).lower() in FORBIDDEN_KEYS:
            raise ValueError(f"argument '{k}' is not allowed")

    cleaned = {}
    for name, rule in schema.items():
        present = name in raw_args and raw_args[name] not in (None, "")
        if not present:
            if rule.get("required"):
                raise ValueError(f"'{name}' is required")
            if "default" in rule:
                cleaned[name] = rule["default"]
            continue

        val = raw_args[name]
        kind = rule["type"]
        try:
            if kind == "amount":
                cleaned[name] = _amount(val)
            elif kind == "iso_date":
                cleaned[name] = _iso_date(val)
            elif kind == "string":
                cleaned[name] = _string(val, rule.get("max_len", MAX_STR))
            elif kind == "int_range":
                cleaned[name] = _int_range(val, rule["min"], rule["max"])
            elif kind == "int_enum":
                cleaned[name] = _int_enum(val, set(rule["values"]))
            elif kind == "enum":
                cleaned[name] = _enum(val, set(rule["values"]))
            else:  # pragma: no cover - schema author error
                raise ValueError(f"unknown arg type '{kind}'")
        except ValueError as exc:
            raise ValueError(f"{name}: {exc}") from None

    return cleaned
