"""Request validation. Money is Decimal end to end; all errors are collected."""

import json
import re
from datetime import date
from decimal import Decimal

from .errors import ValidationError
from .fee_logic import STATUSES

MONEY_MAX = Decimal("9999999999.99")   # DECIMAL(12,2)
INT_MAX = 2_147_483_647
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# API field -> column. Also the whitelist for the dynamic UPDATE.
UPDATABLE_FEE_FIELDS = {"totalFee": "TotalFee", "paidAmount": "PaidAmount", "dueDate": "DueDate"}


def _reject_constant(name):
    raise ValueError(f"{name} is not a valid JSON number")


def parse_json_body(raw: bytes) -> dict:
    if not raw:
        raise ValidationError("Request body is required.")
    try:
        body = json.loads(raw, parse_float=Decimal, parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("Request body must be valid JSON.") from exc
    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object.")
    return body


def _money(value, field, errors, *, allow_zero=True):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        errors[field] = "must be a number"
        return None
    amount = Decimal(value)
    if amount < 0 or (amount == 0 and not allow_zero):
        errors[field] = "must be greater than 0" if not allow_zero else "must not be negative"
    elif amount > MONEY_MAX:
        errors[field] = f"must not exceed {MONEY_MAX}"
    elif amount.as_tuple().exponent < -2:
        errors[field] = "must have at most 2 decimal places"
    else:
        return amount.quantize(Decimal("0.01"))
    return None


def _date(value, field, errors):
    if not isinstance(value, str) or not DATE_PATTERN.match(value):
        errors[field] = "must be a date in YYYY-MM-DD format"
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        errors[field] = "is not a valid calendar date"
        return None
    if parsed.year < 2000:
        errors[field] = "must be on or after 2000-01-01"
        return None
    return parsed


def validate_payment(body: dict) -> Decimal:
    errors: dict[str, str] = {}
    for field in body:
        if field != "amount":
            errors[field] = "is not a recognised field"
    if "amount" not in body:
        errors["amount"] = "is required"
        amount = None
    else:
        amount = _money(body["amount"], "amount", errors, allow_zero=False)
    if errors:
        raise ValidationError("One or more fields are invalid.", errors)
    return amount


def validate_fee_update(body: dict) -> dict:
    errors: dict[str, str] = {}
    cleaned = {}
    if not body:
        raise ValidationError("Provide at least one of: totalFee, paidAmount, dueDate.")
    for field, value in body.items():
        if field not in UPDATABLE_FEE_FIELDS:
            errors[field] = "is not a recognised field"
        elif value is None:
            errors[field] = "cannot be null"
        elif field in ("totalFee", "paidAmount"):
            cleaned[field] = _money(value, field, errors)
        else:
            cleaned[field] = _date(value, field, errors)
    if "totalFee" in cleaned and "paidAmount" in cleaned and not errors:
        if cleaned["paidAmount"] > cleaned["totalFee"]:
            errors["paidAmount"] = "cannot exceed totalFee"
    if errors:
        raise ValidationError("One or more fields are invalid.", errors)
    return cleaned


def parse_positive_int(raw, name: str, *, default=None, maximum=INT_MAX) -> int:
    if raw is None or raw == "":
        if default is not None:
            return default
        raise ValidationError(f"'{name}' is required.", {name: "is required"})
    if not re.fullmatch(r"[0-9]{1,10}", str(raw)) or not 1 <= int(raw) <= maximum:
        raise ValidationError(f"'{name}' must be an integer between 1 and {maximum}.",
                              {name: f"must be an integer between 1 and {maximum}"})
    return int(raw)


def parse_status(raw) -> str | None:
    if raw is None or raw == "":
        return None
    for status in STATUSES:
        if raw.strip().lower() == status.lower():
            return status
    raise ValidationError("Unknown status filter.", {"status": f"must be one of {list(STATUSES)}"})


def parse_text_filter(raw, name: str, max_length: int = 100) -> str | None:
    if raw is None or raw.strip() == "":
        return None
    if len(raw) > max_length:
        raise ValidationError(f"'{name}' is too long.", {name: f"must be at most {max_length} characters"})
    return raw.strip()
