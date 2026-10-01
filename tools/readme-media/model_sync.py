"""Check that lcd/haptic_trace.cpp carries the harness's knob model verbatim.

Why: the rotor model `struct Knob` (a rigid rotor, the gimbal motor's Kt / R / back-EMF, the FOC loop's detent
counting, the rest gate) lives in work/lcd-preview/haptic_fx_tests.cpp, which another session owns and which this
media pipeline must never edit. haptic-trace needs the same model so the README's torque panel shows what the
firmware tests show, so the struct is COPIED into lcd/haptic_trace.cpp between the markers
"===== BEGIN verbatim copy" / "===== END verbatim copy". A copy drifts; this check fails loudly when it does, so
the lead refreshes the copy (re-splice the harness's "struct Knob {" .. "};" block) before rendering.

Usage:
  python model_sync.py <harness haptic_fx_tests.cpp> <lcd/haptic_trace.cpp>
Exit 0 when the two struct texts are identical, 1 with a unified diff when they differ, 2 when a struct is missing.
"""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def knob_struct(text: str) -> tuple[str, int, int] | None:
    """The text of `struct Knob { ... };` (the closing `};` is the first one at column 0 after the opener), with its
    1-based first and last line numbers."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "struct Knob {":
            for j in range(i + 1, len(lines)):
                if lines[j].rstrip() == "};":
                    return "\n".join(lines[i:j + 1]), i + 1, j + 1
            return None
    return None


def check_model_sync(harness_cpp_path, trace_cpp_path) -> int:
    harness = Path(harness_cpp_path).read_text(encoding="utf-8")
    trace = Path(trace_cpp_path).read_text(encoding="utf-8")
    a, b = knob_struct(harness), knob_struct(trace)
    if a is None:
        print(f"model_sync: no 'struct Knob {{' .. '}};' in {harness_cpp_path}", file=sys.stderr)
        return 2
    if b is None:
        print(f"model_sync: no 'struct Knob {{' .. '}};' in {trace_cpp_path}", file=sys.stderr)
        return 2
    if a[0] == b[0]:
        print(f"model_sync: struct Knob identical ({a[2] - a[1] + 1} lines; harness {a[1]}-{a[2]}, copy {b[1]}-{b[2]})")
        return 0
    print(f"model_sync: struct Knob DIFFERS (harness {a[1]}-{a[2]} vs copy {b[1]}-{b[2]}); re-splice the copy:", file=sys.stderr)
    for line in difflib.unified_diff(a[0].splitlines(), b[0].splitlines(), fromfile=str(harness_cpp_path),
                                     tofile=str(trace_cpp_path), lineterm=""):
        print(line, file=sys.stderr)
    return 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    return check_model_sync(argv[0], argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
