"""HTTP handlers. Each one: authenticate/authorise -> validate -> repository
-> fee calculation -> JSON. @api_handler maps every error to one JSON shape:

    400 validation_error    401 unauthorized    403 forbidden
    404 not_found           409 conflict        429 (API Management)
    500 internal_error      503 service_unavailable
"""

import functools
import json
import logging
import os
import uuid
from datetime import date, datetime
from decimal import Decimal

import azure.functions as func

from . import auth
from .errors import ApiError, ForbiddenError, NotFoundError
from .fee_logic import fee_summary
from .validation import (
    parse_json_body,
    parse_positive_int,
    parse_status,
    parse_text_filter,
    validate_fee_update,
    validate_payment,
)

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 200
MAX_REMINDER_BATCH = 500


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Cannot serialise {type(value).__name__}")


def json_response(payload, status_code=200, headers=None) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(payload, default=_json_default), status_code=status_code,
                             mimetype="application/json", headers=headers)


def _error_response(error: ApiError, request_id: str) -> func.HttpResponse:
    body = {"error": {"code": error.code, "message": error.message, "requestId": request_id}}
    if error.details:
        body["error"]["details"] = error.details
    headers = {}
    if error.status_code == 503:
        headers["Retry-After"] = "30"
    if error.status_code == 401:
        headers["WWW-Authenticate"] = 'Bearer error="invalid_token"'
    return json_response(body, error.status_code, headers or None)


def _debug_errors_enabled() -> bool:
    return os.environ.get("DEBUG_ERRORS", "").strip().lower() == "true"


def api_handler(handler):
    @functools.wraps(handler)
    def wrapper(req: func.HttpRequest, *args, **kwargs) -> func.HttpResponse:
        request_id = req.headers.get("x-request-id") or str(uuid.uuid4())
        try:
            return handler(req, *args, **kwargs)
        except ApiError as error:
            if error.status_code >= 500:
                logger.error("[%s] %s %s failed: %s", request_id, req.method, req.url, error.message)
            elif error.status_code in (401, 403):
                logger.warning("[%s] %s %s denied: %s", request_id, req.method, req.url, error.message)
            original = error
            if error.status_code == 500:
                error = ApiError("An unexpected error occurred.")
            if error.status_code >= 500 and _debug_errors_enabled():
                cause = original.__cause__ or original
                error.details = {**error.details, "debugCause": f"{type(cause).__name__}: {cause}"[:1500]}
            return _error_response(error, request_id)
        except Exception as exc:
            logger.exception("[%s] Unhandled error on %s %s", request_id, req.method, req.url)
            error = ApiError("An unexpected error occurred.")
            if _debug_errors_enabled():
                error.details = {"debugCause": f"{type(exc).__name__}: {exc}"[:1500]}
            return _error_response(error, request_id)

    return wrapper


def _student_id(req) -> int:
    return parse_positive_int(req.route_params.get("studentId"), "studentId")


def _admin_principal(req, services, *allowed_roles) -> auth.Principal:
    principal = auth.authenticate(req.headers, services.settings)
    auth.require_any_role(principal, *allowed_roles)
    return principal


def _registered_admin(principal, services) -> dict:
    """Writes are attributed to a real, active row in dbo.Administrators."""
    admin = services.repository().get_admin(principal.user)
    if admin is None or not admin.get("isActive"):
        raise ForbiddenError("Your account is not an active administrator in the fee system.",
                             {"user": principal.user})
    if admin["role"] != auth.ROLE_ADMIN:
        raise ForbiddenError("Your administrator record is read-only.", {"role": admin["role"]})
    return admin


def _public_student(row: dict, as_of: date) -> dict:
    summary = fee_summary(row, as_of)
    summary.pop("updatedAt", None)
    return summary


# ------------------------------------------------------------- student API

@api_handler
def student_fee_status(req: func.HttpRequest, services) -> func.HttpResponse:
    student_id = _student_id(req)
    row = services.repository().get_student(student_id)
    if row is None:
        raise NotFoundError(f"Student {student_id} was not found.")
    summary = _public_student(row, services.settings.today())
    summary.pop("email", None)   # students don't need their contact data echoed back
    return json_response(summary)


# --------------------------------------------------------------- admin API

@api_handler
def admin_list_students(req: func.HttpRequest, services) -> func.HttpResponse:
    _admin_principal(req, services, auth.ROLE_ADMIN, auth.ROLE_VIEWER)
    status = parse_status(req.params.get("status"))
    course = parse_text_filter(req.params.get("course"), "course")
    page = parse_positive_int(req.params.get("page"), "page", default=1)
    page_size = parse_positive_int(req.params.get("pageSize"), "pageSize", default=50, maximum=MAX_PAGE_SIZE)
    as_of = services.settings.today()
    rows, total = services.repository().list_students(as_of, status, course, page, page_size)
    return json_response({
        "page": page, "pageSize": page_size, "totalCount": total,
        "totalPages": (total + page_size - 1) // page_size,
        "items": [_public_student(r, as_of) for r in rows],
    })


@api_handler
def admin_get_student(req: func.HttpRequest, services) -> func.HttpResponse:
    _admin_principal(req, services, auth.ROLE_ADMIN, auth.ROLE_VIEWER)
    student_id = _student_id(req)
    repo = services.repository()
    row = repo.get_student(student_id)
    if row is None:
        raise NotFoundError(f"Student {student_id} was not found.")
    return json_response({**_public_student(row, services.settings.today()),
                          "recentChanges": repo.list_audit(student_id)})


@api_handler
def admin_record_payment(req: func.HttpRequest, services) -> func.HttpResponse:
    principal = _admin_principal(req, services, auth.ROLE_ADMIN)
    admin = _registered_admin(principal, services)
    student_id = _student_id(req)
    amount = validate_payment(parse_json_body(req.get_body()))
    updated = services.repository().record_payment(student_id, amount, admin["email"])
    logger.info("Payment recorded: student=%s amount=%s by=%s", student_id, amount, admin["email"])
    return json_response(_public_student(updated, services.settings.today()))


@api_handler
def admin_update_fees(req: func.HttpRequest, services) -> func.HttpResponse:
    principal = _admin_principal(req, services, auth.ROLE_ADMIN)
    admin = _registered_admin(principal, services)
    student_id = _student_id(req)
    changes = validate_fee_update(parse_json_body(req.get_body()))
    updated = services.repository().update_fees(student_id, changes, admin["email"])
    logger.info("Fee record updated: student=%s fields=%s by=%s", student_id, sorted(changes), admin["email"])
    return json_response(_public_student(updated, services.settings.today()))


# ------------------------------------------------------ reminders (Logic App)

@api_handler
def overdue_for_reminders(req: func.HttpRequest, services) -> func.HttpResponse:
    limit = parse_positive_int(req.params.get("limit"), "limit", default=100, maximum=MAX_REMINDER_BATCH)
    as_of = services.settings.today()
    rows = services.repository().list_overdue(as_of, limit)
    items = [{k: v for k, v in _public_student(r, as_of).items()
              if k in ("studentId", "name", "course", "email", "totalFee", "paidAmount",
                       "balance", "dueDate", "daysOverdue")} for r in rows]
    logger.info("Reminder feed generated: %s overdue students as of %s", len(items), as_of)
    return json_response({"asOf": as_of.isoformat(), "count": len(items), "items": items})


@api_handler
def health(req: func.HttpRequest, services) -> func.HttpResponse:
    services.repository().ping()
    return json_response({"status": "healthy"})
