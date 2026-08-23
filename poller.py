import os
import base64
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


def summarize_email(body_text):
    if not body_text.strip():
        return "(no readable content)"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [{"text": f"Summarize this email in under 5 lines, plain text, no preamble:\n\n{body_text[:3000]}"}]
        }]
    }
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    else:
        return f"(summary failed: {response.status_code})"


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
        msg = gmail_service.users().messages().get(
            userId='me', id=m['id'], format='full'
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


if __name__ == '__main__':
    main()
