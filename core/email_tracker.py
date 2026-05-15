#!/usr/bin/env python3
"""
StrikeCore Email Tracker — Zero-click IP tracking via email.

This is the MOST RELIABLE zero-click method because:
- Email clients (Gmail, Outlook, Apple Mail) load remote images by default
- When the target OPENS the email, the tracking pixel loads from our server
- No click needed — just opening the email is enough
- Works on desktop AND mobile
- Gmail on Android loads images automatically
- Apple Mail loads images automatically
- Outlook loads images after user enables "download images" (often auto-enabled)

Methods:
1. HTML email with invisible tracking pixel
2. HTML email with visible "designed" content that includes tracking
3. Calendar invite with tracking pixel
"""

from __future__ import annotations

import json
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "emails"


def generate_tracking_email(
    tracking_id: str,
    server_url: str,
    to_email: str,
    subject: str = "You've been tagged in a photo",
    template: str = "instagram_notification",
    from_name: str = "Instagram",
    from_email: str = "",
) -> str:
    """Generate an HTML email with embedded tracking pixel.

    The pixel is a 1x1 transparent GIF served from our server.
    When the email is opened, the email client loads the image → IP logged.

    Returns the HTML content (can be sent via SMTP or saved as .html file).
    """
    pixel_url = f"{server_url}/p/{tracking_id}.gif"
    click_url = f"{server_url}/reel/{tracking_id}"

    templates = {
        "instagram_notification": f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#fafafa;padding:20px 0">
<tr><td align="center">
<table width="450" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #dbdbdb;border-radius:4px">
  <tr><td style="padding:20px 24px;border-bottom:1px solid #efefef">
    <img src="https://www.instagram.com/static/images/web/mobile_nav_type_logo.png/735145cfe0a4.png"
         height="29" alt="Instagram" style="height:29px">
  </td></tr>
  <tr><td style="padding:24px">
    <p style="font-size:14px;color:#262626;margin:0 0 12px">Hi,</p>
    <p style="font-size:14px;color:#262626;margin:0 0 12px">Someone tagged you in a photo on Instagram. Tap below to see it.</p>
    <a href="{click_url}" style="display:inline-block;background:#0095f6;color:#fff;text-decoration:none;
       padding:8px 16px;border-radius:4px;font-size:14px;font-weight:600;margin:8px 0">View Photo</a>
    <p style="font-size:12px;color:#8e8e8e;margin:16px 0 0">If you didn't expect this email, you can ignore it.</p>
  </td></tr>
  <tr><td style="padding:16px 24px;border-top:1px solid #efefef;text-align:center">
    <p style="font-size:12px;color:#8e8e8e;margin:0">from Instagram</p>
  </td></tr>
</table>
</td></tr>
</table>
<img src="{pixel_url}" width="1" height="1" style="display:none" alt="">
</body></html>""",

        "linkedin_connection": f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f3f2ef;font-family:-apple-system,Segoe UI,Roboto,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f2ef;padding:20px 0">
<tr><td align="center">
<table width="450" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;box-shadow:0 0 0 1px rgba(0,0,0,.08)">
  <tr><td style="padding:20px 24px;border-bottom:1px solid #e0e0e0">
    <span style="color:#0a66c2;font-size:24px;font-weight:700">in</span>
  </td></tr>
  <tr><td style="padding:24px">
    <p style="font-size:14px;color:#191919;margin:0 0 12px">You have a new connection request.</p>
    <p style="font-size:14px;color:#191919;margin:0 0 16px">Someone wants to connect with you on LinkedIn.</p>
    <a href="{click_url}" style="display:inline-block;background:#0a66c2;color:#fff;text-decoration:none;
       padding:8px 20px;border-radius:20px;font-size:14px;font-weight:600">View Profile</a>
  </td></tr>
</table>
</td></tr>
</table>
<img src="{pixel_url}" width="1" height="1" style="display:none" alt="">
</body></html>""",

        "google_security": f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f8f9fa;font-family:Google Sans,Roboto,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f8f9fa;padding:20px 0">
<tr><td align="center">
<table width="450" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;border:1px solid #dadce0">
  <tr><td style="padding:24px;text-align:center;border-bottom:1px solid #dadce0">
    <span style="color:#4285f4;font-size:22px;font-weight:500">G</span><span style="color:#ea4335;font-size:22px">o</span><span style="color:#fbbc04;font-size:22px">o</span><span style="color:#4285f4;font-size:22px">g</span><span style="color:#34a853;font-size:22px">l</span><span style="color:#ea4335;font-size:22px">e</span>
  </td></tr>
  <tr><td style="padding:24px">
    <p style="font-size:14px;color:#202124;margin:0 0 8px;font-weight:500">Security alert</p>
    <p style="font-size:14px;color:#5f6368;margin:0 0 16px">A new sign-in was detected on your account. If this was you, no action is needed.</p>
    <a href="{click_url}" style="display:inline-block;background:#1a73e8;color:#fff;text-decoration:none;
       padding:8px 24px;border-radius:4px;font-size:14px;font-weight:500">Check Activity</a>
    <p style="font-size:12px;color:#80868b;margin:16px 0 0">You received this email to let you know about important changes to your account.</p>
  </td></tr>
</table>
</td></tr>
</table>
<img src="{pixel_url}" width="1" height="1" style="display:none" alt="">
</body></html>""",

        "delivery_notification": f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Helvetica,Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:20px 0">
<tr><td align="center">
<table width="450" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:4px">
  <tr><td style="padding:20px 24px;background:#ff9900;border-radius:4px 4px 0 0">
    <span style="color:#fff;font-size:18px;font-weight:700">Package Update</span>
  </td></tr>
  <tr><td style="padding:24px">
    <p style="font-size:14px;color:#333;margin:0 0 12px">Your package is on its way!</p>
    <p style="font-size:14px;color:#333;margin:0 0 16px">Estimated delivery: Today by 9 PM</p>
    <a href="{click_url}" style="display:inline-block;background:#ff9900;color:#fff;text-decoration:none;
       padding:8px 20px;border-radius:4px;font-size:14px;font-weight:600">Track Package</a>
  </td></tr>
</table>
</td></tr>
</table>
<img src="{pixel_url}" width="1" height="1" style="display:none" alt="">
</body></html>""",

        "plain_pixel": f"""<!DOCTYPE html>
<html><body>
<p>Check out this content:</p>
<a href="{click_url}">Click here to view</a>
<img src="{pixel_url}" width="1" height="1" style="display:none" alt="">
</body></html>""",
    }

    return templates.get(template, templates["plain_pixel"])


def save_email_html(tracking_id: str, html: str) -> str:
    """Save generated email HTML to a file accessible by the dashboard."""
    out_dir = Path.home() / "strikecore-data" / "email_trackers"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{tracking_id}.html"
    path.write_text(html)
    return str(path)


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    from_email: str = "",
    from_name: str = "",
    smtp_host: str = "localhost",
    smtp_port: int = 25,
    smtp_user: str = "",
    smtp_pass: str = "",
    use_tls: bool = False,
) -> bool:
    """Send the tracking email via SMTP. Returns True on success."""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{from_name} <{from_email}>" if from_name else from_email
        msg['To'] = to_email
        msg.attach(MIMEText(html_body, 'html'))

        if use_tls:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)

        if smtp_user:
            server.login(smtp_user, smtp_pass)

        server.sendmail(from_email, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"SMTP error: {e}")
        return False
