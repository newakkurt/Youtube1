"""
Instagram Reels yayıncı — Instagram API with Instagram Login (Facebook Page gerekmez).
Gerekli env: IG_USER_ID, IG_ACCESS_TOKEN
Kullanım:  from instagram_publish import publish_reel
           publish_reel("output/video.mp4", "Başlık + açıklama #tag1 #tag2")
"""
import os
import time
import requests

API = "https://graph.instagram.com/v21.0"
IG_USER_ID = os.environ["IG_USER_ID"]
TOKEN = os.environ["IG_ACCESS_TOKEN"]


def publish_reel(video_path: str, caption: str, timeout_s: int = 300) -> str:
    # 1) Resumable upload container oluştur (public URL gerekmez)
    r = requests.post(
        f"{API}/{IG_USER_ID}/media",
        data={
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption[:2200],
            "access_token": TOKEN,
        },
        timeout=60,
    )
    r.raise_for_status()
    j = r.json()
    container_id, upload_uri = j["id"], j["uri"]

    # 2) Video binary'sini yükle
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        up = requests.post(
            upload_uri,
            headers={
                "Authorization": f"OAuth {TOKEN}",
                "offset": "0",
                "file_size": str(size),
            },
            data=f,
            timeout=300,
        )
    up.raise_for_status()

    # 3) İşlenmesini bekle
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        s = requests.get(
            f"{API}/{container_id}",
            params={"fields": "status_code", "access_token": TOKEN},
            timeout=30,
        ).json()
        code = s.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"IG işleme hatası: {s}")
        time.sleep(5)
    else:
        raise TimeoutError("IG video işleme zaman aşımı")

    # 4) Yayınla
    p = requests.post(
        f"{API}/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": TOKEN},
        timeout=60,
    )
    p.raise_for_status()
    return p.json()["id"]


def refresh_token() -> str:
    """Token ~60 gün geçerli; ayda bir çağır, yeni token'ı secret'a yaz."""
    r = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": TOKEN},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]