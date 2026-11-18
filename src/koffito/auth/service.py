"""Accounts and sessions: everything Supabase Auth used to do, done by us.

* Passwords: Argon2id, checked against a policy, never logged or returned.
* Sessions: a 15-minute access JWT (in memory in the app) + a 30-day opaque refresh token in an
  httpOnly cookie. Refresh tokens rotate on every use; replaying an old one revokes the session.
* Email links: single-use random tokens, stored hashed, short expiry.
* No user enumeration: register / forgot-password / resend answer the same way whether or not
  the email exists, and failed logins take the same time for unknown emails.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from ..core.auth import TokenVerifier
from ..core.config import Settings
from ..core.errors import AppError, AuthError, UnprocessableError
from ..db import Database, ServiceAuth
from .mailer import Mail, Mailer
from .opaque import new_token, token_hash
from .passwords import DUMMY_HASH, check_policy, hash_password, needs_rehash, verify_password

logger = logging.getLogger(__name__)

SYSTEM = ServiceAuth()


@dataclass(frozen=True, slots=True)
class Session:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime


class EmailNotVerified(AppError):
    status_code = 403
    code = "email_not_verified"


class AccountLocked(AppError):
    status_code = 429
    code = "account_locked"


def _invalid_link() -> AppError:
    return AppError(
        "This link has expired or was already used", code="invalid_link", status_code=400
    )


class AuthService:
    def __init__(
        self, db: Database, settings: Settings, verifier: TokenVerifier, mailer: Mailer
    ) -> None:
        self._db = db
        self._settings = settings
        self._verifier = verifier
        self._mailer = mailer

    # --- sign up & email verification ---------------------------------------------------------

    async def register(self, email: str, password: str, first_name: str) -> Mail | None:
        """Create the account (unverified) and return the email to send.

        The confirmation link carries this registration's password hash and name, and confirming
        applies them. So if someone registered the email first (unconfirmed), the mailbox
        owner's own link still gives the account *their* password — no pre-registration
        takeover. An already-confirmed account gets a reset link instead, so the response
        looks the same either way.
        """
        email = normalise_email(email)
        check_policy(password, email=email)
        password_hash, name = hash_password(password), first_name.strip()[:60]
        row = await self._db.fetchrow(
            """
            with u as (
              insert into public.users (email, password_hash) values (%s, %s)
              on conflict (email) do nothing
              returning id
            ), p as (
              insert into public.profiles (id, display_name) select id, %s from u returning id
            ), s as (
              insert into public.user_settings (user_id) select id from p returning user_id
            )
            select id from u
            """,
            [email, password_hash, name],
            auth=SYSTEM,
        )
        if row is not None:
            logger.info("registered user %s", row["id"])
            user_id = UUID(row["id"])
        else:
            existing = await self._user_by_email(email)
            if existing is None:  # deleted in between; nothing to do
                return None
            user_id = UUID(existing["id"])
            if existing["email_verified_at"] is not None:
                token = await self._email_token(
                    user_id, "reset_password", minutes=self._settings.reset_password_ttl_minutes
                )
                return self._mailer.password_reset(email, token)
        # Pending links from other registrations stay valid until one of them is used.
        token = await self._email_token(
            user_id,
            "verify_email",
            minutes=self._settings.verify_email_ttl_hours * 60,
            password_hash=password_hash,
            display_name=name,
            revoke_older=False,
        )
        return self._mailer.verification(email, token)

    async def resend_verification(self, email: str) -> Mail | None:
        """A fresh link for an unconfirmed account. It can't know which pending registration
        is the mailbox owner's, so it confirms the email *and* lets them choose the password
        (a reset link), instead of reusing a password someone else may have typed."""
        user = await self._user_by_email(normalise_email(email))
        if user is None or user["email_verified_at"] is not None:
            return None
        token = await self._email_token(
            UUID(user["id"]), "reset_password", minutes=self._settings.verify_email_ttl_hours * 60
        )
        return self._mailer.confirm_and_choose_password(user["email"], token)

    async def verify_email(self, token: str, *, user_agent: str | None) -> Session:
        """Consume a verification link and sign the user in on this device."""
        row = await self._db.fetchrow(
            """
            with t as (
              update public.email_tokens set used_at = now()
              where token_hash = %s and purpose = 'verify_email'
                and used_at is null and expires_at > now()
              returning user_id, password_hash, display_name
            ), others as (
              -- every other pending link for this account stops working
              update public.email_tokens o set used_at = now()
              from t where o.user_id = t.user_id and o.purpose = 'verify_email'
                and o.used_at is null and o.token_hash <> %s
            ), named as (
              update public.profiles p set display_name = coalesce(t.display_name, p.display_name)
              from t where p.id = t.user_id
            )
            update public.users u
            set email_verified_at = coalesce(u.email_verified_at, now()),
                password_hash = coalesce(t.password_hash, u.password_hash),
                password_changed_at = now()
            from t where u.id = t.user_id
            returning u.id
            """,
            [token_hash(token), token_hash(token)],
            auth=SYSTEM,
        )
        if row is None:
            raise _invalid_link()
        return await self._start_session(UUID(row["id"]), user_agent=user_agent)

    # --- sign in / out --------------------------------------------------------------------------

    async def login(self, email: str, password: str, *, user_agent: str | None) -> Session:
        user = await self._user_by_email(normalise_email(email))
        if user is None:
            verify_password(DUMMY_HASH, password)  # same cost as a real check
            raise AuthError("Wrong email or password", code="invalid_credentials")

        locked_until = user["locked_until"]
        if locked_until and datetime.fromisoformat(locked_until) > datetime.now(UTC):
            raise AccountLocked(
                "Too many attempts. Try again in a few minutes, or reset your password."
            )

        if not verify_password(user["password_hash"], password):
            await self._db.fetch(
                """
                update public.users
                set failed_logins = case when failed_logins + 1 >= %s then 0
                                         else failed_logins + 1 end,
                    locked_until = case when failed_logins + 1 >= %s
                                        then now() + make_interval(mins => %s) else locked_until end
                where id = %s
                """,
                [
                    self._settings.login_max_failures,
                    self._settings.login_max_failures,
                    self._settings.login_lockout_minutes,
                    user["id"],
                ],
                auth=SYSTEM,
            )
            raise AuthError("Wrong email or password", code="invalid_credentials")

        # Only after the password is right, so this does not reveal which emails exist.
        if user["email_verified_at"] is None:
            raise EmailNotVerified("Confirm your email first. Check your inbox for the link.")

        new_hash = hash_password(password) if needs_rehash(user["password_hash"]) else None
        await self._db.fetch(
            """
            update public.users
            set failed_logins = 0, locked_until = null,
                password_hash = coalesce(%s, password_hash)
            where id = %s
            """,
            [new_hash, user["id"]],
            auth=SYSTEM,
        )
        return await self._start_session(UUID(user["id"]), user_agent=user_agent)

    async def refresh(self, refresh_token: str, *, user_agent: str | None) -> Session:
        """Rotate: the presented token is spent and a new one in the same family is issued.

        Spend, issue and link happen in one statement, so two requests with the same token can
        never both succeed and a crash can't leave the user without a valid token. A token that
        was already spent means a copy exists somewhere: the whole family (that sign-in on every
        device it reached) is revoked. The web app serialises refreshes across tabs (Web
        Locks), so a legitimate client never replays a token.
        """
        token, fresh_id = new_token(), uuid4()
        expires_at = datetime.now(UTC) + timedelta(days=self._settings.refresh_token_ttl_days)
        # The new row's id is chosen up front so the old row is spent *and* linked in a single
        # update (Postgres won't update the same row twice in one statement).
        spent = await self._db.fetchrow(
            """
            with old as (
              update public.refresh_tokens set revoked_at = now(), replaced_by = %s
              where token_hash = %s and revoked_at is null and expires_at > now()
              returning user_id, family_id
            ), fresh as (
              insert into public.refresh_tokens
                (id, user_id, family_id, token_hash, expires_at, user_agent)
              select %s, user_id, family_id, %s, %s, %s from old
            )
            select user_id from old
            """,
            [
                fresh_id,
                token_hash(refresh_token),
                fresh_id,
                token_hash(token),
                expires_at,
                (user_agent or "")[:200],
            ],
            auth=SYSTEM,
        )
        if spent is None:
            known = await self._db.fetchrow(
                "select user_id, family_id, replaced_by from public.refresh_tokens"
                " where token_hash = %s",
                [token_hash(refresh_token)],
                auth=SYSTEM,
            )
            if known and known["replaced_by"] is not None:
                logger.warning("refresh token reuse for user %s; revoking", known["user_id"])
                await self._revoke_family(known["family_id"])
            raise AuthError("Session expired", code="invalid_refresh")

        access, ttl = self._verifier.issue(UUID(spent["user_id"]))
        return Session(access, ttl, token, expires_at)

    async def logout(self, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        row = await self._db.fetchrow(
            "select family_id from public.refresh_tokens where token_hash = %s",
            [token_hash(refresh_token)],
            auth=SYSTEM,
        )
        if row:
            await self._revoke_family(row["family_id"])

    # --- passwords ------------------------------------------------------------------------------

    async def forgot_password(self, email: str) -> Mail | None:
        user = await self._user_by_email(normalise_email(email))
        if user is None:
            return None
        token = await self._email_token(
            UUID(user["id"]), "reset_password", minutes=self._settings.reset_password_ttl_minutes
        )
        return self._mailer.password_reset(user["email"], token)

    async def reset_password(self, token: str, new_password: str) -> None:
        holder = await self._db.fetchrow(
            """
            select u.email from public.email_tokens t join public.users u on u.id = t.user_id
            where t.token_hash = %s and t.purpose = 'reset_password'
              and t.used_at is null and t.expires_at > now()
            """,
            [token_hash(token)],
            auth=SYSTEM,
        )
        if holder is None:
            raise _invalid_link()
        check_policy(new_password, email=holder["email"])
        row = await self._db.fetchrow(
            """
            with t as (
              update public.email_tokens set used_at = now()
              where token_hash = %s and purpose = 'reset_password'
                and used_at is null and expires_at > now()
              returning user_id
            ), u as (
              update public.users u
              set password_hash = %s, password_changed_at = now(), failed_logins = 0,
                  locked_until = null,
                  -- the reset link proves they own the mailbox
                  email_verified_at = coalesce(u.email_verified_at, now())
              from t where u.id = t.user_id
              returning u.id
            ), signed_out as (
              -- every device is signed out
              update public.refresh_tokens r set revoked_at = now()
              from u where r.user_id = u.id and r.revoked_at is null
            )
            select id from u
            """,
            [token_hash(token), hash_password(new_password)],
            auth=SYSTEM,
        )
        if row is None:  # used or expired in the meantime (e.g. a double submit)
            raise _invalid_link()

    async def change_password(
        self, user_id: UUID, current: str, new: str, *, user_agent: str | None
    ) -> Session:
        user = await self._db.fetchrow(
            "select email, password_hash from public.users where id = %s", [user_id], auth=SYSTEM
        )
        if user is None or not verify_password(user["password_hash"], current):
            raise AuthError("Your current password is not right", code="invalid_credentials")
        if current == new:
            raise UnprocessableError("Pick a password you haven't used here", code="weak_password")
        check_policy(new, email=user["email"])
        await self._db.fetch(
            """
            with u as (
              update public.users set password_hash = %s, password_changed_at = now()
              where id = %s returning id
            )
            update public.refresh_tokens r set revoked_at = now()
            from u where r.user_id = u.id and r.revoked_at is null
            """,
            [hash_password(new), user_id],
            auth=SYSTEM,
        )
        # Every other device is signed out; this one gets a fresh session.
        return await self._start_session(user_id, user_agent=user_agent)

    # --- internals ------------------------------------------------------------------------------

    async def _user_by_email(self, email: str) -> dict | None:
        return await self._db.fetchrow(
            """
            select id, email::text as email, password_hash, email_verified_at, locked_until
            from public.users where email = %s
            """,
            [email],
            auth=SYSTEM,
        )

    async def _start_session(self, user_id: UUID, *, user_agent: str | None) -> Session:
        """A new sign-in: a new refresh-token family and a first access token."""
        token = new_token()
        expires_at = datetime.now(UTC) + timedelta(days=self._settings.refresh_token_ttl_days)
        await self._db.fetch(
            """
            insert into public.refresh_tokens
              (user_id, family_id, token_hash, expires_at, user_agent)
            values (%s, %s, %s, %s, %s)
            """,
            [user_id, uuid4(), token_hash(token), expires_at, (user_agent or "")[:200]],
            auth=SYSTEM,
        )
        access, ttl = self._verifier.issue(user_id)
        return Session(access, ttl, token, expires_at)

    async def _revoke_family(self, family_id: str | UUID) -> None:
        await self._db.fetch(
            "update public.refresh_tokens set revoked_at = now()"
            " where family_id = %s and revoked_at is null",
            [family_id],
            auth=SYSTEM,
        )

    async def _email_token(
        self,
        user_id: UUID,
        purpose: str,
        *,
        minutes: int,
        password_hash: str | None = None,
        display_name: str | None = None,
        revoke_older: bool = True,
    ) -> str:
        """A new single-use link token (stored hashed). By default older unused links for the
        same purpose stop working."""
        token = new_token()
        await self._db.fetch(
            """
            with old as (
              update public.email_tokens set used_at = now()
              where %s and user_id = %s and purpose = %s and used_at is null
            )
            insert into public.email_tokens
              (user_id, purpose, token_hash, expires_at, password_hash, display_name)
            values (%s, %s, %s, now() + make_interval(mins => %s), %s, %s)
            """,
            [
                revoke_older,
                user_id,
                purpose,
                user_id,
                purpose,
                token_hash(token),
                minutes,
                password_hash,
                display_name,
            ],
            auth=SYSTEM,
        )
        return token


def normalise_email(email: str) -> str:
    return email.strip().lower()
