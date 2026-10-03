"""DD-RES-010: the Home Assistant Settings Save keeps memory and file in step, and logs a failure.

The nested save() closure of _build_ha_page is rebuilt from its code object with fake
cells, so no Tk window is opened and nothing touches a credential store.
"""
import logging
import threading
from pathlib import Path
import sys
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402

TOKEN = "test-token-not-real"


def _save_code():
    for obj in vars(ui).values():
        fn = getattr(obj, "_build_ha_page", None)
        if fn is not None:
            for const in fn.__code__.co_consts:
                if isinstance(const, types.CodeType) and const.co_name == "save":
                    return const
    raise AssertionError("save() closure not found in _build_ha_page")


class _Label:
    def __init__(self):
        self.calls = []

    def configure(self, **kw):
        self.calls.append(kw)


class _Model:
    token = ""

    def save_values(self):
        return {"ha_area": "area_one", "ha_url": "http://ha.test:8123"}

    def mark_saved(self, _t):
        self.saved = True


class _Owner:
    live = False

    def __init__(self):
        self.config = {"ha_area": "old_area", "ha_url": "http://old.test:8123", "other": 1}
        self.sim_area = None
        self.strip = 0

    def _sim_ha_area(self, area):
        self.sim_area = area

    def _refresh_strip(self):
        self.strip += 1


class _Win:
    def after(self, *_a):
        return None


class _CredentialError(Exception):
    pass


def _build(owner, write, model=None, tokens=None):
    code = _save_code()
    status_text, status_mark = _Label(), _Label()
    cells = {
        "self": owner, "model": model or _Model(), "store": object(),
        "status_text": status_text, "status_mark": status_mark,
        "refresh": lambda: None, "win": _Win(),
        "STORE_LOCK": threading.Lock(), "CredentialError": _CredentialError,
        "save_token": lambda _store, tok: (tokens if tokens is not None else []).append(tok),
    }
    missing = [n for n in code.co_freevars if n not in cells]
    if missing:
        raise AssertionError("unexpected free variables %r" % missing)
    g = dict(vars(ui))
    g["write_settings"] = write
    fn = types.FunctionType(code, g, "save", None,
                            tuple(types.CellType(cells[n]) for n in code.co_freevars))
    return fn, status_text


class HaSettingsSaveTests(unittest.TestCase):
    def test_failed_write_leaves_config_untouched_and_logs_warning(self):
        owner = _Owner()
        before = dict(owner.config)

        def write(_cfg):
            raise OSError("disk full")

        save, status = _build(owner, write)
        with self.assertLogs(ui._log, level=logging.WARNING) as logs:
            save()
        self.assertEqual(owner.config, before, "in-memory settings must not change when the write fails")
        self.assertTrue(any("could not be saved" in c.get("text", "") for c in status.calls))
        rec = [r for r in logs.records if "Home Assistant settings not saved" in r.getMessage()]
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0].levelno, logging.WARNING)
        self.assertIsNotNone(rec[0].exc_info, "the warning carries the traceback")
        self.assertIn("OSError", rec[0].getMessage())
        self.assertNotIn("area_one", rec[0].getMessage())
        self.assertIsNone(owner.sim_area)

    def test_warning_never_contains_the_token(self):
        owner = _Owner()
        model = _Model()
        model.token = TOKEN
        g_save_token = []

        def write(_cfg):
            raise ValueError("boom")

        save, _ = _build(owner, write, model, g_save_token)
        with self.assertLogs(ui._log, level=logging.WARNING) as logs:
            save()
        self.assertEqual(g_save_token, [TOKEN])
        for line in logs.output:
            self.assertNotIn(TOKEN, line)

    def test_successful_write_gets_merged_settings_then_updates_memory(self):
        owner = _Owner()
        written = []

        def write(cfg):
            self.assertEqual(owner.config["ha_area"], "old_area", "memory changes only after the write")
            written.append(dict(cfg))

        save, _ = _build(owner, write)
        save()
        self.assertEqual(written, [{"ha_area": "area_one", "ha_url": "http://ha.test:8123", "other": 1}])
        self.assertEqual(owner.config, written[0])
        self.assertEqual(owner.sim_area, "area_one")
        self.assertEqual(owner.strip, 1)


if __name__ == "__main__":
    unittest.main()
