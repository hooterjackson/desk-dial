"""Shared r3 fixtures (Desk Dial r3 release 1: spaces navigation + Home Assistant Lights).

Headless and offline: the controller on the cc5 fake clock with `spaces` on, and the
SimulatedHomeAssistant driven synchronously through the controller's effects. Never a port, a
socket to a real Home Assistant, a window or the credential store.
"""
import json

from cc5_support import Fixture, queue_state  # noqa: F401  (re-exported)
from control_center import device
from control_center.simulation import SimControls, SimulatedHomeAssistant

CAPS_V6 = {"controlCenter": True, "presentation": 6, "glyphs": "latin-ext-a"}
CAPS_V5 = {"controlCenter": True, "presentation": 5, "glyphs": "latin-ext-a"}


class R3Fixture(Fixture):
    """A presentation-6 knob on the launcher, a SimulatedHomeAssistant with the prototype's scenes."""

    def setUp(self):
        super().setUp()
        self.controls = SimControls()
        self.ha = SimulatedHomeAssistant(self.controls, clock=self.clock, sleep=self.clock.advance)
        self.c.set_spaces(True)          # what the runtime does for a presentation-6 knob
        self.c._reenter("r3 test")       # no hardware: every control is ready at once (cc5 Fixture)
        self.c.lights_state(self.ha.read_state())
        self.c.drain()

    # -------------------------------------------------------------- the HA lane, synchronously
    def serve(self, effects=None):
        """Answer every lights effect with the simulator (the runtime's `nanod-home` lane)."""
        effects = self.c.drain() if effects is None else effects
        rest = []
        for effect in effects:
            kind = effect["kind"]
            try:
                if kind == "lights_read":
                    self.c.complete(effect["request"], self.ha.read_state())
                elif kind == "lights_set":
                    intent = self.c.lights_intent()
                    from control_center.runtime import _call
                    self.c.complete(effect["request"], _call(self.ha.set_light, bri=intent.get("bri"),
                                                             kelvin=intent.get("kelvin"), on_bri=effect.get("on_bri"),
                                                             targets=effect.get("targets"),   # r3.1: the on lights
                                                             transition=effect.get("transition")))
                elif kind == "lights_power":
                    self.c.complete(effect["request"], self.ha.power(effect["on"]))
                elif kind == "scene_run":
                    self.c.complete(effect["request"], self.ha.run_scene(effect["entity_id"]))
                else:
                    if kind == "device_enter":
                        self.c.device_ready(effect["control"]["id"])
                    rest.append(effect)
            except Exception as exc:
                from control_center.runtime import failure
                self.c.complete(effect["request"], None, failure(exc, op=kind))
        return rest

    def lights(self):
        self.press(2)
        self.serve()

    def wire(self, caps=CAPS_V6):
        """The frame exactly as the bridge would send it (validated; raises on a contract error)."""
        return device._frame({"id": self.c.control_id, **self.c.frame()}, caps)

    def dumps(self, caps=CAPS_V6):
        return json.dumps(self.wire(caps), ensure_ascii=False, sort_keys=True)
