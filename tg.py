import json

import requests

from config import *

API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def send(text):
    requests.post(f"{API}/sendMessage",
                  json={"chat_id": TELEGRAM_CHAT_ID, "text": text[:4000], "disable_web_page_preview": True}, timeout=30)


def send_video(path, caption, uid):
    kb = {"inline_keyboard": [[
        {"text": "✅ Yayınla", "callback_data": f"ok:{uid}"},
        {"text": "❌ Reddet", "callback_data": f"no:{uid}"},
    ]]}
    with open(path, "rb") as f:
        r = requests.post(f"{API}/sendVideo",
                          data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1000],
                                "reply_markup": json.dumps(kb), "supports_streaming": "true",
                                "width": 1080, "height": 1920},
                          files={"video": f}, timeout=300).json()
    if not r.get("ok"):
        raise RuntimeError(f"Telegram sendVideo hatası: {r}")
    return r["result"]["video"]["file_id"], r["result"]["message_id"]


def download(file_id, dest):
    info = requests.get(f"{API}/getFile", params={"file_id": file_id}, timeout=30).json()
    if not info.get("ok"):
        raise RuntimeError(f"getFile hatası: {info}")
    url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{info['result']['file_path']}"
    dest.write_bytes(requests.get(url, timeout=300).content)
    return dest


def updates(offset):
    r = requests.get(f"{API}/getUpdates",
                     params={"offset": offset, "timeout": 0, "allowed_updates": json.dumps(["message", "callback_query"])},
                     timeout=30).json()
    return r.get("result", [])


def answer_cb(cb_id, text):
    requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": text}, timeout=30)


def edit_caption(message_id, text):
    requests.post(f"{API}/editMessageCaption",
                  json={"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id, "caption": text[:1000]}, timeout=30)
