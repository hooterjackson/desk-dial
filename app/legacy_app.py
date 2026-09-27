"""Nano_D++ Windows desktop demo. Run with Python 3.10 or later."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import queue
import tkinter as tk
from tkinter import messagebox, ttk

from session import SerialWorker, list_ports
from windows_actions import WindowsActions

APP_DIR = Path(__file__).resolve().parent


class DesktopDemo:
    def __init__(self, root, refresh=True):
        self.root = root
        self.actions = WindowsActions()
        self.worker = SerialWorker(APP_DIR / "backups")
        self.connected = False
        self.closing = False
        self.generation = None
        self.firmware = "—"
        self.preview_level = 50
        self.scroll_total = 0
        self.port = tk.StringVar()
        self.mode = tk.StringVar(value="Volume")
        self.want_armed = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Ready to preview. Connect your knob to begin.")
        self.device = tk.StringVar(value="No device connected")
        self.profile = tk.StringVar(value="Profile: —    Firmware: —")
        self.preview = tk.StringVar(value="Turn the dial to see input here")
        self.root.title("Nano_D++ · Desktop demo")
        self.root.geometry("820x680")
        self.root.minsize(690, 590)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10))
        style.configure("Preview.TLabel", font=("Segoe UI", 17))
        outer = ttk.Frame(root, padding=24)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Nano_D++ / Desktop", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="A physical dial for volume, media, and scrolling.", style="Subtitle.TLabel").pack(anchor="w", pady=(4, 20))

        connection = ttk.LabelFrame(outer, text="1  Connect", padding=12)
        connection.pack(fill="x")
        row = ttk.Frame(connection)
        row.pack(fill="x")
        self.port_box = ttk.Combobox(row, textvariable=self.port, width=35, state="readonly")
        self.port_box.pack(side="left", fill="x", expand=True)
        self.refresh_button = ttk.Button(row, text="Refresh", command=lambda: self.worker.submit("refresh"))
        self.refresh_button.pack(side="left", padx=6)
        self.connect_button = ttk.Button(row, text="Connect", command=self.toggle_connection)
        self.connect_button.pack(side="left")
        ttk.Label(connection, textvariable=self.device).pack(anchor="w", pady=(8, 0))
        ttk.Label(connection, textvariable=self.profile).pack(anchor="w")

        control = ttk.LabelFrame(outer, text="2  Choose desktop controls", padding=12)
        control.pack(fill="x", pady=(14, 0))
        mode_row = ttk.Frame(control)
        mode_row.pack(fill="x")
        ttk.Label(mode_row, text="Dial mode").pack(side="left", padx=(0, 12))
        for mode in ("Volume", "Scroll"):
            ttk.Radiobutton(mode_row, text=mode, value=mode, variable=self.mode).pack(side="left", padx=(0, 16))
        self.arm_button = ttk.Checkbutton(control, text="Enable desktop controls", variable=self.want_armed, command=self.toggle_arm, state="disabled")
        self.arm_button.pack(anchor="w", pady=(12, 6))
        ttk.Label(control, text="A  Mute     B  Play / pause     C  Next track     D  Change dial mode").pack(anchor="w")
        ttk.Label(control, text="Enabling backs up and temporarily replaces the current profile's input mappings.", wraplength=700).pack(anchor="w", pady=(7, 0))

        preview = ttk.LabelFrame(outer, text="3  Input preview", padding=12)
        preview.pack(fill="x", pady=14)
        ttk.Label(preview, textvariable=self.preview, style="Preview.TLabel").pack(anchor="w", pady=(0, 8))
        self.meter = ttk.Progressbar(preview, maximum=100, value=50)
        self.meter.pack(fill="x", pady=(0, 10))
        simulation = ttk.Frame(preview)
        simulation.pack(fill="x")
        ttk.Label(simulation, text="Simulate:").pack(side="left", padx=(0, 8))
        for label, action, value in (("↶ −", "turn", -1), ("↷ +", "turn", 1), ("A", "button", 0), ("B", "button", 1), ("C", "button", 2), ("D", "button", 3)):
            ttk.Button(simulation, text=label, width=6, command=lambda a=action, v=value: self.handle_input(a, v, simulated=True)).pack(side="left", padx=(0, 4))
        ttk.Label(preview, text="Simulation only updates this preview. It never changes Windows.").pack(anchor="w", pady=(8, 0))
        ttk.Label(outer, textvariable=self.status, wraplength=745).pack(anchor="w", pady=(0, 10))
        self.log = tk.Text(outer, height=7, wrap="word", state="disabled", font=("Consolas", 9), relief="solid", borderwidth=1)
        self.log.pack(fill="both", expand=True)
        self.write_log("Desktop output is OFF. Simulation is ready.")
        self.root.after(50, self.poll)
        if refresh:
            self.worker.submit("refresh")

    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{datetime.now():%H:%M:%S}  {text}\n")
        if int(self.log.index("end-1c").split(".")[0]) > 250:
            self.log.delete("1.0", "51.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def stop_output(self):
        self.actions.set_enabled(False)
        self.want_armed.set(False)

    def toggle_connection(self):
        self.stop_output()
        self.connect_button.configure(state="disabled")
        self.arm_button.configure(state="disabled")
        if self.connected:
            self.connected = False
            self.status.set("Restoring the original mappings and disconnecting…")
            self.worker.submit("disconnect")
        else:
            port = self.port.get().split(" — ", 1)[0]
            if not port:
                self.status.set("Choose the knob's COM port, then Connect.")
                self.connect_button.configure(state="normal")
                return
            self.status.set(f"Connecting to {port} and reading the current profile…")
            self.worker.submit("connect", port)

    def toggle_arm(self):
        requested = self.want_armed.get()
        self.actions.set_enabled(False)
        self.arm_button.configure(state="disabled")
        self.connect_button.configure(state="disabled")
        if requested:
            self.status.set("Backing up the current mappings and verifying the demo configuration…")
            self.worker.submit("arm")
        else:
            self.status.set("Desktop controls off. Restoring the original mappings…")
            self.worker.submit("disarm")

    def handle_input(self, action, value, simulated=False, armed=False):
        live = not simulated and armed and self.connected and self.want_armed.get() and self.actions.enabled and not self.closing
        prefix = "Simulation" if simulated else ("Desktop" if live else "Preview")
        if action == "turn":
            if self.mode.get() == "Volume":
                self.preview_level = max(0, min(100, self.preview_level + value * 2))
                self.meter.configure(value=self.preview_level)
                description = f"Volume {'up' if value > 0 else 'down'} · {abs(value)} step(s)"
                operation = lambda: self.actions.volume_steps(value)
            else:
                self.scroll_total += value
                description = f"Scroll {'down' if value > 0 else 'up'} · {abs(value)} step(s)"
                operation = lambda: self.actions.scroll_steps(value)
        else:
            descriptions = ("Mute / unmute", "Play / pause", "Next track", "Change dial mode")
            description = descriptions[value]
            operation = (self.actions.mute, self.actions.play_pause, self.actions.next_track, self.change_mode)[value]
        self.preview.set(f"{prefix} · {description}")
        self.write_log(f"{prefix}: {description}")
        if live:
            try:
                operation()
            except OSError as exc:
                self.stop_output()
                self.status.set(str(exc))
                self.write_log(str(exc))
                self.worker.submit("disarm")

    def change_mode(self):
        self.mode.set("Scroll" if self.mode.get() == "Volume" else "Volume")
        self.preview.set(f"Desktop · Dial mode: {self.mode.get()}")

    def poll(self):
        for _ in range(100):
            try:
                event = self.worker.events.get_nowait()
            except queue.Empty:
                break
            kind = event["kind"]
            if kind == "closed":
                self.root.destroy()
                return
            if self.closing:
                if kind == "error":
                    self.status.set(event["message"])
                    messagebox.showwarning("Mapping restore needs attention", event["message"], parent=self.root)
                continue
            if kind == "ports":
                values = [f"{port} — {description}" for port, description in event["ports"]]
                self.port_box.configure(values=values)
                if self.port.get() not in values:
                    self.port.set(values[0] if values else "")
                if not values:
                    self.status.set("No serial ports found. Check the USB data cable, then Refresh.")
            elif kind == "connected":
                self.connected = True
                self.generation = event["generation"]
                self.device.set(f"{event['device']} on {event['port']}")
                self.firmware = event["firmware"]
                self.profile.set(f"Profile: {event['profile']}    Firmware: {event['firmware']}")
                self.connect_button.configure(text="Disconnect", state="normal")
                self.arm_button.configure(state="normal")
                self.status.set("Connected in preview. Enable desktop controls when ready.")
            elif kind == "armed":
                if self.want_armed.get() and self.connected:
                    try:
                        self.actions.set_enabled(True)
                    except OSError as exc:
                        self.stop_output()
                        self.worker.submit("disarm")
                        self.status.set(str(exc))
                    else:
                        self.status.set("Desktop controls ON. Turn the knob or press A–D.")
                        self.write_log(f"Original profile backup: {event['backup']}")
                else:
                    self.worker.submit("disarm")
                self.arm_button.configure(state="normal")
                self.connect_button.configure(state="normal")
            elif kind in ("disarmed", "restored"):
                self.stop_output()
                self.status.set(event["message"])
                if kind == "restored":
                    self.arm_button.configure(state="normal" if self.connected else "disabled")
                    self.connect_button.configure(state="normal")
            elif kind == "disconnected":
                self.stop_output()
                self.connected = False
                self.device.set("No device connected")
                self.connect_button.configure(text="Connect", state="normal")
                self.arm_button.configure(state="disabled")
                self.status.set(event["message"])
            elif kind == "error":
                self.stop_output()
                self.status.set(event["message"])
                self.write_log(event["message"])
                self.connect_button.configure(state="normal")
            elif kind == "profile":
                self.write_log(f"Current profile: {event['name']}")
                self.profile.set(f"Profile: {event['name']}    Firmware: {self.firmware}")
            elif kind == "input" and event["generation"] == self.generation:
                self.handle_input(event["action"], event["value"], armed=event["armed"])
        self.root.after(50, self.poll)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.stop_output()
        self.connect_button.configure(state="disabled")
        self.arm_button.configure(state="disabled")
        self.status.set("Closing: restoring the original mappings before releasing the serial port…")
        self.worker.submit("close")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-test", action="store_true", help="Construct and close the UI without enumerating or connecting devices")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports without opening them")
    args = parser.parse_args()
    if args.list_ports:
        try:
            for port, description in list_ports():
                print(f"{port}: {description}")
        except RuntimeError as exc:
            parser.exit(1, f"{exc}\n")
        return
    root = tk.Tk()
    if args.smoke_test:
        root.withdraw()
    app = DesktopDemo(root, refresh=not args.smoke_test)
    if args.smoke_test:
        root.update_idletasks()
        root.update()
        app.close()
        root.after(5000, root.quit)
    root.mainloop()
    if args.smoke_test:
        if app.worker.thread.is_alive():
            raise RuntimeError("UI smoke test failed: worker did not close")
        print("UI smoke test passed; no device opened or desktop input sent.")


if __name__ == "__main__":
    main()
