"""Fee Management System - Azure Functions (Python v2 programming model).

Routes only; logic lives in fees/. Every route needs a function key
(API Management and the Logic App hold the keys, clients never do), except
/api/health. Admin routes additionally require an Entra ID token with the
FeeAdmin or FeeViewer app role.

    Student  GET   /api/students/{studentId}/fee-status
    Admin    GET   /api/manage/students?status=&course=&page=&pageSize=
    Admin    GET   /api/manage/students/{studentId}
    Admin    POST  /api/manage/students/{studentId}/payments      (FeeAdmin)
    Admin    PATCH /api/manage/students/{studentId}/fees          (FeeAdmin)
    Logic App GET  /api/reminders/overdue?limit=
             GET   /api/health
"""

import azure.functions as func

from fees import api
from fees.services import services

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="students/{studentId:int}/fee-status", methods=["GET"])
def student_fee_status(req: func.HttpRequest) -> func.HttpResponse:
    return api.student_fee_status(req, services)


@app.route(route="manage/students", methods=["GET"])
def admin_list_students(req: func.HttpRequest) -> func.HttpResponse:
    return api.admin_list_students(req, services)


@app.route(route="manage/students/{studentId:int}", methods=["GET"])
def admin_get_student(req: func.HttpRequest) -> func.HttpResponse:
    return api.admin_get_student(req, services)


@app.route(route="manage/students/{studentId:int}/payments", methods=["POST"])
def admin_record_payment(req: func.HttpRequest) -> func.HttpResponse:
    return api.admin_record_payment(req, services)


@app.route(route="manage/students/{studentId:int}/fees", methods=["PATCH"])
def admin_update_fees(req: func.HttpRequest) -> func.HttpResponse:
    return api.admin_update_fees(req, services)


@app.route(route="reminders/overdue", methods=["GET"])
def overdue_for_reminders(req: func.HttpRequest) -> func.HttpResponse:
    return api.overdue_for_reminders(req, services)


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return api.health(req, services)
