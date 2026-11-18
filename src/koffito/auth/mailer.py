"""Transactional email (verification and password-reset links) over SMTP."""

import html
import logging
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage

import aiosmtplib

from ..core.config import Settings

logger = logging.getLogger(__name__)

# Koffito palette (src/theme/tokens.ts in the app).
_BG, _SURFACE, _PRIMARY, _ON_PRIMARY, _TEXT, _MUTED = (
    "#FBF6EF",
    "#FFFDF9",
    "#9A5B34",
    "#FFFDF9",
    "#3B2A20",
    "#7A6A5F",
)


@dataclass(frozen=True, slots=True)
class Mail:
    to: str
    subject: str
    heading: str
    body: str
    button: str
    link: str


class Mailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, mail: Mail) -> None:
        message = EmailMessage()
        message["From"] = self._settings.mail_from
        message["To"] = mail.to
        message["Subject"] = mail.subject
        message.set_content(f"{mail.heading}\n\n{mail.body}\n\n{mail.button}: {mail.link}\n")
        message.add_alternative(_html(mail), subtype="html")
        s = self._settings
        await aiosmtplib.send(
            message,
            hostname=s.smtp_host,
            port=s.smtp_port,
            username=s.smtp_username,
            password=s.smtp_password.get_secret_value() if s.smtp_password else None,
            start_tls=s.smtp_starttls,
            use_tls=s.smtp_use_tls,
            timeout=10,
        )
        logger.info("sent %r email", mail.subject)

    def verification(self, to: str, token: str) -> Mail:
        return Mail(
            to=to,
            subject="Confirm your email for Koffito",
            heading="One sip away ☕",
            body="Confirm your email to start meeting people over coffee. "
            f"The link works for {self._settings.verify_email_ttl_hours} hours.",
            button="Confirm my email",
            link=f"{self._settings.app_base_url}/verify-email?token={token}",
        )

    def confirm_and_choose_password(self, to: str, token: str) -> Mail:
        return Mail(
            to=to,
            subject="Confirm your email for Koffito",
            heading="One sip away ☕",
            body="Tap the button to confirm your email and choose your password. "
            f"The link works for {self._settings.verify_email_ttl_hours} hours.",
            button="Confirm and choose a password",
            link=f"{self._settings.app_base_url}/reset-password?token={token}",
        )

    def reminder(self, to: str, kind: str, at: datetime, event_id: str) -> Mail:
        time = at.strftime("%H:%M")
        when = f"tomorrow at {time}" if kind == "reminder_24h" else f"in about 3 hours, at {time}"
        return Mail(
            to=to,
            subject=f"Your coffee talk is {when}",
            heading="Coffee time soon ☕",
            body=f"Your Koffito coffee talk is {when}. Open the app to see the café and who's "
            "coming, and let them know you'll be there.",
            button="See my coffee talk",
            link=f"{self._settings.app_base_url}/event-details?id={event_id}",
        )

    def password_reset(self, to: str, token: str) -> Mail:
        return Mail(
            to=to,
            subject="Reset your Koffito password",
            heading="Forgot your password?",
            body="Tap the button to choose a new one. "
            f"The link works for {self._settings.reset_password_ttl_minutes} minutes. "
            "If you didn't ask for this, you can ignore this email.",
            button="Choose a new password",
            link=f"{self._settings.app_base_url}/reset-password?token={token}",
        )


def _html(mail: Mail) -> str:
    e = html.escape
    return f"""<!doctype html>
<html><body style="margin:0;padding:32px 16px;background:{_BG};font-family:Nunito,Segoe UI,Arial,sans-serif;color:{_TEXT}">
  <table role="presentation" width="100%" style="max-width:480px;margin:0 auto;background:{_SURFACE};border-radius:24px;padding:32px">
    <tr><td style="font-size:26px;font-weight:800;padding-bottom:12px">{e(mail.heading)}</td></tr>
    <tr><td style="font-size:16px;line-height:24px;color:{_MUTED};padding-bottom:24px">{e(mail.body)}</td></tr>
    <tr><td><a href="{e(mail.link, quote=True)}" style="display:inline-block;background:{_PRIMARY};color:{_ON_PRIMARY};text-decoration:none;font-weight:700;font-size:16px;padding:16px 28px;border-radius:999px">{e(mail.button)}</a></td></tr>
    <tr><td style="font-size:13px;color:{_MUTED};padding-top:24px;word-break:break-all">Or paste this link: {e(mail.link)}</td></tr>
  </table>
</body></html>"""
