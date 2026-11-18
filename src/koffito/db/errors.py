import logging
from typing import Any

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..core.errors import AppError, AuthError, error_response

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """A failed database call: Postgres SQLSTATE (or our own `not_found`) + message."""

    def __init__(
        self,
        status: int,
        code: str | None,
        message: str,
        details: Any = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(f"{status} {code or '-'}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.hint = hint

    @classmethod
    def from_psycopg(cls, exc: psycopg.Error) -> DatabaseError:
        diag = exc.diag
        return cls(
            400,
            exc.sqlstate,
            diag.message_primary or str(exc),
            diag.message_detail,
            diag.message_hint,
        )


class DatabaseUnavailable(DatabaseError):
    """The database could not be reached (connection error, pool timeout)."""

    def __init__(self, message: str) -> None:
        super().__init__(503, None, message)


# `raise exception '<name>'` inside the SQL functions → SQLSTATE P0001 with the name as the
# message. These names are stable API contracts shared with the app.
RPC_ERRORS: dict[str, tuple[int, str]] = {
    "not_authenticated": (401, "not_authenticated"),
    "survey_incomplete": (409, "survey_incomplete"),
    "event_not_open": (409, "event_not_open"),
    "time_conflict": (409, "time_conflict"),
    "event_full": (409, "event_full"),
    "nothing_to_cancel": (409, "nothing_to_cancel"),
    "event_not_confirmable": (409, "event_not_confirmable"),
    "nothing_to_confirm": (409, "nothing_to_confirm"),
    "not_revealed_yet": (409, "not_revealed_yet"),
    "not_attended": (409, "not_attended"),
    "invalid_stage": (422, "invalid_stage"),
    "unknown_language": (422, "unknown_language"),
    "invalid_rating": (422, "invalid_rating"),
    "event_in_the_past": (422, "event_in_the_past"),
    "not_admin": (403, "admin_required"),
}

# Postgres SQLSTATE / our codes → HTTP status + stable code.
_CODES: dict[str, tuple[int, str]] = {
    "not_found": (404, "not_found"),  # a single row was expected but there was none
    "23505": (409, "conflict"),  # unique_violation
    "23503": (422, "invalid_reference"),  # foreign_key_violation
    "23514": (422, "constraint_violation"),  # check_violation
    "23502": (422, "missing_field"),  # not_null_violation
    "22P02": (422, "invalid_value"),  # invalid_text_representation
    "22007": (422, "invalid_value"),  # invalid_datetime_format
    "22008": (422, "invalid_value"),  # datetime_field_overflow
    "22003": (422, "invalid_value"),  # numeric_value_out_of_range
    "57014": (504, "upstream_timeout"),  # query_canceled (statement_timeout)
}


def map_database_error(err: DatabaseError) -> AppError:
    """Translate a database failure into the API's own error (status + stable code)."""
    if isinstance(err, DatabaseUnavailable):
        return AppError("Database is unavailable", code="upstream_unavailable", status_code=503)
    code = err.code or ""
    if code == "P0001":
        if err.message in RPC_ERRORS:
            status, api_code = RPC_ERRORS[err.message]
            if status == 401:
                return AuthError("Authentication required", code=api_code)
            return AppError(err.message.replace("_", " "), code=api_code, status_code=status)
        return AppError(err.message, code="rpc_error", status_code=400)
    if code in _CODES:
        status, api_code = _CODES[code]
        # Only FK details are safe and useful ("Key (event_id)=(…) is not present"); check /
        # not-null violations carry "Failing row contains (…)" — the whole row.
        details = err.details if code == "23503" else None
        message = "Not found" if code == "not_found" else err.message
        return AppError(message, code=api_code, status_code=status, details=details)
    logger.warning("unmapped database error: code=%s message=%s", code, err.message)
    return AppError("The request could not be completed", code="database_error", status_code=500)


async def _database_error(request: Request, exc: DatabaseError) -> JSONResponse:
    mapped = map_database_error(exc)
    if mapped.status_code >= 500:
        logger.error(
            "database error on %s %s: code=%s message=%s",
            request.method,
            request.url.path,
            exc.code,
            exc.message,
        )
    return error_response(
        mapped.status_code, mapped.code, mapped.message, mapped.details, mapped.headers
    )


def register_database_error_handler(app: FastAPI) -> None:
    app.add_exception_handler(DatabaseError, _database_error)  # type: ignore[arg-type]
