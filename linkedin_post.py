"""LinkedIn video paylasimi (kisisel profil).

Gerekli ortam degiskenleri:
  LINKEDIN_ACCESS_TOKEN   (zorunlu)
  LINKEDIN_TOKEN_DATE     (opsiyonel, token'in alindigi tarih, YYYY-MM-DD; sure uyarisi icin)
  LINKEDIN_API_VERSION    (opsiyonel, varsayilan 202609; surum hatasi alirsan guncelle)

Kullanim:
  from linkedin_post import post_to_linkedin, token_warning
  post_to_linkedin("video.mp4", "Baslik ve hashtagler #shorts")
"""
import os
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


def _person_urn():
    r = requests.get(f"{API}/v2/userinfo", headers=_headers(), timeout=30)
    r.raise_for_status()
    return f"urn:li:person:{r.json()['sub']}"


def token_warning():
    """Token bitmesine az kaldiysa uyari metni dondurur, yoksa None.
    Bunu Telegram'dan gondermek icin botundaki mevcut mesaj fonksiyonuna ver."""
    raw = os.environ.get("LINKEDIN_TOKEN_DATE")
    if not raw:
        return None
    issued = datetime.strptime(raw, "%Y-%m-%d").date()
    left = TOKEN_LIFETIME_DAYS - (date.today() - issued).days
    if left <= WARN_AT_DAYS_LEFT:
        return (
            f"LinkedIn token'inin bitmesine {left} gun kaldi. "
            "OAuth 2.0 tools sayfasindan yeni token uret, "
            "LINKEDIN_ACCESS_TOKEN ve LINKEDIN_TOKEN_DATE secret'larini guncelle."
        )
    return None


def _upload_video(owner, video_path):
    data = open(video_path, "rb").read()

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
    r.raise_for_status()
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
        up.raise_for_status()
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
    fin.raise_for_status()
    return video_urn


def _wait_until_available(video_urn, timeout_s=300):
    url = f"{API}/rest/videos/{quote(video_urn, safe='')}"
    end = time.time() + timeout_s
    while time.time() < end:
        r = requests.get(url, headers=_headers(), timeout=30)
        r.raise_for_status()
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
            "commentary": caption,
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
    r.raise_for_status()
    return r.headers.get("x-restli-id", "")
