import sys
from google_auth_oauthlib.flow import InstalledAppFlow

client_id = sys.argv[1]
client_secret = sys.argv[2]

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

flow = InstalledAppFlow.from_client_config(
    {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:9876/"]
        }
    },
    scopes=SCOPES
)

credentials = flow.run_local_server(port=9876, prompt='consent')
print(f"Refresh Token: {credentials.refresh_token}")