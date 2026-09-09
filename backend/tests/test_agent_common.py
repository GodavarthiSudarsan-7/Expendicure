"""tools/_common.validate_args — never trust raw LLM args."""

import pytest

from tools._common import validate_args

SCHEMA = {
    "amount": {"type": "amount", "required": True},
    "horizon": {"type": "int_enum", "values": [7, 30, 60, 90], "default": 30},
    "when": {"type": "iso_date"},
    "note": {"type": "string", "max_len": 10},
    "limit": {"type": "int_range", "min": 1, "max": 5},
    "dir": {"type": "enum", "values": ["debit", "credit"]},
}


def test_valid_args_pass_and_coerce():
    out = validate_args(SCHEMA, {"amount": "1,200.50", "horizon": "60", "when": "2026-09-30",
                                 "note": "hello world!!", "limit": 3, "dir": "DEBIT"})
    assert out["amount"] == "1200.50"
    assert out["horizon"] == 60
    assert out["when"] == "2026-09-30"
    assert out["note"] == "hello worl"  # truncated to max_len
    assert out["limit"] == 3
    assert out["dir"] == "debit"


def test_defaults_applied():
    out = validate_args(SCHEMA, {"amount": 5})
    assert out["horizon"] == 30
    assert "when" not in out


def test_missing_required_rejected():
    with pytest.raises(ValueError):
        validate_args(SCHEMA, {"horizon": 30})


@pytest.mark.parametrize("bad", ["abc", "-5", "0", "NaN", "Infinity", True, None])
def test_bad_amount_rejected(bad):
    with pytest.raises(ValueError):
        validate_args(SCHEMA, {"amount": bad})


@pytest.mark.parametrize("bad", [1, 45, 365, "lots", 7.5])
def test_bad_int_enum_rejected(bad):
    with pytest.raises(ValueError):
        validate_args(SCHEMA, {"amount": 1, "horizon": bad})


def test_bad_date_rejected():
    with pytest.raises(ValueError):
        validate_args(SCHEMA, {"amount": 1, "when": "30/09/2026"})


def test_int_range_bounds():
    with pytest.raises(ValueError):
        validate_args(SCHEMA, {"amount": 1, "limit": 9})


def test_enum_rejects_unknown():
    with pytest.raises(ValueError):
        validate_args(SCHEMA, {"amount": 1, "dir": "sideways"})


@pytest.mark.parametrize("key", ["user_id", "student_id", "account_id", "id", "token"])
def test_identity_keys_forbidden(key):
    with pytest.raises(ValueError):
        validate_args(SCHEMA, {"amount": 1, key: 999})


def test_unknown_keys_ignored_not_passed_through():
    out = validate_args(SCHEMA, {"amount": 1, "nonsense": "x", "drop_table": ";"})
    assert set(out) <= {"amount", "horizon"}
    assert "nonsense" not in out


def test_non_dict_args_rejected():
    with pytest.raises(ValueError):
        validate_args(SCHEMA, ["amount", 1])
