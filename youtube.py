from datetime import date, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import *

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _creds():
    return Credentials(None, refresh_token=YT_REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token",
                       client_id=YT_CLIENT_ID, client_secret=YT_CLIENT_SECRET, scopes=SCOPES)


def upload(path, title, description, tags):
    yt = build("youtube", "v3", credentials=_creds(), cache_discovery=False)
    body = {
        "snippet": {"title": title[:100], "description": description[:4900], "tags": tags[:15], "categoryId": "28"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(path), mimetype="video/mp4", resumable=True)
    return yt.videos().insert(part="snippet,status", body=body, media_body=media).execute()["id"]


def stats(days=7):
    c = _creds()
    yt = build("youtube", "v3", credentials=c, cache_discovery=False)
    yta = build("youtubeAnalytics", "v2", credentials=c, cache_discovery=False)
    ch = yt.channels().list(part="statistics", mine=True).execute()["items"][0]["statistics"]
    end = date.today()
    start = end - timedelta(days=days)
    common = dict(ids="channel==MINE", startDate=str(start), endDate=str(end))
    r = yta.reports().query(metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost", **common).execute()
    views, mins, gain, lost = (r.get("rows") or [[0, 0, 0, 0]])[0]
    top = yta.reports().query(metrics="views", dimensions="video", sort="-views", maxResults=5, **common).execute().get("rows") or []
    names = {}
    if top:
        items = yt.videos().list(part="snippet", id=",".join(t[0] for t in top)).execute()["items"]
        names = {i["id"]: i["snippet"]["title"] for i in items}
    lines = [
        f"📊 Haftalık rapor ({start} → {end})",
        f"👀 İzlenme: {views}",
        f"⏱ İzlenme süresi: {int(mins)} dk",
        f"👥 Abone: +{gain} / -{lost} (toplam {ch.get('subscriberCount', '?')} / 1000 YPP hedefi)",
        f"🎬 Toplam video: {ch.get('videoCount', '?')}",
        "",
        "🏆 En iyi 5:",
    ]
    lines += [f"{n + 1}. {names.get(t[0], t[0])} — {t[1]} izlenme" for n, t in enumerate(top)]
    return "\n".join(lines)
