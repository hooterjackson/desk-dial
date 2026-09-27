import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "app"
before = json.loads((root / "backups/control-center-inventory-20260922T163405Z-b8273399.json").read_text(encoding="utf-8"))
after = json.loads((root / "backups/control-center-inventory-20260922T164420Z-ce1e0d80.json").read_text(encoding="utf-8"))
result = dict(saved_profiles_identical=before["profiles"] == after["profiles"],
              current_before=before.get("current"), current_after=after.get("current"),
              settings_changed=[k for k in set(before.get("settings", {})) | set(after.get("settings", {}))
                                if before.get("settings", {}).get(k) != after.get("settings", {}).get(k)])
assert result["saved_profiles_identical"], "Saved profiles changed"
assert result["current_before"] == result["current_after"], "Current saved preset changed"
(root / "diagnostics/install-profile-preservation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
