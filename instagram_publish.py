"""
Instagram Reels yayıncı — Instagram API with Instagram Login (Facebook Page gerekmez).
Bu hesap tipi dosya yüklemeyi kabul etmiyor, video_url (public link) istiyor.
Akış: videoyu geçici bir host'a yükle -> link ile Reels container -> işle -> yayınla.
Gerekli env: IG_USER_ID, IG_ACCESS_TOKEN
"""
import os
import time
import requests

API = "https://graph.instagram.com/v21.0"
IG_USER_ID = os.environ["IG_USER_ID"]
TOKEN = os.environ["IG_ACCESS_TOKEN"]


def _check(resp, step):
    """Hata olursa Instagram'ın asıl cevabını (token'sız) mesaja koy."""
    if resp.ok:
        return resp
    body = resp.text.replace(TOKEN, "***")[:350]
    raise RuntimeError(f"[{step}] HTTP {resp.status_code}: {body}")


def _host_litterbox(video_path: str) -> str:
    with open(video_path, "rb") as f:
        r = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "24h"},
            files={"fileToUpload": (os.path.basename(video_path), f, "video/mp4")},
            timeout=300,
        )
    r.raise_for_status()
    url = r.text.strip()
    if not url.startswith("http"):
        raise RuntimeError(f"litterbox cevabı beklenmedik: {url[:100]}")
    return url


def _host_tmpfiles(video_path: str) -> str:
    with open(video_path, "rb") as f:
        r = requests.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": (os.path.basename(video_path), f, "video/mp4")},
            timeout=300,
        )
    r.raise_for_status()
    url = r.json()["data"]["url"]
    # sayfa linkini doğrudan indirme linkine çevir
    return url.replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)


def upload_public(video_path: str) -> str:
    errors = []
    for fn in (_host_litterbox, _host_tmpfiles):
        try:
            return fn(video_path)
        except Exception as e:
            errors.append(f"{fn.__name__}: {str(e)[:120]}")
    raise RuntimeError("Geçici host yüklemesi başarısız: " + " | ".join(errors))


def publish_reel(video_path: str, caption: str, timeout_s: int = 420) -> str:
    # 1) Videoyu public linke koy
    video_url = upload_public(video_path)

    # 2) Reels container oluştur
    r = requests.post(
        f"{API}/{IG_USER_ID}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption[:2200],
            "access_token": TOKEN,
        },
        timeout=60,
    )
    _check(r, "container")
    container_id = r.json()["id"]

    # 3) Instagram videoyu çekip işleyene kadar bekle
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        sr = requests.get(
            f"{API}/{container_id}",
            params={"fields": "status_code,status", "access_token": TOKEN},
            timeout=30,
        )
        _check(sr, "status")
        s = sr.json()
        code = s.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"[processing] {s}")
        time.sleep(6)
    else:
        raise TimeoutError("IG video işleme zaman aşımı")

    # 4) Yayınla
    p = requests.post(
        f"{API}/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": TOKEN},
        timeout=60,
    )
    _check(p, "publish")
    return p.json()["id"]


def refresh_token() -> str:
    """Token ~60 gün geçerli; ayda bir çağır, yeni token'ı secret'a yaz."""
    r = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": TOKEN},
        timeout=30,
    )
    _check(r, "refresh")
    return r.json()["access_token"]
