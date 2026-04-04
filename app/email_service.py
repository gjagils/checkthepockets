"""Email sending via Resend.com. Falls back to a no-op if RESEND_API_KEY is not set."""

import logging
from app.config import RESEND_API_KEY, RESEND_FROM_EMAIL, APP_URL

logger = logging.getLogger(__name__)


def _send(to: str, subject: str, html: str) -> bool:
    """Send an email via Resend. Returns True on success, False on failure."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — email not sent to %s: %s", to, subject)
        return False
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": RESEND_FROM_EMAIL,
            "to": [to],
            "subject": subject,
            "html": html,
        })
        return True
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to, exc)
        return False


def send_verification_email(to: str, token: str) -> bool:
    url = f"{APP_URL}/verify-email?token={token}"
    html = f"""
    <div style="font-family:sans-serif; max-width:480px; margin:0 auto;">
        <h2>Bevestig je e-mailadres</h2>
        <p>Klik op de knop hieronder om je e-mailadres te bevestigen voor Check Your Pockets.</p>
        <p style="margin:1.5rem 0;">
            <a href="{url}" style="background:#F9A800; color:#fff; padding:0.75rem 1.5rem;
               border-radius:8px; text-decoration:none; font-weight:700;">
                E-mailadres bevestigen
            </a>
        </p>
        <p style="color:#888; font-size:0.85rem;">
            Of kopieer deze link: <a href="{url}">{url}</a><br>
            Deze link is 24 uur geldig.
        </p>
    </div>
    """
    return _send(to, "Bevestig je e-mailadres — Check Your Pockets", html)


def send_password_reset_email(to: str, token: str) -> bool:
    url = f"{APP_URL}/reset-password?token={token}"
    html = f"""
    <div style="font-family:sans-serif; max-width:480px; margin:0 auto;">
        <h2>Wachtwoord opnieuw instellen</h2>
        <p>Je hebt een wachtwoordreset aangevraagd voor je Check Your Pockets account.</p>
        <p style="margin:1.5rem 0;">
            <a href="{url}" style="background:#F9A800; color:#fff; padding:0.75rem 1.5rem;
               border-radius:8px; text-decoration:none; font-weight:700;">
                Nieuw wachtwoord instellen
            </a>
        </p>
        <p style="color:#888; font-size:0.85rem;">
            Of kopieer deze link: <a href="{url}">{url}</a><br>
            Deze link is 1 uur geldig. Als jij dit niet hebt aangevraagd, kun je deze e-mail negeren.
        </p>
    </div>
    """
    return _send(to, "Wachtwoord opnieuw instellen — Check Your Pockets", html)


def send_invite_email(to: str, token: str, invited_by: str) -> bool:
    url = f"{APP_URL}/register?invite={token}"
    html = f"""
    <div style="font-family:sans-serif; max-width:480px; margin:0 auto;">
        <h2>Je bent uitgenodigd voor Check Your Pockets</h2>
        <p>{invited_by} heeft je uitgenodigd om een account aan te maken.</p>
        <p style="margin:1.5rem 0;">
            <a href="{url}" style="background:#F9A800; color:#fff; padding:0.75rem 1.5rem;
               border-radius:8px; text-decoration:none; font-weight:700;">
                Account aanmaken
            </a>
        </p>
        <p style="color:#888; font-size:0.85rem;">
            Of kopieer deze link: <a href="{url}">{url}</a><br>
            Deze uitnodiging is 7 dagen geldig.
        </p>
    </div>
    """
    return _send(to, f"Uitnodiging voor Check Your Pockets van {invited_by}", html)
