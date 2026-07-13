from __future__ import annotations

from email.message import EmailMessage
from html import escape
import logging
import smtplib
import time

from app.core.config import settings
from app.core.security import hash_security_identifier


logger = logging.getLogger(__name__)


class PasswordResetEmailDeliveryError(Exception):
    pass


class PasswordResetEmailService:
    def send_code(self, *, email: str, code: str, expires_minutes: int) -> None:
        provider = settings.email_provider.strip().lower()
        if provider == "console":
            if settings.env not in {"development", "test"}:
                raise PasswordResetEmailDeliveryError
            logger.info(
                "password_reset_dev_email_sent recipient_hash=%s code=%s expires_minutes=%s",
                hash_security_identifier(email)[:12],
                code,
                expires_minutes,
            )
            return

        if provider != "smtp" or not settings.smtp_host or not settings.smtp_from_email:
            raise PasswordResetEmailDeliveryError

        message = EmailMessage()
        message["Subject"] = "Your BazarSync AI password reset code"
        message["From"] = settings.smtp_from_email
        message["To"] = email
        message.set_content(
            "Use this verification code to reset your BazarSync AI password:\n\n"
            f"{code}\n\n"
            f"This code expires in {expires_minutes} minutes.\n\n"
            "If you did not request a password reset, you can safely ignore this email.\n"
            "Never share this code with anyone. Support will never ask for it."
        )
        safe_code = escape(code)
        message.add_alternative(
            "<p>Use this verification code to reset your BazarSync AI password:</p>"
            f"<p><strong>{safe_code}</strong></p>"
            f"<p>This code expires in {expires_minutes} minutes.</p>"
            "<p>If you did not request a password reset, you can safely ignore this email."
            " Support will never ask for the code.</p>",
            subtype="html",
        )

        attempts = max(1, settings.password_reset_email_retry_attempts)
        for attempt in range(1, attempts + 1):
            try:
                with smtplib.SMTP(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=settings.smtp_timeout_seconds,
                ) as client:
                    if settings.smtp_use_tls:
                        client.starttls()
                    if settings.smtp_username and settings.smtp_password:
                        client.login(settings.smtp_username, settings.smtp_password)
                    client.send_message(message)
                logger.info(
                    "password_reset_email_sent recipient_hash=%s",
                    hash_security_identifier(email)[:12],
                )
                return
            except (OSError, smtplib.SMTPException):
                logger.warning(
                    "password_reset_email_delivery_failed code=SMTP_DELIVERY_FAILED attempt=%s",
                    attempt,
                )
                if attempt < attempts:
                    time.sleep(0.05)

        raise PasswordResetEmailDeliveryError
