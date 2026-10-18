import asyncio
# MoviePy'nin HDR klip "side data" satırında çökmesini engelle
from moviepy.video.io import ffmpeg_reader as _fr

_orig_parse = _fr.FFmpegInfosParser.parse_metadata_field_value


def _safe_parse(self, line):
    try:
        return _orig_parse(self, line)
    except ValueError:
        return "", ""


_fr.FFmpegInfosParser.parse_metadata_field_value = _safe_parse

import random
import shutil
import textwrap

import edge_tts
import numpy as np
import requests
from moviepy import AudioFileClip, ColorClip, CompositeVideoClip, ImageClip, VideoFileClip, concatenate_videoclips
from moviepy.video.fx import Loop
from PIL import Image, ImageDraw, ImageFont

from config import *

W, H = 1080, 1920
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

# script_gen.STOCK_KEYWORDS ile aynı liste: konuyla uyumlu görüntüler
ALLOWED_KEYWORDS = [
    "hands typing laptop keyboard", "network switch cables", "server rack", "laptop code screen",
    "ethernet cable closeup", "data center corridor", "engineer laptop",
]


def _font(size, path=FONT_PATH):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


_edge_ok = True

def tts(text, path):
    global _edge_ok
    if _edge_ok:
        try:
            asyncio.run(edge_tts.Communicate(text, VOICE, rate="+5%").save(str(path)))
            return
        except Exception as e:
            print(f"edge-tts FAIL, gTTS'e geçiliyor: {e}")
            _edge_ok = False  # sonraki sahnelerde tekrar deneme
    from gtts import gTTS
    gTTS(text=text, lang=VOICE[:2]).save(str(path))

def fetch_clip(keyword, dest):
    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": PEXELS_API_KEY},
        params={"query": keyword, "orientation": "portrait", "size": "medium", "per_page": 8},
        timeout=30,
    )
    r.raise_for_status()
    vids = r.json().get("videos", [])
    random.shuffle(vids)
    for v in vids:
        files = [f for f in v["video_files"] if f["height"] > f["width"] and f["width"] <= 1080]
        if not files:
            continue
        best = max(files, key=lambda f: f["width"])
        dest.write_bytes(requests.get(best["link"], timeout=90).content)
        return dest
    return None


