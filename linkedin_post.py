"""LinkedIn video paylasimi (kisisel profil).

Gerekli ortam degiskenleri:
  LINKEDIN_ACCESS_TOKEN   (zorunlu)
  LINKEDIN_TOKEN_DATE     (opsiyonel, token'in alindigi tarih, YYYY-MM-DD; sure uyarisi icin)
  LINKEDIN_API_VERSION    (opsiyonel, varsayilan 202609; surum hatasi alirsan guncelle)

Ana bot dosyasindan kullanim (2 satir):
  from linkedin_post import publish_linkedin
  li_status = publish_linkedin(video_path, caption)   # Telegram mesajina ekle
"""
import os
import re
import time
from datetime import date, datetime
from urllib.parse import quote

import requests

API = "https://api.linkedin.com"
TOKEN_LIFETIME_DAYS = 60
WARN_AT_DAYS_LEFT = 10


def _headers(extra=None):
    h = {
        "Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}",
        "LinkedIn-Version": os.environ.get("LINKEDIN_API_VERSION", "202609"),
        "X-Restli-Protocol-Version": "2.0.0",
    }
    if extra:
        h.update(extra)
    return h


def _raise(resp, step):
    """Hata olursa LinkedIn'in asil cevabini (token'siz) mesaja koy."""
    if resp.ok:
        return resp
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    body = resp.text.replace(token, "***")[:300] if token else resp.text[:300]
    raise RuntimeError(f"[{step}] HTTP {resp.status_code}: {body}")


def _person_urn():
    r = requests.get(f"{API}/v2/userinfo", headers=_headers(), timeout=30)
    _raise(r, "userinfo")
    return f"urn:li:person:{r.json()['sub']}"


def _escape_commentary(text):
    """LinkedIn metninde ozel karakterler kacirilmazsa paylasim kesilebilir.
    '#' korunur ki hashtag'ler calismaya devam etsin."""
    return re.sub(r"([\\|{}@\[\]()<>*_~])", r"\\\1", text)


def token_warning():
    """Token bitmesine az kaldiysa uyari metni dondurur, yoksa None."""
    raw = os.environ.get("LINKEDIN_TOKEN_DATE")
    if not raw:
        return None
    try:
        issued = datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        return "LINKEDIN_TOKEN_DATE formati hatali, YYYY-MM-DD olmali."
    left = TOKEN_LIFETIME_DAYS - (date.today() - issued).days
    if left <= WARN_AT_DAYS_LEFT:
        return (
            f"LinkedIn token'inin bitmesine {left} gun kaldi. "
            "OAuth 2.0 tools sayfasindan yeni token uret, "
            "LINKEDIN_ACCESS_TOKEN ve LINKEDIN_TOKEN_DATE secret'larini guncelle."
        )
    return None


def _upload_video(owner, video_path):
    with open(video_path, "rb") as f:
        data = f.read()

    r = requests.post(
        f"{API}/rest/videos?action=initializeUpload",
        headers=_headers({"Content-Type": "application/json"}),
        json={
            "initializeUploadRequest": {
                "owner": owner,
                "fileSizeBytes": len(data),
                "uploadCaptions": False,
                "uploadThumbnail": False,
            }
        },
        timeout=60,
    )
    _raise(r, "initializeUpload")
    value = r.json()["value"]
    video_urn = value["video"]

    etags = []
    for part in value["uploadInstructions"]:
        chunk = data[part["firstByte"] : part["lastByte"] + 1]
        up = requests.put(
            part["uploadUrl"],
            data=chunk,
            headers={"Content-Type": "application/octet-stream"},
            timeout=300,
        )
        _raise(up, "uploadPart")
        etags.append(up.headers["ETag"])

    fin = requests.post(
        f"{API}/rest/videos?action=finalizeUpload",
        headers=_headers({"Content-Type": "application/json"}),
        json={
            "finalizeUploadRequest": {
                "video": video_urn,
                "uploadToken": value.get("uploadToken", ""),
                "uploadedPartIds": etags,
            }
        },
        timeout=60,
    )
    _raise(fin, "finalizeUpload")
    return video_urn


def _wait_until_available(video_urn, timeout_s=300):
    url = f"{API}/rest/videos/{quote(video_urn, safe='')}"
    end = time.time() + timeout_s
    while time.time() < end:
        r = requests.get(url, headers=_headers(), timeout=30)
        _raise(r, "videoStatus")
        status = r.json().get("status")
        if status == "AVAILABLE":
            return
        if status == "PROCESSING_FAILED":
            raise RuntimeError("LinkedIn video isleme basarisiz oldu")
        time.sleep(5)
    raise TimeoutError("LinkedIn video isleme zaman asimina ugradi")


def post_to_linkedin(video_path, caption, title=None):
    """Videoyu yukler ve profilde paylasir. Post URN'ini dondurur."""
    owner = _person_urn()
    video_urn = _upload_video(owner, video_path)
    _wait_until_available(video_urn)

    r = requests.post(
        f"{API}/rest/posts",
        headers=_headers({"Content-Type": "application/json"}),
        json={
            "author": owner,
            "commentary": _escape_commentary(caption)[:3000],
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "content": {
                "media": {"title": (title or caption)[:200], "id": video_urn}
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        },
        timeout=60,
    )
    _raise(r, "post")
    return r.headers.get("x-restli-id", "")


def publish_linkedin(video_path, caption):
    """Ana bot dosyasindan cagrilacak tek fonksiyon.
    Instagram'in urettigi *_ig.mp4 varsa onu kullanir, yoksa orijinali.
    Asla exception firlatmaz; Telegram'a eklenecek durum metni dondurur."""
    ig_video = os.path.splitext(video_path)[0] + "_ig.mp4"
    src = ig_video if os.path.exists(ig_video) else video_path
    try:
        post_to_linkedin(src, caption)
        status = "LinkedIn ✅"
    except Exception as e:
        status = f"LinkedIn ❌ {str(e)[:250]}"

    warn = token_warning()
    if warn:
        status += "\n" + warn
    return status
