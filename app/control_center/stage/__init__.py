"""The DirectComposition stage engine (DESKTOP_STAGE K4 §2-§6 and §19, with the [G1] notes).

WP7a stage core: the reusable engine that the music scenes (WP8, ``scenes``) and the picker's GPU
chrome (WP7c, RF0 step 3; lead ruling R-h; CAROUSEL.md §12.4) build on. The one module outside this
package that imports it is the wiring point, ``standalone.py`` (K4 §4.1): it starts the stage
(``scenes.start_music_stage``) and installs the picker's chrome (``picker_chrome.install()``) before
the WindowsAdapter exists. The carousel modules never name this package; they receive the chrome's
factory through ``carousel.install_gpu_chrome``.

Modules (pure unless marked Windows):
- ``curves``       CSS curves fitted as piecewise cubics; the analytic twin with steps (§4.6.2-§4.6.4);
                   the resumable idle warm-up of the segment tables (``Prewarmer``).
- ``motion_table`` every App A tuple (H3).
- ``clock``        the one clock: ticks in timeFrequency, t0 conversion, the t1 rule (§0.6, G1-6, G1-8).
- ``com``          COM structs, GUIDs, the vtable slot table with call styles (§4.7.1, G1-1).
- ``win32``        (Windows) flat exports.
- ``backend``      the COM seam: ``NativeBackend`` (Windows) and the recording ``FakeBackend``.
- ``tree``         visual tree helpers and animatable properties (§4.4, §4.6.6).
- ``animation``    the per-event builder: one Commit, retargets from the twin, holds and legs
                   anchored to t0, call cutting (§4.6.4-§4.6.7, G1-4, G1-7).
- ``surfaces``     prepared surfaces: premultiplied uploads, the per-wake budget, shared solids
                   (G1-9), fixed shadow layers (§4.5, §7.3).
- ``blur``         the snapshot blur recipes per surface (§12, App B) and the ambient build.
- ``capture``      the ``NanoD-stage-capture`` worker (§2.6, §4.9).
- ``frames``       FrameStats (§6.1-§6.3, with ``cpu_pct_one_core`` and the ``NANOD_FPS_HUD`` sprite
                   drawn by ``engine``), the compositor statistics harvest (G1-1, G1-3), the
                   compositor-clock wait with its sleeping-display fallback (G1-2) and the
                   pacer for Python-stepped surfaces (§5).
- ``host``         host window roles: click-eating (0x08200088) and click-through; the input
                   contract (§3), NOACTIVATE show rules, capture exclusion, system notifications.
- ``device``       (Windows) D3D11 + DirectComposition device creation, loss and lifetime (§4.2, §4.3).
- ``presenter``    the Tk-side presenter API (§2.3) and the scene protocol.
- ``layout``       units, k, the stage and the 32:9 rule (§0.3, §18).
- ``engine``       ``StageCore`` (t1, batches, commits, episodes, boost, harvest), ``StageEngine``
                   (open/close sequences, events, device loss and lifetime) and ``StageThread``
                   (the ``NanoD-stage`` Win32 loop) (§4.1-§4.3, §4.9, §15).
- ``proof``        measurement helpers for supervised proofs: pickup classes, the quiet baseline,
                   the pixel witness, the P9 history probe (§19; G1 report §6 item 11).
- ``probe_scene``  a synthetic explorer-like scene for the self-test, the bench and the supervised check.
- ``bench``        the headless per-detent build bench (H5).
- ``selftest``     the headless self-test (P0-style).
- ``picker_chrome``   the window picker's chrome on DirectComposition (step 3, K4 §9.10): the tree, the
                      mirror of the carousel machine's tweens, uploads, the device's lifetime, and
                      ``install()`` / ``factory`` for the wiring point.
- ``picker_device``   (Windows) the chrome's native device in two halves, so a knob touch never
                      holds ``NanoD-carousel`` (``prepare`` on a worker, ``adopt``, ``discard``; WP7c-R6).
- ``picker_testing``  the headless rigs, fakes and the reference renderer with clips (tests, benches).
- ``picker_bench``    the picker's per-frame benches (H5; R-h's targets).
- ``picker_selftest`` the stage self-test with the scenes, extended with the picker's checks.
- ``scenes``       (subpackage) the explorer and Up next (WP8), their art workers and tools.

The tools run by path from the project folder, never ``-m`` under ``-I`` (neither the working
directory nor the script's folder is on ``sys.path`` then; each tool puts the project root there):

    .venv\\Scripts\\python.exe -I control_center\\stage\\selftest.py [--json PATH] [--quick]
    .venv\\Scripts\\python.exe -I control_center\\stage\\bench.py [--device native|fake] [--table 32:9|16:9]
    .venv\\Scripts\\python.exe -I control_center\\stage\\picker_selftest.py [--picker-only]
    .venv\\Scripts\\python.exe -I control_center\\stage\\picker_bench.py [--ratio both] [--dwm]
"""
