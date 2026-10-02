"""Bilgisayarında BİR KEZ çalıştır: pip install google-auth-oauthlib
client_secret.json (Google Cloud > Credentials > OAuth client > Desktop app) aynı klasörde olmalı."""
import json

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
cfg = json.load(open("client_secret.json"))["installed"]
print("\nYT_CLIENT_ID     =", cfg["client_id"])
print("YT_CLIENT_SECRET =", cfg["client_secret"])
print("YT_REFRESH_TOKEN =", creds.refresh_token)
