import os
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from twilio.rest import Client

ALLOWED_SENDERS = {
    "placements@cumminscollege.in",
    "comments-noreply@docs.google.com",
    "internship.coordinaorscomp@cumminscollege.in",
    "rakhi.dongaonkar@cumminscollege.in",
}

creds = Credentials(
    None,
    refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
    client_id=os.environ["GMAIL_CLIENT_ID"],
    client_secret=os.environ["GMAIL_CLIENT_SECRET"],
    token_uri="https://oauth2.googleapis.com/token"
)
gmail_service = build('gmail', 'v1', credentials=creds)

twilio_client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])

def sender_is_allowed(headers):
    for h in headers:
        if h['name'] == 'From':
            return any(addr in h['value'] for addr in ALLOWED_SENDERS)
    return False

def send_whatsapp_notification(from_addr, subject):
    message = twilio_client.messages.create(
        from_=os.environ["TWILIO_WHATSAPP_FROM"],
        to=os.environ["MY_WHATSAPP_TO"],
        body=f"New tracked email\nFrom: {from_addr}\nSubject: {subject}"
    )
    print(f"WhatsApp sent, SID: {message.sid}")

def main():
    # Look at messages received in the last ~10 minutes to avoid re-notifying
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
            send_whatsapp_notification(from_addr, subject)

if __name__ == '__main__':
    main()