"""Read current Sonos/library readiness; no playback, volume, queue, or device writes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))
from control_center.sonos import SonosAdapter
from control_center.apple_music import AppleMusicClient
from control_center.credentials import CredentialStore

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--speaker-ip", default=os.environ.get("DESKDIAL_SPEAKER_IP", ""),
                    help="the Sonos speaker to read (or set DESKDIAL_SPEAKER_IP)")
parser.add_argument("--room-uid", default=os.environ.get("DESKDIAL_ROOM_UID") or None,
                    help="optional RINCON_... room UID to pin (or set DESKDIAL_ROOM_UID)")
ARGS = parser.parse_args()
if not ARGS.speaker_ip:
    parser.error("give --speaker-ip or set DESKDIAL_SPEAKER_IP")

def sonos():
    state = SonosAdapter(ARGS.speaker_ip, room_uid=ARGS.room_uid).read_state()
    return {key: state.get(key) for key in ("online", "group_label", "group_room_count", "volume", "playback", "can_previous", "can_next")}

def music():
    credentials = CredentialStore(APP / "local/credentials.bin").load()
    page = AppleMusicClient(credentials).recent()
    return {"authorized": True, "page_items": len(page["items"]), "has_more": bool(page.get("next"))}

result = {"checked_at": datetime.now(timezone.utc).isoformat(), "read_only": True}
with ThreadPoolExecutor(max_workers=2) as pool:
    futures = {"sonos": pool.submit(sonos), "apple_music": pool.submit(music)}
    for name, future in futures.items():
        try:
            result[name] = future.result()
        except Exception as exc:
            result[name] = {"ready": False, "error_type": type(exc).__name__}
(APP / "diagnostics/live-readiness-after-install.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
