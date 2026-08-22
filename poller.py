import os
import requests
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

def sender_is_allowed(headers):
    for h in headers:
        if h['name'] == 'From':
            return any(addr in h['value'] for addr in ALLOWED_SENDERS)
    return False

def send_telegram_notification(from_addr, subject):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"New tracked email\nFrom: {from_addr}\nSubject: {subject}"
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
            userId='me', id=m['id'], format='metadata',
            metadataHeaders=['From', 'Subject']
        ).execute()
        headers = msg['payload']['headers']

        if sender_is_allowed(headers):
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '(no subject)')
            from_addr = next((h['value'] for h in headers if h['name'] == 'From'), '(unknown)')
            print(f"MATCH: From={from_addr} | Subject={subject}")
            send_telegram_notification(from_addr, subject)

if __name__ == '__main__':
    main()