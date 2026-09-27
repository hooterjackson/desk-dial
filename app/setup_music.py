"""Import a local MusicKit key and finish browser authorization; never print secrets."""
import argparse
from pathlib import Path
import queue
import time
from control_center.credentials import AuthServer, CredentialStore, MusicKitCredentials


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file")
    parser.add_argument("--team-id")
    parser.add_argument("--key-id")
    args = parser.parse_args()
    store = CredentialStore(Path(__file__).resolve().parent / "local" / "credentials.bin")
    creds = MusicKitCredentials.from_key_file(args.team_id, args.key_id, args.key_file) if args.key_file else store.load()
    store.save(creds)
    server = AuthServer(creds, on_token=store.save)
    print("MusicKit key imported into Windows-protected local storage.", flush=True)
    print("Authorization URL: " + server.start(), flush=True)
    deadline = time.monotonic() + 900
    try:
        while time.monotonic() < deadline:
            try:
                event = server.events.get(timeout=1)
            except queue.Empty:
                continue
            if event["event"] == "authorized":
                print("Apple Music authorized. Encrypted credentials saved.", flush=True)
                return
            print(event.get("message", "Authorization incomplete"), flush=True)
        print("Authorization session expired; run setup again.", flush=True)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
