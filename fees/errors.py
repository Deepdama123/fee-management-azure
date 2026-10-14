"""Application errors, each mapped to exactly one HTTP status code."""


class ApiError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(ApiError):
    status_code = 400
    code = "validation_error"


class UnauthorizedError(ApiError):
    """No valid identity: missing, expired or forged token."""

    status_code = 401
    code = "unauthorized"


class ForbiddenError(ApiError):
    """Valid identity, but not allowed to do this (RBAC)."""

    status_code = 403
    code = "forbidden"


class NotFoundError(ApiError):
    status_code = 404
    code = "not_found"


class ConflictError(ApiError):
    status_code = 409
    code = "conflict"


class ServiceUnavailableError(ApiError):
    status_code = 503
    code = "service_unavailable"


class ConfigurationError(ApiError):
    status_code = 500
    code = "internal_error"
