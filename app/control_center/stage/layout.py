"""Units, k, the stage and the monitor (DESKTOP_STAGE §0.3, §18).

- unit: one px of the prototype's 1280 × 720 reference stage;
- ``k = min(W / 1280, H / 720)`` of the chosen monitor in physical px (``layout_for``, CR:221-229);
- the stage: the 1280 × 720-unit box centred on the monitor;
- ``wide``: ``W / k > 1281`` (BS ``wide = SW > 1280``): the 32:9 tables;
- rest pixels: every rest position and size is ``round(units × k)`` physical px (RF0 §3 rule 12).
On the G93SC (5120 × 1440): k = 2, the stage is 2560 × 1440 px at x 1280-3840, wide.
"""
from __future__ import annotations


class StageLayout:
    __slots__ = ("x", "y", "W", "H", "k", "sx0", "sy0", "wide")

    def __init__(self, rect):
        """``rect`` = (left, top, right, bottom) of the monitor (rcMonitor), physical px."""
        l, t, r, b = (int(v) for v in rect)
        self.x, self.y = l, t
        self.W, self.H = r - l, b - t
        if self.W <= 0 or self.H <= 0:
            raise ValueError("empty monitor rect")
        self.k = min(self.W / 1280.0, self.H / 720.0)
        self.sx0 = (self.W - 1280.0 * self.k) / 2.0
        self.sy0 = (self.H - 720.0 * self.k) / 2.0
        self.wide = self.W / self.k > 1281.0

    def u(self, units: float) -> int:
        """A size in whole physical px."""
        return int(round(units * self.k))

    def px(self, x_units: float, y_units: float):
        """A stage point (units) in client px of a monitor-sized host, rounded to whole px."""
        return int(round(self.sx0 + x_units * self.k)), int(round(self.sy0 + y_units * self.k))

    def rect(self, x_units, y_units, w_units, h_units):
        """A stage rect in client px (left, top, right, bottom)."""
        x, y = self.px(x_units, y_units)
        return x, y, x + self.u(w_units), y + self.u(h_units)

    @property
    def monitor(self):
        """(x, y, w, h) for SetWindowPos."""
        return self.x, self.y, self.W, self.H

    def describe(self) -> dict:
        return {"W": self.W, "H": self.H, "k": round(self.k, 6), "wide": self.wide,
                "stage_origin": [round(self.sx0, 2), round(self.sy0, 2)]}
