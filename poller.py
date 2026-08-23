import os
import base64
import json
import time
import requests
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

ALLOWED_SENDERS = {
    "placements@cumminscollege.in",
    "comments-noreply@docs.google.com",
    "internship.coordinaorscomp@cumminscollege.in",
    "rakhi.dongaonkar@cumminscollege.in",
    "vrunani.muley@cumminscollege.in",
}

SEEN_FILE = "seen_messages.json"

creds = Credentials(
    None,
    refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
    client_id=os.environ["GMAIL_CLIENT_ID"],
    client_secret=os.environ["GMAIL_CLIENT_SECRET"],
    token_uri="https://oauth2.googleapis.com/token"
)
gmail_service = build('gmail', 'v1', credentials=creds)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"


def load_seen_ids():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r') as f:
            data = json.load(f)
            return set(data.get('ids', []))
    return set()


def save_seen_ids(seen_ids):
    # Keep the list from growing forever: retain only the most recent 500 IDs
    trimmed = list(seen_ids)[-500:]
    with open(SEEN_FILE, 'w') as f:
        json.dump({'ids': trimmed}, f)


def sender_is_allowed(headers):
    for h in headers:
        if h['name'] == 'From':
            return any(addr in h['value'] for addr in ALLOWED_SENDERS)
    return False


def extract_body(payload):
    """Pull plain text body out of a Gmail message payload, handling nested MIME parts."""
    if 'parts' in payload:
        for part in payload['parts']:
            if part.get('mimeType') == 'text/plain' and 'data' in part.get('body', {}):
                return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
            if 'parts' in part:
                result = extract_body(part)
                if result:
                    return result
    elif payload.get('body', {}).get('data'):
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
    return ""


def summarize_email(body_text, max_retries=3):
    if not body_text.strip():
        return "(no readable content)"

    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY
    }
    payload = {
        "contents": [{
            "parts": [{"text": f"Summarize this email in under 5 lines, plain text, no preamble:\n\n{body_text[:3000]}"}]
        }]
    }

    for attempt in range(1, max_retries + 1):
        response = requests.post(GEMINI_URL, headers=headers, json=payload)

        if response.status_code == 200:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

        print(f"Gemini API error {response.status_code} (attempt {attempt}/{max_retries}): {response.text}")

        # 503 = model temporarily overloaded, 429 = rate limited — both worth retrying briefly
        if response.status_code in (503, 429) and attempt < max_retries:
            time.sleep(attempt * 3)  # 3s, then 6s
            continue

        return f"(summary failed: {response.status_code})"

    return "(summary failed: retries exhausted)"


def send_telegram_notification(from_addr, subject, summary, received_time):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"New tracked email\nFrom: {from_addr}\nSubject: {subject}\nReceived: {received_time}\n\nSummary:\n{summary}"
    }
    response = requests.post(url, data=payload)
    if response.status_code == 200:
        print(f"Telegram sent: {response.json()['result']['message_id']}")
    else:
        print(f"Telegram send failed: {response.status_code} {response.text}")


def main():
    seen_ids = load_seen_ids()
    new_seen_ids = set(seen_ids)

    results = gmail_service.users().messages().list(
        userId='me',
        q="newer_than:1h",
        labelIds=['INBOX']
    ).execute()

    messages = results.get('messages', [])
    if not messages:
        print("No recent messages.")
        return

    for m in messages:
        msg_id = m['id']

        if msg_id in seen_ids:
            continue  # already notified about this one, skip it

        msg = gmail_service.users().messages().get(
            userId='me', id=msg_id, format='full'
        ).execute()
        headers = msg['payload']['headers']

        if sender_is_allowed(headers):
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '(no subject)')
            from_addr = next((h['value'] for h in headers if h['name'] == 'From'), '(unknown)')

            timestamp_ms = int(msg.get('internalDate', 0))
            received_time = (datetime.fromtimestamp(timestamp_ms / 1000) + timedelta(hours=5, minutes=30)).strftime('%d %b %Y, %I:%M %p')

            body_text = extract_body(msg['payload'])
            summary = summarize_email(body_text)

            print(f"MATCH: From={from_addr} | Subject={subject} | Time={received_time}")
            send_telegram_notification(from_addr, subject, summary, received_time)

        new_seen_ids.add(msg_id)

    save_seen_ids(new_seen_ids)


if __name__ == '__main__':
    main()