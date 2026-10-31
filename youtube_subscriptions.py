"""Official YouTube subscription manager.

Safety defaults:
- Disabled unless ENABLE_YT_SUBSCRIPTION_MANAGER=true.
- Dry-run unless YT_SUBSCRIPTION_DRY_RUN=false.
- Only acts on explicitly configured channel IDs.
- Never infers reciprocity from public subscriber counts.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from config import YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN, ROOT

STATE_FILE = ROOT / "yt_subscription_state.json"
SCOPE = ["https://www.googleapis.com/auth/youtube"]
HARD_DAILY_CAP = 50


def _csv_env(name):
    return [x.strip() for x in os.getenv(name, "").split(",") if x.strip()]


def _client():
    if not (YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN):
        raise RuntimeError("YT_CLIENT_ID, YT_CLIENT_SECRET veya YT_REFRESH_TOKEN eksik.")
    creds = Credentials(
        None,
        refresh_token=YT_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET,
        scopes=SCOPE,
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"date": "", "actions": 0, "history": []}


def _save(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _my_subscriptions(yt):
    found = {}
    token = None
    while True:
        result = yt.subscriptions().list(
            part="snippet", mine=True, maxResults=50, pageToken=token
        ).execute()
        for item in result.get("items", []):
            channel = item.get("snippet", {}).get("resourceId", {})
            channel_id = channel.get("channelId")
            if channel_id:
                found[channel_id] = item["id"]
        token = result.get("nextPageToken")
        if not token:
            return found


def run():
    if os.getenv("ENABLE_YT_SUBSCRIPTION_MANAGER", "").lower() != "true":
        print("🛡️ YouTube abonelik yöneticisi kapalı. ENABLE_YT_SUBSCRIPTION_MANAGER=true olmadan işlem yapılmaz.")
        return

    dry_run = os.getenv("YT_SUBSCRIPTION_DRY_RUN", "true").lower() != "false"
    daily_cap = min(HARD_DAILY_CAP, max(1, int(os.getenv("YT_SUBSCRIPTION_DAILY_CAP", "10"))))
    subscribe_ids = list(dict.fromkeys(_csv_env("YT_TARGET_CHANNEL_IDS")))
    unsubscribe_ids = list(dict.fromkeys(_csv_env("YT_UNSUBSCRIBE_CHANNEL_IDS")))

    if not subscribe_ids and not unsubscribe_ids:
        print("Hedef yok. YT_TARGET_CHANNEL_IDS veya YT_UNSUBSCRIBE_CHANNEL_IDS ile kanal ID'leri tanımlayın.")
        return

    yt = _client()
    current = _my_subscriptions(yt)
    state = _state()
    today = datetime.now(timezone.utc).date().isoformat()
    if state.get("date") != today:
        state = {"date": today, "actions": 0, "history": state.get("history", [])}

    plan = []
    for channel_id in subscribe_ids:
        if channel_id in current:
            print(f"Zaten abonesin, atlandı: {channel_id}")
        else:
            plan.append(("subscribe", channel_id))
    for channel_id in unsubscribe_ids:
        if channel_id not in current:
            print(f"Mevcut abonelik bulunamadı, atlandı: {channel_id}")
        else:
            plan.append(("unsubscribe", channel_id))

    remaining = max(0, daily_cap - int(state.get("actions", 0)))
    if len(plan) > remaining:
        print(f"Günlük işlem bütçesi nedeniyle {len(plan) - remaining} işlem sonraki güne bırakıldı.")
    plan = plan[:remaining]

    print(f"YouTube abonelik planı: {len(plan)} işlem | günlük limit={daily_cap} | dry_run={dry_run}")
    for action, channel_id in plan:
        if dry_run:
            print(f"[DRY-RUN] {action}: {channel_id}")
            continue
        if action == "subscribe":
            yt.subscriptions().insert(
                part="snippet",
                body={"snippet": {"resourceId": {"kind": "youtube#channel", "channelId": channel_id}}},
            ).execute()
        else:
            yt.subscriptions().delete(id=current[channel_id]).execute()
        state["actions"] = int(state.get("actions", 0)) + 1
        state.setdefault("history", []).append({
            "date": today, "action": action, "channel_id": channel_id
        })
        state["history"] = state["history"][-500:]
        print(f"OK {action}: {channel_id}")

    if not dry_run:
        _save(state)

    print("Not: YouTube, diğer kanal sahibinin sana abone olup olmadığını her zaman göstermez. "
          "Bu nedenle 1.000 abone eşiği/karşılıklılık üzerinden otomatik abonelik silme yapılmaz. "
          "Silme yalnızca YT_UNSUBSCRIBE_CHANNEL_IDS ile açıkça verdiğin kanal ID'lerinde denenir.")
