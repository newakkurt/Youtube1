"""
Instagram Reels yayıncı — Instagram API with Instagram Login (Facebook Page gerekmez).
Bu hesap tipi dosya yüklemeyi kabul etmiyor, video_url (public link) istiyor.
Akış: videoyu IG biçimine çevir -> geçici host'a yükle -> link ile Reels container -> işle -> yayınla.
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
    """H.264 + yuv420p + 30fps + AAC 48k stereo + faststart (moov başta). Ses yoksa sessiz ses ekler."""
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
    return url.replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)


def _fetchable(url: str) -> str:
    """Instagram botu gibi linke bak; durumu kısa metin olarak döndür."""
    try:
        r = requests.get(
            url, stream=True, timeout=30, allow_redirects=True,
            headers={"User-Agent": "facebookexternalhit/1.1", "Range": "bytes=0-1023"},
        )
        ctype = r.headers.get("Content-Type", "?")
        r.close()
        return f"{r.status_code} {ctype}"
    except Exception as e:
        return f"erişilemedi: {str(e)[:80]}"


def upload_public(video_path: str):
    """(url, host_adı, erişim_durumu) döndürür. Erişilebilir ilk host'u seçer."""
    errors, fallback = [], None
    for fn in (_host_litterbox, _host_tmpfiles):
        try:
            url = fn(video_path)
        except Exception as e:
            errors.append(f"{fn.__name__}: {str(e)[:120]}")
            continue
        status = _fetchable(url)
        name = fn.__name__.replace("_host_", "")
        ok = status.startswith(("200", "206")) and "video" in status.lower()
        if ok:
            return url, name, status
        fallback = fallback or (url, name, status)
        errors.append(f"{name}: IG botuna uygun değil ({status})")
    if fallback:
        return fallback
    raise RuntimeError("Geçici host yüklemesi başarısız: " + " | ".join(errors))


def publish_reel(video_path: str, caption: str, timeout_s: int = 420) -> str:
    # 0) IG biçimine çevir
    ig_path = make_ig_compatible(video_path)

    # 1) Videoyu public linke koy
    video_url, host, fetch_status = upload_public(ig_path)

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
            raise RuntimeError(f"[processing] {s} | host={host} erisim={fetch_status}")
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
