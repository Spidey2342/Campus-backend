import os
import requests
from dotenv import load_dotenv

load_dotenv()

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "CampusVibe <onboarding@resend.dev>")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://campus-loop-peach.vercel.app")


def send_password_reset_email(to_email: str, username: str, reset_token: str) -> bool:
    """
    Sends a password reset email via Resend.
    Returns True if sent successfully, False otherwise (never raises —
    we don't want a broken email provider to crash the forgot-password flow,
    and we never want to reveal via errors whether an email exists).
    """
    if not RESEND_API_KEY:
        print("RESEND_API_KEY not set — skipping email send")
        return False

    reset_link = f"{FRONTEND_URL}/reset-password?token={reset_token}"

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px;">
      <h2 style="color: #0d9488;">CampusVibe</h2>
      <p>Hi {username},</p>
      <p>We received a request to reset your CampusVibe password. Click the button below to set a new one:</p>
      <a href="{reset_link}"
         style="display: inline-block; background: #14b8a6; color: #000; font-weight: 600;
                padding: 12px 28px; border-radius: 999px; text-decoration: none; margin: 16px 0;">
        Reset Password
      </a>
      <p style="color: #888; font-size: 13px;">This link expires in 30 minutes. If you didn't request this, you can safely ignore this email.</p>
      <p style="color: #888; font-size: 13px;">Or copy this link: {reset_link}</p>
    </div>
    """

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": FROM_EMAIL,
                "to": [to_email],
                "subject": "Reset your CampusVibe password",
                "html": html_body,
            },
            timeout=10,
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Failed to send reset email: {e}")
        return False