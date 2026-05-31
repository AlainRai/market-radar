"""
MarketRadar — Alert Bot
========================
Sends alerts when high-probability signals are generated.

Supported channels:
  1. Email (Gmail SMTP) — works immediately
  2. WhatsApp (via Twilio) — optional, add credentials to .env

Alert triggers:
  - Signal probability >= 75% (configurable via env)
  - Golden/Death cross events
  - Volume spike > 2.5x average
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

from db import create_alert

log = logging.getLogger(__name__)

THRESHOLD = int(os.getenv('HIGH_PROBABILITY_ALERT_THRESHOLD', '75'))


def format_email_html(signals: list[dict]) -> str:
    """Format high-probability signals as a clean HTML email."""
    rows = ''
    for s in signals:
        signal_type = s.get('signal', 'watch').upper()
        color = {'BUY': '#00c896', 'SELL': '#ff4d6d', 'WATCH': '#ffb74d'}.get(signal_type, '#888')
        rows += f"""
        <tr>
          <td style="padding:12px 16px;border-bottom:1px solid #1e2940;">
            <strong style="color:#f0f4ff">{s.get('_symbol', 'N/A')}</strong><br>
            <small style="color:#7a8aaa">{s.get('_name', '')}</small>
          </td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e2940;text-align:center;">
            <span style="background:{color}22;color:{color};padding:3px 10px;border-radius:20px;
                         font-size:12px;font-weight:bold;border:1px solid {color}44">
              {signal_type}
            </span>
          </td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e2940;text-align:center;
                     font-family:monospace;font-size:18px;color:{color};font-weight:bold">
            {s.get('probability', 0)}%
          </td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e2940;
                     font-family:monospace;color:#f0f4ff">
            {s.get('_price', 'N/A')}<br>
            <small style="color:#7a8aaa">Target: {s.get('target_price', 'N/A')}</small>
          </td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e2940;color:#7a8aaa;font-size:12px">
            {s.get('rationale', '')[:150]}...
          </td>
        </tr>"""

    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#080c14;font-family:Arial,sans-serif">
  <div style="max-width:700px;margin:0 auto;padding:24px">

    <div style="margin-bottom:24px">
      <span style="font-size:22px;font-weight:bold;color:#f0f4ff">Market</span>
      <span style="font-size:22px;font-weight:bold;color:#5b8fff">Radar</span>
      <span style="float:right;background:#00e5a022;color:#00e5a0;border:1px solid #00e5a033;
                   padding:4px 12px;border-radius:20px;font-size:12px;margin-top:4px">
        ● LIVE ALERT
      </span>
    </div>

    <div style="background:#0d1320;border:1px solid #1a2440;border-radius:12px;
                padding:16px 20px;margin-bottom:16px">
      <div style="font-size:13px;color:#7a8aaa;margin-bottom:4px">
        {len(signals)} HIGH-PROBABILITY SIGNAL{'S' if len(signals) > 1 else ''} DETECTED
      </div>
      <div style="font-size:12px;color:#3d4f70">{now}</div>
    </div>

    <table style="width:100%;border-collapse:collapse;background:#0d1320;
                  border:1px solid #1a2440;border-radius:12px;overflow:hidden">
      <thead>
        <tr style="background:#111827">
          <th style="padding:10px 16px;text-align:left;color:#7a8aaa;font-size:11px;
                     font-family:monospace;letter-spacing:0.5px">STOCK</th>
          <th style="padding:10px 16px;color:#7a8aaa;font-size:11px;font-family:monospace">SIGNAL</th>
          <th style="padding:10px 16px;color:#7a8aaa;font-size:11px;font-family:monospace">PROBABILITY</th>
          <th style="padding:10px 16px;color:#7a8aaa;font-size:11px;font-family:monospace">PRICE / TARGET</th>
          <th style="padding:10px 16px;text-align:left;color:#7a8aaa;font-size:11px;font-family:monospace">RATIONALE</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>

    <div style="margin-top:20px;padding:12px 16px;background:#0d1320;border:1px solid #1a2440;
                border-radius:8px;font-size:11px;color:#3d4f70">
      ⚠️ MarketRadar signals are AI-generated analysis tools, not financial advice.
      Always conduct your own research before making investment decisions.
      Past performance does not guarantee future results.
    </div>

  </div>
</body>
</html>"""


def send_email_alert(signals: list[dict]) -> bool:
    """Send email alert via Gmail SMTP."""
    from_addr = os.getenv('ALERT_EMAIL_FROM')
    to_addr   = os.getenv('ALERT_EMAIL_TO')
    password  = os.getenv('GMAIL_APP_PASSWORD')

    if not all([from_addr, to_addr, password]):
        log.info("  Email not configured — skipping (set ALERT_EMAIL_FROM, ALERT_EMAIL_TO, GMAIL_APP_PASSWORD)")
        return False

    try:
        msg = MIMEMultipart('alternative')
        signal_count = len(signals)
        top_prob = max(s.get('probability', 0) for s in signals)
        symbols  = ', '.join(s.get('_symbol', '') for s in signals[:3])
        msg['Subject'] = f"🎯 MarketRadar: {signal_count} signal{'s' if signal_count > 1 else ''} | {symbols} | Top prob: {top_prob}%"
        msg['From'] = from_addr
        msg['To']   = to_addr

        # Plain text fallback
        plain_lines = [f"MarketRadar — High Probability Alerts\n"]
        for s in signals:
            plain_lines.append(
                f"{s.get('_symbol')} | {s.get('signal','').upper()} | "
                f"{s.get('probability')}% | Target: {s.get('target_price')}"
            )
            plain_lines.append(f"  {s.get('rationale', '')}\n")
        msg.attach(MIMEText('\n'.join(plain_lines), 'plain'))
        msg.attach(MIMEText(format_email_html(signals), 'html'))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(from_addr, password)
            server.sendmail(from_addr, to_addr, msg.as_string())

        log.info(f"  Email alert sent to {to_addr}")
        return True

    except Exception as e:
        log.error(f"  Email send failed: {e}")
        return False


def check_and_send_alerts(db, signals: list[dict]) -> list[dict]:
    """
    Check all generated signals for alert conditions.
    Sends alerts for high-probability signals.
    Returns list of alerts that were triggered.
    """
    triggered = []

    high_prob = [
        s for s in signals
        if s.get('probability', 0) >= THRESHOLD
    ]

    if not high_prob:
        return []

    log.info(f"  {len(high_prob)} signal(s) exceeded {THRESHOLD}% threshold")

    for s in high_prob:
        symbol = s.get('_symbol', 'N/A')
        prob   = s.get('probability', 0)
        signal = s.get('signal', 'watch')
        msg = (f"{symbol}: {signal.upper()} signal at {prob}% probability. "
               f"Target: {s.get('target_price')}. "
               f"{s.get('rationale', '')[:200]}")

        create_alert(db, symbol, 'high_probability', msg, prob)
        triggered.append(s)

    # Send email with all high-probability signals together
    if triggered:
        send_email_alert(triggered)

    return triggered
