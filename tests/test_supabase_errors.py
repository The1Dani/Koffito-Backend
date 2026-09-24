import pytest

from koffito.core.errors import AuthError
from koffito.supabase.errors import (
    GATE_MESSAGE_PREFIX,
    SupabaseError,
    SupabaseUnavailable,
    map_supabase_error,
)


@pytest.mark.parametrize(
    ("err", "status", "code"),
    [
        (SupabaseError(400, "P0001", "event_full"), 409, "event_full"),
        (SupabaseError(400, "P0001", "invalid_stage"), 422, "invalid_stage"),
        (SupabaseError(400, "P0001", "not_admin"), 403, "admin_required"),
        (SupabaseError(400, "P0001", "not_authenticated"), 401, "not_authenticated"),
        (SupabaseError(400, "P0001", "something_new"), 400, "rpc_error"),
        (
            SupabaseError(401, "42501", f"{GATE_MESSAGE_PREFIX}", None, "x"),
            500,
            "backend_misconfigured",
        ),
        (SupabaseError(403, "42501", "permission denied for table venues"), 403, "forbidden"),
        (SupabaseError(401, "PGRST301", "JWT expired"), 401, "token_expired"),
        (SupabaseError(406, "PGRST116", "0 rows"), 404, "not_found"),
        (SupabaseError(409, "23505", "duplicate key"), 409, "conflict"),
        (
            SupabaseError(409, "23503", "fk violation", "Key (event_id)=(x) is not present"),
            422,
            "invalid_reference",
        ),
        (SupabaseError(400, "22P02", "invalid input syntax for type uuid"), 422, "invalid_value"),
        (
            SupabaseError(500, "57014", "canceling statement due to statement timeout"),
            504,
            "upstream_timeout",
        ),
        (SupabaseUnavailable("ConnectError: boom"), 503, "upstream_unavailable"),
        (SupabaseError(400, "PGRST204", "Could not find the 'foo' column"), 502, "upstream_error"),
        (SupabaseError(502, None, "bad gateway"), 502, "upstream_error"),
    ],
)
def test_status_and_code(err, status, code):
    mapped = map_supabase_error(err)
    assert (mapped.status_code, mapped.code) == (status, code)


def test_auth_mappings_carry_www_authenticate():
    for err in (
        SupabaseError(401, "PGRST301", "JWT expired"),
        SupabaseError(400, "P0001", "not_authenticated"),
    ):
        mapped = map_supabase_error(err)
        assert isinstance(mapped, AuthError)
        assert mapped.headers == {"WWW-Authenticate": 'Bearer error="invalid_token"'}


def test_foreign_key_details_are_forwarded():
    mapped = map_supabase_error(
        SupabaseError(409, "23503", "fk", "Key (event_id)=(x) is not present")
    )
    assert mapped.details == "Key (event_id)=(x) is not present"


def test_check_violation_does_not_leak_the_failing_row():
    err = SupabaseError(
        400,
        "23514",
        'new row for relation "surveys" violates check constraint "surveys_survey_data_check"',
        'Failing row contains (uuid, uuid, {"q": 1}, [0.1, 0.2], 1, null, ...).',
    )
    mapped = map_supabase_error(err)
    assert mapped.status_code == 422
    assert mapped.details is None
    assert "Failing row" not in mapped.message


def test_unknown_codes_do_not_echo_the_upstream_message():
    mapped = map_supabase_error(
        SupabaseError(400, "PGRST204", "Could not find the 'foo' column of 'profiles'")
    )
    assert "foo" not in mapped.message
    assert mapped.details is None
