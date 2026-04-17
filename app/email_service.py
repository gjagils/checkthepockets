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


def send_weekly_digest(
    to: str,
    username: str,
    per_account: list[tuple[str, int]],
    uncat_total: int,
    new_total: int,
) -> bool:
    """Verstuurt een weekly digest met per-account counts en een CTA naar /inbox.

    `per_account` is een lijst van (account_naam, aantal_nieuwe_transacties).
    """
    inbox_url = f"{APP_URL}/inbox"
    settings_url = f"{APP_URL}/settings"

    rows = "".join(
        f"""
        <tr>
            <td style="padding:0.4rem 0; color:#333;">{name}</td>
            <td style="padding:0.4rem 0; text-align:right; font-weight:700; color:#111;">{count}</td>
        </tr>
        """
        for name, count in per_account
    ) or """
        <tr><td style="padding:0.4rem 0; color:#888;" colspan="2">Geen nieuwe transacties afgelopen week.</td></tr>
        """

    html = f"""
    <div style="font-family:sans-serif; max-width:520px; margin:0 auto; color:#222;">
        <h2 style="margin-bottom:0.25rem;">Hoi {username},</h2>
        <p style="color:#666; margin-top:0;">Je wekelijkse overzicht van Check Your Pockets.</p>

        <h3 style="margin-top:1.75rem;">Afgelopen week binnengekomen</h3>
        <table style="width:100%; border-collapse:collapse; font-size:0.95rem;">
            {rows}
            <tr style="border-top:1px solid #e5e5e5;">
                <td style="padding:0.5rem 0; font-weight:700;">Totaal</td>
                <td style="padding:0.5rem 0; text-align:right; font-weight:700;">{new_total}</td>
            </tr>
        </table>

        <p style="text-align:center; margin:2rem 0;">
            <a href="{inbox_url}" style="background:#F9A800; color:#fff; padding:0.75rem 1.5rem;
               border-radius:8px; text-decoration:none; font-weight:700; display:inline-block;">
                Naar mijn inbox
            </a>
        </p>

        <p style="color:#333; text-align:center; margin:1.25rem 0 0.25rem;">
            In totaal staan er <strong>{uncat_total}</strong> transacties nog op review.
        </p>

        <hr style="border:none; border-top:1px solid #eee; margin:2rem 0 1rem;">
        <p style="color:#888; font-size:0.82rem; text-align:center;">
            Ga naar <a href="{settings_url}" style="color:#666;">Instellingen</a> om aan te passen wanneer je deze mail krijgt of om 'm uit te zetten.
        </p>
    </div>
    """
    subject = f"Je hebt {new_total} nieuwe transactie(s) te reviewen" if new_total else f"{uncat_total} transactie(s) wachten in je inbox"
    return _send(to, subject, html)


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
