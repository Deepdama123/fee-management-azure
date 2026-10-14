"""HTTP handler tests (local-dev auth mode; Entra token checks are in test_auth.py)."""

import json

import azure.functions as func
import pytest

from conftest import ADMIN, FORMER, VIEWER, FakeServices
from fees import api


def request(method="GET", url="/api/x", body=None, params=None, route=None, user=None, roles=None):
    headers = {}
    if user:
        headers["X-Dev-User"] = user
    if roles:
        headers["X-Dev-Roles"] = roles
    raw = json.dumps(body).encode() if isinstance(body, dict) else (body or b"")
    return func.HttpRequest(method=method, url=url, body=raw, params=params or {},
                            route_params=route or {}, headers=headers)


def payload(response):
    return json.loads(response.get_body())


def as_admin(**kw):
    return request(user=ADMIN, roles="FeeAdmin", **kw)


def as_viewer(**kw):
    return request(user=VIEWER, roles="FeeViewer", **kw)


# ---------------------------------------------------------------- student API

@pytest.mark.parametrize("student_id, status, balance, days", [
    ("1001", "Paid", 0, 0),
    ("1007", "Partially Paid", 110000, 0),
    ("1015", "Overdue", 180000, 7),
])
def test_student_fee_status(services, student_id, status, balance, days):
    response = api.student_fee_status(request(route={"studentId": student_id}), services)
    body = payload(response)
    assert response.status_code == 200
    assert body["status"] == status
    assert body["balance"] == balance
    assert body["daysOverdue"] == days
    assert "email" not in body


def test_student_not_found_and_bad_id(services):
    assert api.student_fee_status(request(route={"studentId": "9999"}), services).status_code == 404
    assert api.student_fee_status(request(route={"studentId": "abc"}), services).status_code == 400


# ------------------------------------------------------------ authentication

def test_admin_endpoints_need_identity(services):
    response = api.admin_list_students(request(), services)
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_identity_without_a_fee_role_is_forbidden(services):
    response = api.admin_list_students(request(user=ADMIN, roles="SomethingElse"), services)
    assert response.status_code == 403
    assert payload(response)["error"]["details"]["requiredAnyOf"] == ["FeeAdmin", "FeeViewer"]


# ------------------------------------------------------------ admin queries

def test_viewer_and_admin_can_query(services):
    for req in (as_viewer(), as_admin()):
        body = payload(api.admin_list_students(req, services))
        assert body["totalCount"] == 20 and len(body["items"]) == 20


def test_query_filters_and_paging(services):
    overdue = payload(api.admin_list_students(as_viewer(params={"status": "overdue"}), services))
    assert overdue["totalCount"] == 7
    assert {s["status"] for s in overdue["items"]} == {"Overdue"}

    mba = payload(api.admin_list_students(as_viewer(params={"course": "MBA"}), services))
    assert mba["totalCount"] == 4

    page2 = payload(api.admin_list_students(as_viewer(params={"page": "2", "pageSize": "8"}), services))
    assert page2["totalPages"] == 3 and len(page2["items"]) == 8
    assert page2["items"][0]["studentId"] == 1009


@pytest.mark.parametrize("params", [{"status": "late"}, {"pageSize": "1000"}, {"page": "0"}])
def test_query_rejects_bad_parameters(services, params):
    assert api.admin_list_students(as_viewer(params=params), services).status_code == 400


# ---------------------------------------------------------------- payments

def test_admin_records_payment_status_changes_and_is_audited(services):
    response = api.admin_record_payment(as_admin(method="POST", route={"studentId": "1014"},
                                                 body={"amount": 30000}), services)
    body = payload(response)
    assert response.status_code == 200
    assert body["status"] == "Paid" and body["balance"] == 0

    detail = payload(api.admin_get_student(as_viewer(route={"studentId": "1014"}), services))
    change = detail["recentChanges"][0]
    assert change["action"] == "PAYMENT_RECORDED"
    assert change["oldPaidAmount"] == 60000 and change["newPaidAmount"] == 90000
    assert change["changedBy"] == ADMIN