def caption_png(text, size=None):
    """Ekran yazısı: kısa kural cümleleri büyük, okunaklı, koyu şeritli."""
    text = str(text).strip()
    size = size or (80 if len(text) <= 45 else 70 if len(text) <= 75 else 60)
    font = _font(size)
    img = Image.new("RGBA", (W, 760), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lines = textwrap.wrap(text, width=max(14, int(1000 / (size * 0.62))))[:6]
    block_h = len(lines) * (size + 16)
    d.rounded_rectangle([40, -10, W - 40, block_h + 20], radius=36, fill=(0, 0, 0, 120))
    y = 8
    for line in lines:
        w = d.textbbox((0, 0), line, font=font)[2]
        d.text(((W - w) / 2, y), line, font=font, fill="white", stroke_width=6, stroke_fill="black")
        y += size + 16
    return np.array(img)


def watermark_png(text):
    font = _font(40)
    img = Image.new("RGBA", (W, 80), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = d.textbbox((0, 0), text, font=font)[2]
    d.text(((W - w) / 2, 10), text, font=font, fill=(255, 255, 255, 200), stroke_width=3, stroke_fill="black")
    return np.array(img)


def build_scene(i, scene, tmp):
    apath = tmp / f"a{i}.mp3"
    tts(scene["text"], apath)
    audio = AudioFileClip(str(apath))
    d = audio.duration + 0.25

    kw = scene.get("keyword")
    if kw not in ALLOWED_KEYWORDS:
        kw = random.choice(ALLOWED_KEYWORDS)
    vpath = fetch_clip(kw, tmp / f"v{i}.mp4")
    if vpath:
        clip = VideoFileClip(str(vpath)).without_audio()
        scale = max(W / clip.w, H / clip.h)
        clip = clip.resized(scale)
        clip = clip.cropped(x_center=clip.w / 2, y_center=clip.h / 2, width=W, height=H)
        clip = clip.with_effects([Loop(duration=d)]) if clip.duration < d else clip.subclipped(0, d)
    else:
        clip = ColorClip((W, H), color=(15, 23, 42), duration=d)

    layers = [
        clip,
        ColorClip((W, H), color=(0, 0, 0), duration=d).with_opacity(0.30),
        # Ekranda kısa "caption" varsa o, yoksa anlatım metni
        ImageClip(caption_png(scene.get("caption") or scene["text"])).with_duration(d).with_position(("center", 950)),
    ]
    if CHANNEL_TAG:
        layers.append(ImageClip(watermark_png(CHANNEL_TAG)).with_duration(d).with_position(("center", 90)))
    return CompositeVideoClip(layers, size=(W, H)).with_duration(d).with_audio(audio)


def build(script, out_path):
    OUT.mkdir(exist_ok=True)
    tmp = OUT / f"tmp_{out_path.stem}"
    tmp.mkdir(exist_ok=True)
    try:
        scenes = [build_scene(i, s, tmp) for i, s in enumerate(script["scenes"])]
        final = concatenate_videoclips(scenes, method="compose")
        final.write_videofile(str(out_path), fps=30, codec="libx264", audio_codec="aac",
                              bitrate="3000k", preset="veryfast", threads=2, logger=None)
        final.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_path


# =====================================================================
# Uzun format (16:9, 5-7 dk): stok video yok, her sahne PIL ile çizilir
# =====================================================================
LW, LH = 1920, 1080
_BG, _FG, _ACCENT, _HOT, _DIM = (15, 23, 42), (241, 245, 249), (56, 189, 248), (251, 146, 60), (148, 163, 184)


def _wrap_px(d, text, f, max_w):
    lines, cur = [], ""
    for w in str(text).split():
        t = (cur + " " + w).strip()
        if d.textbbox((0, 0), t, font=f)[2] <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _base(heading):
    img = Image.new("RGB", (LW, LH), _BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, LW, 12], fill=_ACCENT)
    f, y = _font(60), 70
    for line in _wrap_px(d, heading, f, LW - 240)[:2]:
        d.text((120, y), line, font=f, fill=_FG)
        y += 76
    d.line([(120, y + 10), (520, y + 10)], fill=_ACCENT, width=6)
    if CHANNEL_TAG:
        ft = _font(32)
        w = d.textbbox((0, 0), CHANNEL_TAG, font=ft)[2]
        d.text((LW - w - 60, LH - 60), CHANNEL_TAG, font=ft, fill=_DIM)
    return img, d, y + 60


def _draw_title(s):
    img = Image.new("RGB", (LW, LH), _BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, LW, 12], fill=_ACCENT)
    f = _font(88)
    lines = _wrap_px(d, s.get("heading", ""), f, LW - 300)[:3]
    y = (LH - len(lines) * 110) // 2
    for line in lines:
        w = d.textbbox((0, 0), line, font=f)[2]
        d.text(((LW - w) / 2, y), line, font=f, fill=_FG)
        y += 110
    d.line([(LW / 2 - 200, y + 20), (LW / 2 + 200, y + 20)], fill=_ACCENT, width=8)
    if CHANNEL_TAG:
        ft = _font(40)
        w = d.textbbox((0, 0), CHANNEL_TAG, font=ft)[2]
        d.text(((LW - w) / 2, y + 60), CHANNEL_TAG, font=ft, fill=_DIM)
    return img


def _draw_bullets(s):
    img, d, y = _base(s.get("heading", ""))
    f = _font(50)
    for b in s.get("bullets", [])[:5]:
        lines = _wrap_px(d, b, f, LW - 360)[:3]
        d.ellipse([130, y + 16, 154, y + 40], fill=_ACCENT)
        for line in lines:
            d.text((190, y), line, font=f, fill=_FG)
            y += 66
        y += 36
    return img


