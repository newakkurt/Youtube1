import json

import requests

from config import *

API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def check():
    """Üretime başlamadan önce token ve chat id doğrula (8 dk boşa gitmesin)."""
    me = requests.get(f"{API}/getMe", timeout=30)
    if me.status_code != 200:
        raise RuntimeError(f"Telegram token geçersiz ({me.status_code}). TELEGRAM_BOT_TOKEN secret'ını kontrol et.")
    chat = requests.get(f"{API}/getChat", params={"chat_id": TELEGRAM_CHAT_ID}, timeout=30)
    if chat.status_code != 200:
        raise RuntimeError("Telegram chat id yanlış ya da botuna /start yazılmamış. TELEGRAM_CHAT_ID secret'ını kontrol et.")
    print("Telegram OK:", me.json()["result"]["username"])


def send(text):
    try:
        r = requests.post(f"{API}/sendMessage",
                          json={"chat_id": TELEGRAM_CHAT_ID, "text": text[:4000], "disable_web_page_preview": True}, timeout=30)
        if r.status_code != 200:
            print("Telegram send hatası:", r.status_code, r.text[:200])
    except Exception as e:
        print("Telegram send hatası:", e)


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
