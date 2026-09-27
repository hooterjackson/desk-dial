"""Single-owner serial session with verified, reversible RAM-only mappings."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import sys
import threading
import time
import uuid

VENDOR = Path(__file__).resolve().parent / "vendor"
if VENDOR.is_dir():
    sys.path.insert(0, str(VENDOR))

from protocol import EventMapper, LineDecoder, demo_updates


def list_ports():
    try:
        from serial.tools import list_ports as ports
    except ImportError as exc:
        raise RuntimeError("pyserial is missing. Run: python -m pip install --target vendor pyserial==3.5") from exc
    return [(p.device, p.description) for p in ports.comports()]


def open_serial(port):
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError("pyserial is missing. Run: python -m pip install --target vendor pyserial==3.5") from exc
    return serial.Serial(port, baudrate=115200, timeout=0.1, write_timeout=1.0)


def mapping_updates(profile):
    keys = profile.get("keys")
    knob = profile.get("knob")
    if not isinstance(keys, list) or len(keys) != 4 or any(not isinstance(k, dict) for k in keys):
        raise ValueError("Unsupported profile: expected four button mappings")
    if not isinstance(knob, list) or not knob:
        raise ValueError("Unsupported profile: missing knob mappings")
    def normalize_action(action):
        # The published firmware writes "profiles" but reads "profile" for a
        # named-profile key action. Normalize both sides of readback comparison.
        if isinstance(action, dict) and action.get("type") == "profiles" and isinstance(action.get("name"), str):
            action["type"] = "profile"

    restored_keys = deepcopy(keys)
    for key in restored_keys:
        for action in ("pressed", "held", "released"):
            if not isinstance(key.get(action, []), list):
                raise ValueError("Unsupported button action list")
            key.setdefault(action, [])
            for item in key[action]:
                normalize_action(item)
    restored_knob = deepcopy(knob)
    for item in restored_knob:
        if not isinstance(item, dict):
            raise ValueError("Unsupported knob mapping")
        for key in ("every", "cw", "ccw"):
            normalize_action(item.get(key))
    return {"keys": restored_keys, "knob": restored_knob}


def demo_verified(profile, original):
    try:
        actual = mapping_updates(profile)
    except ValueError:
        return False
    if any(key.get(kind) for key in actual["keys"] for kind in ("pressed", "held", "released")):
        return False
    if len(actual["knob"]) != len(original["knob"]):
        return False
    for current, old in zip(actual["knob"], original["knob"]):
        if current.get("type") != "actions" or any(current.get(k) for k in ("every", "cw", "ccw", "actions")):
            return False
        # Check that the device retained the exact motor/haptic configuration.
        if current.get("haptic") != old.get("haptic"):
            return False
    return True


class DeviceSession:
    """Synchronous core; used exclusively by SerialWorker, or by fake tests."""

    def __init__(self, emit, backup_dir, serial_factory=open_serial, request_timeout=3.0):
        self.emit = emit
        self.backup_dir = Path(backup_dir)
        self.serial_factory = serial_factory
        self.request_timeout = request_timeout
        self.serial = None
        self.decoder = LineDecoder()
        self.mapper = EventMapper()
        self.armed = False
        self.current = None
        self.original = None
        self.needs_restore = False
        self.backup_path = None
        self.port = None
        self.identity = None
        self.backup_identity = None
        self.backup_port = None
        self.generation = 0

    def _emit(self, kind, **data):
        self.emit({"kind": kind, "generation": self.generation, **data})

    def _write(self, message):
        data = (json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        if self.serial is None:
            raise OSError("The knob is not connected")
        written = self.serial.write(data)
        if written != len(data):
            raise OSError("Serial write was incomplete; desktop controls remain off")

    def _read(self):
        messages = self.decoder.feed(self.serial.read(4096))
        for message in messages:
            if "error" in message:
                # Report firmware errors, never raw settings (which may contain credentials).
                raise OSError(f"The knob reported: {str(message['error'])[:200]}")
            if isinstance(message.get("current"), str) and message["current"] != self.current:
                if self.armed:
                    self.armed = False
                    self.mapper.reset()
                    self._emit("disarmed", message="The knob changed profile; desktop controls stopped.")
                self.current = message["current"]
                self._emit("profile", name=self.current)
            for action, value in self.mapper.consume(message):
                self._emit("input", action=action, value=value, armed=self.armed)
        return messages

    def _request(self, command, predicate):
        self._write(command)
        deadline = time.monotonic() + self.request_timeout
        while time.monotonic() < deadline:
            for message in self._read():
                if predicate(message):
                    return message
        raise TimeoutError("The knob did not answer in time. Close ZeroOne or other serial apps, then reconnect.")

    def _profiles(self):
        reply = self._request({"profiles": "#all"}, lambda m: isinstance(m.get("profiles"), list) and isinstance(m.get("current"), str))
        name = reply["current"]
        if name not in reply["profiles"] or not 1 <= len(name.encode("utf-8")) <= 20:
            raise ValueError("The device did not return a valid existing current profile")
        return reply

    def _profile(self, name):
        reply = self._request({"profile": name}, lambda m: isinstance(m.get("profile"), dict) and m["profile"].get("name") == name)
        return reply["profile"]

    def connect(self, port):
        if self.serial is not None:
            raise RuntimeError("Disconnect before selecting another port")
        self.generation += 1
        self.port = port
        self.decoder.reset()
        self.mapper.reset()
        self.current = None
        self.serial = self.serial_factory(port)
        settings = self._request({"settings": "?"}, lambda m: isinstance(m.get("settings"), dict))["settings"]
        self.identity = settings.get("serialNumber")
        profiles = self._profiles()
        self.current = profiles["current"]
        if self.needs_restore:
            # A retained in-memory backup may only be applied to its own device.
            if not self.backup_identity or self.identity != self.backup_identity or port != self.backup_port:
                raise RuntimeError("A previous mapping restore is pending. Reconnect the original device on its original port, or power-cycle it and restart this app.")
            self.restore()
        profile = self._profile(self.current)
        mapping_updates(profile)
        self._emit("connected", port=port, profile=self.current,
                   firmware=str(settings.get("firmwareVersion", "unknown")),
                   device=str(settings.get("deviceName", "Nano_D++")))

    def arm(self):
        if self.serial is None:
            raise OSError("Connect the knob before enabling desktop controls")
        if self.armed:
            return
        if self.needs_restore:
            self.restore()
        current = self._profiles()["current"]
        original = self._profile(current)
        mapping_updates(original)
        patch = demo_updates(original)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.backup_path = self.backup_dir / f"profile-{stamp}-{uuid.uuid4().hex[:8]}.json"
        backup = {"createdUtc": stamp, "port": self.port, "deviceSerial": self.identity, "profile": original}
        with self.backup_path.open("x", encoding="utf-8") as output:
            json.dump(backup, output, ensure_ascii=False, indent=2, allow_nan=False)
        self.original = deepcopy(original)
        self.backup_identity = self.identity
        self.backup_port = self.port
        self.needs_restore = True  # Set before writing: a failed write may still reach the device.
        self._write({"profile": current, "updates": patch})
        checked = self._profile(current)
        if not demo_verified(checked, original):
            raise RuntimeError("The knob did not confirm empty native actions. Desktop controls remain off; restoring the original mappings.")
        if self._profiles()["current"] != current:
            raise RuntimeError("The current profile changed during setup. Desktop controls remain off.")
        self.mapper.reset()
        self.armed = True
        self._emit("armed", backup=str(self.backup_path))

    def restore(self):
        self.armed = False
        self.mapper.reset()
        self._emit("disarmed", message="Desktop controls off; checking original mappings.")
        if not self.needs_restore:
            return
        if self.port != self.backup_port or self.identity != self.backup_identity:
            raise RuntimeError("Refusing to restore a backup to a different device or port. Reconnect the original knob; its backup is retained.")
        name = self.original["name"]
        profiles = self._profiles()
        if name not in profiles["profiles"]:
            raise RuntimeError("The original profile no longer exists; retained its backup without creating a new profile")
        desired = mapping_updates(self.original)
        self._write({"profile": name, "updates": desired})
        checked = self._profile(name)
        if mapping_updates(checked) != desired:
            raise RuntimeError("Could not verify the original mappings were restored. Power-cycle the knob to reload its last saved configuration; backup retained.")
        self.needs_restore = False
        self.original = None
        self._emit("restored", message="Desktop controls off. Original mappings restored and verified.")

    def poll(self):
        if self.serial is not None:
            self._read()
            if self.needs_restore and not self.armed:
                self.restore()

    def disconnect(self):
        self.armed = False
        error = None
        try:
            if self.serial is not None and self.needs_restore:
                self.restore()
        except Exception as exc:
            error = exc
        finally:
            if self.serial is not None:
                try:
                    self.serial.close()
                finally:
                    self.serial = None
            self.mapper.reset()
            self._emit("disconnected", message="Disconnected. Desktop controls off.")
        if error:
            raise error


class SerialWorker:
    """Serial operations and bounded waits happen off Tk's thread."""

    def __init__(self, backup_dir, serial_factory=open_serial):
        self.events = queue.Queue()
        self.commands = queue.Queue()
        self.session = DeviceSession(self.events.put, backup_dir, serial_factory)
        self.thread = threading.Thread(target=self._run, name="nanod-serial", daemon=True)
        self.thread.start()

    def submit(self, command, value=None):
        self.commands.put((command, value))

    def _run(self):
        running = True
        while running:
            try:
                try:
                    command, value = self.commands.get(timeout=0.01)
                except queue.Empty:
                    command = None
                if command == "connect":
                    self.session.connect(value)
                elif command == "arm":
                    self.session.arm()
                elif command == "disarm":
                    self.session.restore()
                elif command in ("disconnect", "close"):
                    running = command != "close"
                    self.session.disconnect()
                elif command == "refresh":
                    self.events.put({"kind": "ports", "ports": list_ports()})
                elif command is None:
                    self.session.poll()
            except Exception as exc:
                self.session.armed = False
                message = str(exc)
                try:
                    self.session.disconnect()
                except Exception as restore_error:
                    message += f" Restore could not be verified: {restore_error}"
                if self.session.needs_restore:
                    message += " Backup retained. Reconnect this knob, or power-cycle it to reload the last saved configuration."
                self.events.put({"kind": "error", "message": message})
        self.events.put({"kind": "closed"})