def _draw_terminal(s):
    img, d, y = _base(s.get("heading", ""))
    x0, x1, y1 = 120, LW - 120, LH - 110
    d.rounded_rectangle([x0, y, x1, y1], radius=22, fill=(2, 6, 23), outline=(51, 65, 85), width=3)
    for i, c in enumerate([(239, 68, 68), (234, 179, 8), (34, 197, 94)]):
        d.ellipse([x0 + 28 + i * 40, y + 24, x0 + 52 + i * 40, y + 48], fill=c)
    f, ty = _font(38, FONT_MONO), y + 84
    for line in s.get("lines", [])[:11]:
        line = str(line)[:72]
        is_cmd = ("#" in line[:30]) or (">" in line[:30])
        d.text((x0 + 40, ty), line, font=f, fill=(134, 239, 172) if is_cmd else (203, 213, 225))
        ty += 54
    return img


def _draw_topology(s):
    img, d, y = _base(s.get("heading", ""))
    nodes = [str(n) for n in s.get("nodes", [])][:5] or ["Device"]
    n, bw, bh = len(nodes), 290, 150
    gap = (LW - 2 * 150 - n * bw) // max(n - 1, 1) if n > 1 else 0
    cy = y + 170
    hi = s.get("highlight")
    f = _font(34)
    for i, name in enumerate(nodes):
        x = 150 + i * (bw + gap)
        hot = hi == i
        d.rounded_rectangle([x, cy - bh // 2, x + bw, cy + bh // 2], radius=24,
                            fill=(124, 45, 18) if hot else (30, 41, 59),
                            outline=_HOT if hot else _ACCENT, width=5)
        ls = _wrap_px(d, name, f, bw - 30)[:2]
        ty = cy - len(ls) * 22
        for line in ls:
            w = d.textbbox((0, 0), line, font=f)[2]
            d.text((x + (bw - w) / 2, ty), line, font=f, fill=_FG)
            ty += 44
        if i < n - 1:
            ax0, ax1 = x + bw + 12, x + bw + gap - 12
            d.line([(ax0, cy), (ax1, cy)], fill=_DIM, width=6)
            d.polygon([(ax1, cy), (ax1 - 22, cy - 14), (ax1 - 22, cy + 14)], fill=_DIM)
    fn, ny = _font(46), cy + bh + 90
    for line in _wrap_px(d, s.get("note", ""), fn, LW - 300)[:4]:
        d.text((150, ny), line, font=fn, fill=_HOT)
        ny += 62
    return img


_DRAW = {"title": _draw_title, "bullets": _draw_bullets, "terminal": _draw_terminal, "topology": _draw_topology}


def build_scene_long(i, s, tmp):
    apath = tmp / f"a{i}.mp3"
    tts(s["text"], apath)
    audio = AudioFileClip(str(apath))
    d = audio.duration + 0.4
    frame = np.array(_DRAW[s["kind"]](s))
    clip = ImageClip(frame).with_duration(d).resized(lambda t: 1 + 0.05 * t / d)  # hafif zoom
    scene = CompositeVideoClip([clip.with_position("center")], size=(LW, LH)).with_duration(d).with_audio(audio)
    return scene, d


def _ts(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def build_long(script, out_path):
    """script_gen.generate_long() çıktısından videoyu üretir.
    (yol, chapters_metni) döndürür; chapters'ı YouTube açıklamasına ekle."""
    OUT.mkdir(exist_ok=True)
    tmp = OUT / f"tmp_{out_path.stem}"
    tmp.mkdir(exist_ok=True)
    try:
        scenes, durs = [], []
        for i, s in enumerate(script["scenes"]):
            sc, d = build_scene_long(i, s, tmp)
            scenes.append(sc)
            durs.append(d)
        final = concatenate_videoclips(scenes, method="compose")
        final.write_videofile(str(out_path), fps=24, codec="libx264", audio_codec="aac",
                              bitrate="2500k", preset="veryfast", threads=2, logger=None)
        final.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    t, rows = 0.0, []
    for s, d in zip(script["scenes"], durs):
        rows.append(f"{_ts(t)} {s.get('heading') or 'Intro'}")
        t += d
    return out_path, "\n".join(rows)
