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


def _font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        return ImageFont.load_default()


def tts(text, path):
    asyncio.run(edge_tts.Communicate(text, VOICE, rate="+5%").save(str(path)))


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


def caption_png(text, size=64):
    font = _font(size)
    img = Image.new("RGBA", (W, 760), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 0
    for line in textwrap.wrap(text, width=22):
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

    vpath = fetch_clip(scene["keyword"], tmp / f"v{i}.mp4")
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
        ImageClip(caption_png(scene["text"])).with_duration(d).with_position(("center", 950)),
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
