import os
import email
import imaplib
import requests
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

ALLOWED_SENDERS = {
    "placements@cumminscollege.in",
    "comments-noreply@docs.google.com",
    "internship.coordinaorscomp@cumminscollege.in",
    "rakhi.dongaonkar@cumminscollege.in",
    "vrunani.muley@cumminscollege.in",
}

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GITHUB_MODELS_TOKEN = os.environ["GITHUB_MODELS_TOKEN"]

LOOKBACK = timedelta(hours=1)


def connect():
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    imap.select("INBOX")
    return imap


def sender_is_allowed(from_header):
    return any(addr in from_header for addr in ALLOWED_SENDERS)


def extract_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get(
                "Content-Disposition"
            ):
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="ignore")
        return ""
    else:
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, errors="ignore")


def summarize_email(body_text):
    if not body_text.strip():
        return "(no readable content)"
    url = "https://models.github.ai/inference/chat/completions"
    headers = {
        "Authorization": f"Bearer {GITHUB_MODELS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": f"Summarize this email in under 5 lines, plain text, no preamble:\n\n{body_text[:3000]}",
            }
        ],
        "max_tokens": 200,
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"].strip()
    return f"(summary failed: {response.status_code})"


def send_telegram_notification(from_addr, subject, summary):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"New tracked email\nFrom: {from_addr}\nSubject: {subject}\n\nSummary:\n{summary}",
    }
    response = requests.post(url, data=payload)
    if response.status_code == 200:
        print(f"Telegram sent: {response.json()['result']['message_id']}")
    else:
        print(f"Telegram send failed: {response.status_code} {response.text}")


def main():
    imap = connect()

    since_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%d-%b-%Y")
    status, data = imap.search(None, f'(SINCE "{since_date}")')
    if status != "OK":
        print("IMAP search failed.")
        return

    ids = data[0].split()
    if not ids:
        print("No recent messages.")
        imap.logout()
        return

    cutoff = datetime.now(timezone.utc) - LOOKBACK

    for msg_id in ids:
        status, msg_data = imap.fetch(msg_id, "(RFC822)")
        if status != "OK":
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        date_header = msg.get("Date")
        try:
            msg_date = parsedate_to_datetime(date_header)
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        if msg_date < cutoff:
            continue

        from_addr = msg.get("From", "(unknown)")
        subject = msg.get("Subject", "(no subject)")

        if sender_is_allowed(from_addr):
            body_text = extract_body(msg)
            summary = summarize_email(body_text)
            print(f"MATCH: From={from_addr} | Subject={subject}")
            send_telegram_notification(from_addr, subject, summary)

    imap.logout()


if __name__ == "__main__":
    main()