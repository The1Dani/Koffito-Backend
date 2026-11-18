"""`/auth/*`: sign up, email verification, sign in, refresh, sign out, password reset/change.

The access token is returned in the JSON body (the app keeps it in memory only). The refresh
token never touches JavaScript: it lives in an httpOnly, SameSite=Strict cookie scoped to the
auth routes. The cookie-based routes also require `X-Requested-With: koffito`, a header a
cross-site form or image cannot send, as a second CSRF guard.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from ...auth.mailer import Mail, Mailer
from ...auth.service import AuthService, Session, normalise_email
from ...core.errors import AuthError, ForbiddenError, RateLimitedError
from ...core.ratelimit import RateLimit, rate_limited
from ..deps import AuthenticatedUser, get_auth_service, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE = "koffito_refresh"
CSRF_HEADER = "x-requested-with"

AUTH = rate_limited(
    lambda s: RateLimit(s.rate_limit_auth_limit, s.rate_limit_auth_window_seconds, "auth")
)


# --- bodies -------------------------------------------------------------------------------------


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    first_name: str = Field(min_length=1, max_length=60)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class EmailIn(BaseModel):
    email: EmailStr


class TokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class ResetIn(TokenIn):
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class SessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AcceptedOut(BaseModel):
    ok: bool = True


# --- helpers ------------------------------------------------------------------------------------


def _limit_email(request: Request, email: str) -> None:
    """Second limit keyed on the email address, so one account can't be hammered from many IPs."""
    settings = request.app.state.settings
    if not settings.rate_limit_enabled:
        return
    rl = RateLimit(
        settings.rate_limit_email_limit, settings.rate_limit_email_window_seconds, "auth-email"
    )
    decision = request.app.state.limiter.hit(f"auth-email:{normalise_email(email)}", rl)
    if not decision.allowed:
        raise RateLimitedError(retry_after=decision.retry_after)


def _require_csrf_header(request: Request) -> None:
    if request.headers.get(CSRF_HEADER, "").lower() != "koffito":
        raise ForbiddenError("Missing request header", code="csrf_header_missing")


def _set_cookie(request: Request, response: Response, session: Session) -> SessionOut:
    settings = request.app.state.settings
    response.set_cookie(
        COOKIE,
        session.refresh_token,
        max_age=settings.refresh_token_ttl_days * 86400,
        expires=session.refresh_expires_at,
        path=settings.auth_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return SessionOut(access_token=session.access_token, expires_in=session.expires_in)


def _clear_cookie(request: Request, response: Response) -> None:
    settings = request.app.state.settings
    response.delete_cookie(
        COOKIE,
        path=settings.auth_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _send_later(tasks: BackgroundTasks, mailer: Mailer, mail: Mail | None) -> None:
    """Send after the response, so timing does not reveal whether an account exists."""
    if mail is None:
        return

    async def send() -> None:
        try:
            await mailer.send(mail)
        except Exception:
            logger.exception("could not send %r", mail.subject)

    tasks.add_task(send)


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


# --- routes -------------------------------------------------------------------------------------


@router.post(
    "/register",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedOut,
    dependencies=[Depends(AUTH)],
)
async def register(
    body: RegisterIn,
    request: Request,
    tasks: BackgroundTasks,
    service: AuthService = Depends(get_auth_service),
):
    """Create an account. The response is the same whether or not the email was free; either
    way an email goes out (a confirmation link, or a reset link for an existing account)."""
    _limit_email(request, body.email)
    mail = await service.register(body.email, body.password, body.first_name)
    _send_later(tasks, request.app.state.mailer, mail)
    return AcceptedOut()


@router.post(
    "/resend-verification",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedOut,
    dependencies=[Depends(AUTH)],
)
async def resend_verification(
    body: EmailIn,
    request: Request,
    tasks: BackgroundTasks,
    service: AuthService = Depends(get_auth_service),
):
    _limit_email(request, body.email)
    _send_later(tasks, request.app.state.mailer, await service.resend_verification(body.email))
    return AcceptedOut()


@router.post("/verify-email", response_model=SessionOut, dependencies=[Depends(AUTH)])
async def verify_email(
    body: TokenIn,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    """Consume the link from the confirmation email; signs the user in."""
    session = await service.verify_email(body.token, user_agent=_user_agent(request))
    return _set_cookie(request, response, session)


@router.post("/login", response_model=SessionOut, dependencies=[Depends(AUTH)])
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    # Per-account protection for logins is the lockout in AuthService.login.
    session = await service.login(body.email, body.password, user_agent=_user_agent(request))
    return _set_cookie(request, response, session)


@router.post("/refresh", response_model=SessionOut)
async def refresh(
    request: Request, response: Response, service: AuthService = Depends(get_auth_service)
):
    """New access token from the refresh cookie (which is rotated)."""
    _require_csrf_header(request)
    token = request.cookies.get(COOKIE)
    if not token:
        raise AuthError("Not signed in", code="invalid_refresh")
    try:
        session = await service.refresh(token, user_agent=_user_agent(request))
    except AuthError:
        _clear_cookie(request, response)
        raise
    return _set_cookie(request, response, session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, service: AuthService = Depends(get_auth_service)
):
    _require_csrf_header(request)
    await service.logout(request.cookies.get(COOKIE))
    _clear_cookie(request, response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedOut,
    dependencies=[Depends(AUTH)],
)
async def forgot_password(
    body: EmailIn,
    request: Request,
    tasks: BackgroundTasks,
    service: AuthService = Depends(get_auth_service),
):
    """Always 202, so it can't be used to find out who has an account."""
    _limit_email(request, body.email)
    _send_later(tasks, request.app.state.mailer, await service.forgot_password(body.email))
    return AcceptedOut()


@router.post(
    "/reset-password", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(AUTH)]
)
async def reset_password(body: ResetIn, service: AuthService = Depends(get_auth_service)):
    """Set a new password from a reset link. Signs out every device."""
    await service.reset_password(body.token, body.password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/change-password", response_model=SessionOut, dependencies=[Depends(AUTH)])
async def change_password(
    body: ChangePasswordIn,
    request: Request,
    response: Response,
    user: AuthenticatedUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    """Signed in: change the password. Other devices are signed out; this one stays in."""
    session = await service.change_password(
        user.id, body.current_password, body.new_password, user_agent=_user_agent(request)
    )
    return _set_cookie(request, response, session)
