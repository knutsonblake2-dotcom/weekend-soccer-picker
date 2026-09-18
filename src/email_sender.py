"""Sends the weekly recommendation email via Gmail SMTP."""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from . import config

logger = logging.getLogger(__name__)


def send_email(subject: str, body_text: str, body_html: str | None = None) -> bool:
    if not config.GMAIL_ADDRESS or not config.GMAIL_APP_PASSWORD:
        logger.error(
            "GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set - cannot send email. "
            "Printing the email instead:\n\nSubject: %s\n\n%s",
            subject,
            body_text,
        )
        return False

    if body_html:
        # multipart/alternative: mail clients that render HTML show the
        # nicer version; anything that can't (or is set to prefer plain
        # text) falls back to body_text. Gmail always shows the HTML part.
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))
    else:
        msg = MIMEText(body_text, "plain")
    msg["Subject"] = subject
    msg["From"] = config.GMAIL_ADDRESS
    msg["To"] = config.EMAIL_TO

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
            server.sendmail(config.GMAIL_ADDRESS, [config.EMAIL_TO], msg.as_string())
        logger.info("Email sent to %s", config.EMAIL_TO)
        return True
    except smtplib.SMTPException as exc:
        logger.error("Failed to send email: %s", exc)
        return False
