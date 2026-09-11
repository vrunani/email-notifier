import os
import json
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
GITHUB_MODELS_TOKEN = os.environ["MODELS_TOKEN"]

# --- New: sheet-change detection (Bot 2) ---
SHEETS_CLIENT_ID = os.environ.get("SHEETS_CLIENT_ID")
SHEETS_CLIENT_SECRET = os.environ.get("SHEETS_CLIENT_SECRET")
SHEETS_REFRESH_TOKEN = os.environ.get("SHEETS_REFRESH_TOKEN")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
SHEET_RANGE = os.environ.get("SHEET_RANGE", "A1:Z1000")
SHEET_BOT_TOKEN = os.environ.get("SHEET_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
SHEET_CHAT_ID = os.environ.get("SHEET_CHAT_ID", TELEGRAM_CHAT_ID)
SNAPSHOT_FILE = "sheet_snapshot.json"

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
        "model": "openai/gpt-5-mini",
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


# --- New: Bot 2 helpers ---

def get_sheets_access_token():
    url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": SHEETS_CLIENT_ID,
        "client_secret": SHEETS_CLIENT_SECRET,
        "refresh_token": SHEETS_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }
    response = requests.post(url, data=payload)
    response.raise_for_status()
    return response.json()["access_token"]


def fetch_sheet_data():
    access_token = get_sheets_access_token()
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{SHEET_RANGE}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json().get("values", [])


def load_last_snapshot():
    if os.path.exists(SNAPSHOT_FILE):
        with open(SNAPSHOT_FILE, "r") as f:
            return json.load(f)
    return []


def save_snapshot(data):
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(data, f, indent=2)


def diff_rows(old_rows, new_rows):
    changes = []
    max_len = max(len(old_rows), len(new_rows))
    for i in range(max_len):
        old_row = old_rows[i] if i < len(old_rows) else None
        new_row = new_rows[i] if i < len(new_rows) else None
        if old_row != new_row:
            changes.append({"row": i + 1, "old": old_row, "new": new_row})
    return changes


def summarize_sheet_changes(changes):
    url = "https://models.github.ai/inference/chat/completions"
    headers = {
        "Authorization": f"Bearer {GITHUB_MODELS_TOKEN}",
        "Content-Type": "application/json",
    }
    changes_text = json.dumps(changes, indent=2)[:3000]
    payload = {
        "model": "openai/gpt-5-mini",
        "messages": [
            {
                "role": "user",
                "content": (
                    "These are row changes in a Google Sheet (old vs new values). "
                    "Describe briefly what kind of update this is, in under 5 lines, "
                    "plain text, no preamble:\n\n" + changes_text
                ),
            }
        ],
        "max_tokens": 200,
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"].strip()
    return f"(summary failed: {response.status_code})"


def send_sheet_notification(summary):
    url = f"https://api.telegram.org/bot{SHEET_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": SHEET_CHAT_ID,
        "text": f"Sheet updated\n\n{summary}",
    }
    response = requests.post(url, data=payload)
    if response.status_code == 200:
        print(f"Sheet bot sent: {response.json()['result']['message_id']}")
    else:
        print(f"Sheet bot send failed: {response.status_code} {response.text}")


def check_sheet_update():
    if not SHEETS_CLIENT_ID or not SHEETS_CLIENT_SECRET or not SHEETS_REFRESH_TOKEN or not SPREADSHEET_ID:
        print("Sheet check skipped: missing OAuth secrets or SPREADSHEET_ID.")
        return

    new_rows = fetch_sheet_data()
    old_rows = load_last_snapshot()

    changes = diff_rows(old_rows, new_rows)
    if changes:
        summary = summarize_sheet_changes(changes)
        send_sheet_notification(summary)
        print(f"Sheet changes detected: {len(changes)} row(s).")
    else:
        print("No sheet changes detected.")

    save_snapshot(new_rows)


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
        status, msg_data = imap.fetch(msg_id, "(BODY.PEEK[])")
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

            # Mark only tracked/matched emails as read
            imap.store(msg_id, "+FLAGS", "\\Seen")

            # New branch: this mail is a Google Sheets notification -> check the sheet itself
            if "docs.google.com" in from_addr:
                check_sheet_update()

    imap.logout()


if __name__ == "__main__":
    main()
