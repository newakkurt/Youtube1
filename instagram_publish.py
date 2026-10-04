"""
Instagram Reels yayıncı — Instagram API with Instagram Login (Facebook Page gerekmez).
Bu hesap tipi dosya yüklemeyi kabul etmiyor, video_url (public link) istiyor.
Akış: videoyu IG biçimine çevir -> geçici host'a yükle (link gerçekten MP4 mü doğrula)
      -> link ile Reels container -> işle -> yayınla.
Gerekli env: IG_USER_ID, IG_ACCESS_TOKEN
"""
import os
import re
import subprocess
import time
import requests

API = "https://graph.instagram.com/v21.0"
IG_USER_ID = os.environ["IG_USER_ID"]
TOKEN = os.environ["IG_ACCESS_TOKEN"]
UA = "Mozilla/5.0 (compatible; reels-bot/1.0)"


def _check(resp, step):
    """Hata olursa Instagram'ın asıl cevabını (token'sız) mesaja koy."""
    if resp.ok:
        return resp
    body = resp.text.replace(TOKEN, "***")[:350]
    raise RuntimeError(f"[{step}] HTTP {resp.status_code}: {body}")


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def make_ig_compatible(src: str) -> str:
    """H.264 + yuv420p + 30fps + AAC 48k stereo + faststart. Ses yoksa sessiz ses ekler."""
    ff = _ffmpeg()
    dst = os.path.splitext(src)[0] + "_ig.mp4"

    probe = subprocess.run([ff, "-hide_banner", "-i", src], capture_output=True, text=True)
    has_audio = bool(re.search(r"Stream #\d+:\d+.*Audio:", probe.stderr))

    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    cmd += [
        "-map", "0:v:0",
        "-map", "0:a:0" if has_audio else "1:a:0",
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-r", "30", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k",
        "-movflags", "+faststart",
        "-shortest",
        dst,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
        raise RuntimeError(f"[ffmpeg] {r.stderr[-300:]}")
    return dst


# ---------- Geçici host'lar (hepsi doğrudan dosya linki dönmeli) ----------

def _host_litterbox(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "24h"},
            files={"fileToUpload": (os.path.basename(path), f, "video/mp4")},
            headers={"User-Agent": UA}, timeout=300,
        )
    r.raise_for_status()
    return r.text.strip()


def _host_uguu(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(
            "https://uguu.se/upload",
            files={"files[]": (os.path.basename(path), f, "video/mp4")},
            headers={"User-Agent": UA}, timeout=300,
        )
    r.raise_for_status()
    try:
        return r.json()["files"][0]["url"]
    except Exception:
        return r.text.strip()


def _host_0x0(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(
            "https://0x0.st",
            files={"file": (os.path.basename(path), f, "video/mp4")},
            data={"expires": "24"},
            headers={"User-Agent": "curl/8.5.0"}, timeout=300,
        )
    r.raise_for_status()
    return r.text.strip()


def _host_catbox(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": (os.path.basename(path), f, "video/mp4")},
            headers={"User-Agent": UA}, timeout=300,
        )
    r.raise_for_status()
    return r.text.strip()


HOSTS = (_host_litterbox, _host_uguu, _host_0x0, _host_catbox)


def _is_direct_mp4(url: str) -> str:
    """Linkten ilk baytları çek: MP4 imzası ('ftyp') varsa doğrudan video demektir.
    Boş string = uygun, doluysa sebep."""
    try:
        r = requests.get(url, stream=True, timeout=30, allow_redirects=True,
                         headers={"User-Agent": UA, "Range": "bytes=0-63"})
        head = next(r.iter_content(64), b"")
        ctype = r.headers.get("Content-Type", "?")
        status = r.status_code
        r.close()
        if status not in (200, 206):
            return f"HTTP {status}"
        if b"ftyp" not in head[:16]:
            return f"video değil ({ctype})"
        return ""
    except Exception as e:
        return f"erişilemedi: {str(e)[:60]}"


def upload_public(path: str):
    """İlk doğrulanmış doğrudan-MP4 linkini döndür: (url, host_adı)."""
    notes = []
    for fn in HOSTS:
        name = fn.__name__.replace("_host_", "")
        try:
            url = fn(path)
        except Exception as e:
            notes.append(f"{name}: yükleme hatası {str(e)[:60]}")
            continue
        if not url.startswith("http"):
            notes.append(f"{name}: beklenmedik cevap {url[:50]}")
            continue
        why = _is_direct_mp4(url)
        if not why:
            return url, name
        notes.append(f"{name}: {why}")
    raise RuntimeError("Hiçbir host uygun değil -> " + " | ".join(notes))


def publish_reel(video_path: str, caption: str, timeout_s: int = 420) -> str:
    # 0) IG biçimine çevir
    ig_path = make_ig_compatible(video_path)

    # 1) Videoyu doğrulanmış public linke koy
    video_url, host = upload_public(ig_path)

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
            raise RuntimeError(f"[processing] {s} | host={host}")
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