def test_viewer_cannot_record_payments(services):
    response = api.admin_record_payment(as_viewer(method="POST", route={"studentId": "1014"},
                                                  body={"amount": 100}), services)
    assert response.status_code == 403


def test_overpayment_is_rejected_atomically(services, repo):
    response = api.admin_record_payment(as_admin(method="POST", route={"studentId": "1014"},
                                                 body={"amount": 30000.01}), services)
    assert response.status_code == 409
    assert payload(response)["error"]["details"]["outstandingBalance"] == "30000.00"
    assert float(repo.get_student(1014)["paidAmount"]) == 60000          # unchanged


@pytest.mark.parametrize("body", [{}, {"amount": 0}, {"amount": -5}, {"amount": "100"},
                                  {"amount": 1.234}, {"amount": 10, "note": "x"}])
def test_payment_validation(services, body):
    response = api.admin_record_payment(as_admin(method="POST", route={"studentId": "1014"}, body=body), services)
    assert response.status_code == 400


def test_payment_for_unknown_student(services):
    response = api.admin_record_payment(as_admin(method="POST", route={"studentId": "9999"},
                                                 body={"amount": 10}), services)
    assert response.status_code == 404


def test_token_role_alone_is_not_enough_for_writes(services):
    """A FeeAdmin token whose user is missing or inactive in dbo.Administrators is refused."""
    for user in ("stranger@contoso.onmicrosoft.com", FORMER):
        req = request(method="POST", route={"studentId": "1014"}, body={"amount": 10}, user=user, roles="FeeAdmin")
        assert api.admin_record_payment(req, services).status_code == 403


# ------------------------------------------------------------ fee updates

def test_admin_updates_due_date_and_status_follows(services):
    response = api.admin_update_fees(as_admin(method="PATCH", route={"studentId": "1015"},
                                              body={"dueDate": "2026-12-31"}), services)
    body = payload(response)
    assert response.status_code == 200
    assert body["status"] == "Partially Paid" and body["dueDate"] == "2026-12-31"
    audit = payload(api.admin_get_student(as_admin(route={"studentId": "1015"}), services))["recentChanges"]
    assert audit[0]["action"] == "FEE_UPDATED" and audit[0]["newDueDate"] == "2026-12-31"


def test_update_cannot_make_paid_exceed_total(services):
    response = api.admin_update_fees(as_admin(method="PATCH", route={"studentId": "1007"},
                                              body={"totalFee": 100000}), services)  # paid is 110000
    assert response.status_code == 409


@pytest.mark.parametrize("body", [{}, {"totalFee": None}, {"dueDate": "31/12/2026"},
                                  {"paidAmount": 10, "totalFee": 5}, {"name": "x"}])
def test_update_validation(services, body):
    response = api.admin_update_fees(as_admin(method="PATCH", route={"studentId": "1007"}, body=body), services)
    assert response.status_code == 400


# --------------------------------------------------------------- reminders

def test_reminder_feed_lists_only_overdue_oldest_first(services):
    body = payload(api.overdue_for_reminders(request(), services))
    assert body["count"] == 7
    assert [s["daysOverdue"] for s in body["items"]] == sorted((s["daysOverdue"] for s in body["items"]), reverse=True)
    first = body["items"][0]
    assert set(first) == {"studentId", "name", "course", "email", "totalFee", "paidAmount",
                          "balance", "dueDate", "daysOverdue"}
    assert first["name"] == "Yash Malhotra" and first["daysOverdue"] == 45


def test_reminder_feed_respects_limit(services):
    assert payload(api.overdue_for_reminders(request(params={"limit": "3"}), services))["count"] == 3


# ----------------------------------------------------------- error handling

def test_unexpected_errors_do_not_leak(repo):
    class Broken(FakeServices):
        def repository(self):
            raise RuntimeError("Pwd=secret")

    response = api.student_fee_status(request(route={"studentId": "1001"}), Broken(repo))
    assert response.status_code == 500
    assert "secret" not in response.get_body().decode()


def test_health(services):
    assert payload(api.health(request(), services)) == {"status": "healthy"}
