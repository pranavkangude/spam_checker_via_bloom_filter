"""Typed service errors; app.py maps them to the standard error JSON."""
from __future__ import annotations

from typing import Optional


class ServiceError(Exception):
    status = 500
    code = "INTERNAL_ERROR"

    def __init__(self, message: str, field: Optional[str] = None, code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.field = field
        if code:
            self.code = code


class ValidationError(ServiceError):
    status = 400
    code = "VALIDATION_ERROR"


class NotFoundError(ServiceError):
    status = 404
    code = "NOT_FOUND"


class ConflictError(ServiceError):
    status = 409
    code = "CONFLICT"


class PayloadTooLargeError(ServiceError):
    status = 413
    code = "PAYLOAD_TOO_LARGE"
