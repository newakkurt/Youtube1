import os
import json
from datetime import date, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import *

# ROOT tanımlı değilse config'den gelsin veya mevcut dizin olsun
if 'ROOT' not in globals():
    ROOT = Path(__file__).resolve().parent

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _creds():
    return Credentials(None, refresh_token=YT_REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token",
                       client_id=YT_CLIENT_ID, client_secret=YT_CLIENT_SECRET, scopes=SCOPES)


def check_token():
    """OAuth yenilemeyi ve bağlı YouTube kanalına erişimi yükleme yapmadan test eder."""
    try:
        from google.auth.transport.requests import Request
        creds = _creds()
        creds.refresh(Request())
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        result = yt.channels().list(part="id,snippet", mine=True).execute()
        channels = result.get("items") or []
        if not channels:
            return False, "🔑 OAuth yenilendi ancak mine=true ile YouTube kanalı bulunamadı. OAuth hesabı/kanal veya YouTube API erişimini kontrol et."
        channel = channels[0]
        title = channel.get("snippet", {}).get("title", "Kanal adı alınamadı")
        return True, f"🔑 YouTube OAuth + API erişimi başarılı ✅ Kanal: {title} (ID: {channel.get('id', '?')})"
    except Exception as e:
        detail = str(e)
        if getattr(e, "content", None):
            try:
                detail += " | API: " + e.content.decode("utf-8", errors="replace")[:1000]
            except Exception:
                pass
        return False, f"🔑 YouTube bağlantı testi başarısız ❌ {type(e).__name__}: {detail[:1200]}"


def upload(path, title, description, tags):
    yt = build("youtube", "v3", credentials=_creds(), cache_discovery=False)
    body = {
        "snippet": {"title": title[:100], "description": description[:4900], "tags": tags[:15], "categoryId": "28"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(path), mimetype="video/mp4", resumable=True)
    return yt.videos().insert(part="snippet,status", body=body, media_body=media).execute()["id"]


def privacy(video_id):
    """Yüklenen videonun gizlilik durumu (public/private). Hata olursa None."""
    try:
        yt = build("youtube", "v3", credentials=_creds(), cache_discovery=False)
        items = yt.videos().list(part="status", id=video_id).execute()["items"]
        return items[0]["status"]["privacyStatus"] if items else None
    except Exception:
        return None


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


def save_performance(hooks=None, days=90, n=20):
    """En çok izlenen videoları performance.json'a yazar. script_gen.winners() bunu okuyup
    yeni scriptlerin prompt'una örnek olarak verir. hooks: {video_id: açılış cümlesi}."""
    hooks = hooks or {}
    c = _creds()
    yt = build("youtube", "v3", credentials=c, cache_discovery=False)
    yta = build("youtubeAnalytics", "v2", credentials=c, cache_discovery=False)
    end = date.today()
    start = end - timedelta(days=days)
    top = yta.reports().query(
        ids="channel==MINE", startDate=str(start), endDate=str(end),
        metrics="views", dimensions="video", sort="-views", maxResults=n,
    ).execute().get("rows") or []
    if not top:
        return 0
    items = yt.videos().list(part="snippet", id=",".join(t[0] for t in top)).execute()["items"]
    names = {i["id"]: i["snippet"]["title"] for i in items}
    rows = []
    for vid, views in top:
        if not names.get(vid):
            continue
        row = {"video_id": vid, "title": names[vid], "views": int(views)}
        if hooks.get(vid):
            row["hook"] = hooks[vid]
        rows.append(row)
    (ROOT / "performance.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(rows)
