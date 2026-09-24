import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..core.errors import AppError, AuthError, error_response

logger = logging.getLogger(__name__)

# The Data API gate (`private.check_request`) rejects requests without our backend key.
GATE_MESSAGE_PREFIX = "Koffito data is only available through the Koffito API"


class SupabaseError(Exception):
    """A non-2xx answer from PostgREST, with the PostgREST/Postgres error fields."""

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


class SupabaseUnavailable(SupabaseError):
    """Supabase could not be reached (connection error or timeout)."""

    def __init__(self, message: str) -> None:
        super().__init__(503, None, message)


# `raise exception '<name>'` inside the SQL RPCs → PostgREST 400 with code P0001 and the name
# as the message. These names are stable API contracts shared with the app.
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
    "is_admin_is_read_only": (403, "forbidden"),
}

# Postgres SQLSTATE / PostgREST codes → HTTP status + stable code.
_CODES: dict[str, tuple[int, str]] = {
    "PGRST116": (404, "not_found"),  # single-object response but 0 (or >1) rows
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


def map_supabase_error(err: SupabaseError) -> AppError:
    """Translate a PostgREST failure into the API's own error (status + stable code)."""
    if isinstance(err, SupabaseUnavailable):
        return AppError("Supabase is unavailable", code="upstream_unavailable", status_code=503)
    code = err.code or ""
    if code == "P0001":
        if err.message in RPC_ERRORS:
            status, api_code = RPC_ERRORS[err.message]
            if status == 401:
                return AuthError("Authentication required", code=api_code)
            return AppError(err.message.replace("_", " "), code=api_code, status_code=status)
        return AppError(err.message, code="rpc_error", status_code=400)
    if code == "42501":
        if err.message.startswith(GATE_MESSAGE_PREFIX):
            logger.error("data api gate rejected the backend key; check KOFFITO_BACKEND_KEY")
            return AppError(
                "Backend is misconfigured", code="backend_misconfigured", status_code=500
            )
        return AppError("Not allowed", code="forbidden", status_code=403)
    if code == "PGRST301":
        # PostgREST rejected the JWT itself (usually expired between our check and theirs).
        return AuthError("Token expired", code="token_expired")
    if code in _CODES:
        status, api_code = _CODES[code]
        details = err.details if status == 422 else None
        return AppError(err.message, code=api_code, status_code=status, details=details)
    if err.status >= 500:
        return AppError("Supabase returned an error", code="upstream_error", status_code=502)
    return AppError(err.message, code="upstream_error", status_code=502)


async def _supabase_error(request: Request, exc: SupabaseError) -> JSONResponse:
    mapped = map_supabase_error(exc)
    if mapped.status_code >= 500:
        logger.error(
            "supabase error on %s %s: status=%s code=%s message=%s",
            request.method,
            request.url.path,
            exc.status,
            exc.code,
            exc.message,
        )
    return error_response(
        mapped.status_code, mapped.code, mapped.message, mapped.details, mapped.headers
    )


def register_supabase_error_handler(app: FastAPI) -> None:
    app.add_exception_handler(SupabaseError, _supabase_error)  # type: ignore[arg-type]
