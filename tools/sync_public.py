#!/usr/bin/env python3
"""Copy the Desk Dial release sources into the public repository through an explicit allow-list.

Nothing reaches the public tree unless a rule below names it: per destination (firmware/, app/,
harness/, tools/ and a few single files) the script lists the files and globs to take from the
private source trees. Everything else stays private. There is no "copy everything, then exclude".

    python sync_public.py --dry-run            plan only: counts of copies, rewrites and deletions,
                                               plus the privacy gate over the planned content
    python sync_public.py --apply              write the plan into the public tree, then gate again
    python sync_public.py --check              exit 1 when the public tree differs from the plan

Roots (arguments win over environment variables, which win over the defaults):
    --private-root / NANOD_PRIVATE_ROOT   the folder holding work/ and outputs/ (default: the parent
                                          of this script's folder when that layout is found there)
    --public-root  / NANOD_PUBLIC_ROOT    the public repository (default: <private root>/publish/desk-dial)
    --scrub-map    / NANOD_SCRUB_MAP      the private rewrite map, a JSON file kept OUTSIDE the
                                          repository (default: <private root>/work/audit/private/scrub-map.json)
    --terms        / NANOD_SCRUB_TERMS    the private term list for the gate (default: terms.txt beside the map)
    --scrub-check  / NANOD_SCRUB_CHECK    scrub_check.py (default: <private root>/work/audit/tools/scrub_check.py)

Order of work:
  1. select: git-tracked files of each source that match an INCLUDE glob and no DENY glob (a file
     named literally in an INCLUDE list is taken even when untracked). Fixtures denied as third-party
     art take the tests that read them along ("excluded with its test").
  2. rewrite every text file: workspace paths, the private layout -> public layout, path arithmetic,
     then the private map (names, titles, addresses, ids). Byte-exact paths (app/profiles/) are copied
     byte for byte and never rewritten.
  3. gate: scrub_check's scanner runs over every planned text file with the private terms. A hit is
     tolerated only when the matched text is a known public placeholder (ALLOWED_* below). The
     script refuses to write anything (--apply) or reports failure (--dry-run) on any other hit.
     Matched text is never printed: rows are file:line [class].
  4. apply: write changed files, delete stale allow-listed files (allowed by a rule, but the source
     is gone) and, only with --prune-orphans, public files no rule produces. README-owned paths
     (PROTECTED) are never written or deleted. Then the gate runs again over the written tree.

The private values themselves live only in the scrub map (outside the repository); this file holds
rules and public placeholders only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# ---------------------------------------------------------------------------------------------------------
# Layout

HERE = Path(__file__).resolve()

# README session's paths: never created, edited or deleted by the sync.
PROTECTED = [
    "README.md",
    "docs/features/**",
    "docs/setup/**",
    "docs/faq.md",
    "docs/privacy.md",
    "docs/media/**",
    "tools/readme-media/**",
    ".github/ISSUE_TEMPLATE/**",
]

# Never published, whatever a rule says (checked on every source path and every public path).
GLOBAL_DENY = [
    "**/backups/**", "**/diagnostics/**", "**/local/**", "**/desktop-build*/**", "**/desktop-dist*/**",
    "**/.pio/**", "**/.pio-core/**", "**/.venv/**", "**/venv/**", "**/__pycache__/**", "**/*.pyc",
    "**/*.log", "**/*.jsonl", "**/*.superseded-*", "**/audit/**", "**/*.bin", "**/*.elf", "**/*.map",
    "**/*.zip", "**/firmware/manifest*.json", "**/firmware/**/manifest*.json", "**/settings.json", "**/credentials*.bin", "**/*.p8", "**/*.pem",
    "**/*.key", "**/.env", "**/.env.*",
    # prompt, hand-off, memory and plan files
    "**/DEEP_DIVE_PROMPT.md", "**/README_PROMPT.md", "**/APP_PROFILES_PROMPT.md",
    "**/CLAUDE_CODE_HANDOFF.md", "**/CLAUDE.md", "**/*_PROMPT.md", "**/MEMORY.md", "**/memory/**",
    "**/plans/**", "**/.cla" "ude/**",
]

# Third-party art (D-ART): never published. Tests that read one of these files are excluded with it.
ART_DENY = [
    "**/covers/**", "**/assets/apps/**",
    # rendered sheets and screenshots that show real album covers or third-party app logos
    "design-reference/r3-navigator/*.png", "design-reference/r3-navigator-prototype/*.png",
    "design-reference/r3-navigator-sheet.png", "design-reference/r4-motion-tour-sheet.png",
    "tests/goldens/navigator/**",                 # real cover rendered into the golden
    "tests/goldens/music/**",                     # real titles rendered into the goldens (regenerate first)
]   # plus the scrub map's "art_deny" globs (fixtures named after private things)

# Files that count as tests for the "excluded with its test" cascade.
TEST_GLOBS = ["tests/test_*.py", "tests/js/*.cjs", "*_tests.py", "*_tests.cpp", "*_tests.cjs"]


@dataclass
class Spec:
    dest: str                       # public folder ("firmware") or "" for root single files
    repo: str                       # private git repository, relative to the private root
    sub: str = ""                   # folder inside the repository ("lcd-preview")
    include: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    byte_exact: list[str] = field(default_factory=list)
    renames: dict[str, str] = field(default_factory=dict)   # source rel -> public path (repo-relative)


SPECS = [
    Spec(
        dest="firmware", repo="firmware",
        include=[
            "platformio.ini", "boards/**", "include/**", "src/**", "lib/**", "scripts/**", "sounds/**",
            "test/**", ".gitignore", ".gitmodules", ".vscode/tasks.json",
            # upstream docs
            "README.md", "api.md", "communications.md", "hid.md", "mapping.md", "midi.md", "midi.png",
            # contracts (ALIVE_R2_DRAFT.md and PRESENTATION_V4.md carry their own superseded/frozen banner)
            "CONTROL_CENTER.md", "ALIVE.md", "ALIVE_R2_DRAFT.md", "PRESENTATION_V4.md", "PRESENTATION_V5.md",
            "V5_VOCABULARY.md", "ARTWORK2.md", "HAPTICS.md", "MOTION.md", "APP_PROFILES.md",
        ],
        deny=[".vscode/settings.json", ".vscode/extensions.json", "compile_commands.json", "**/*.d"],
    ),
    Spec(
        dest="app", repo="app",
        include=[
            "standalone.py", "app.py", "protocol.py", "session.py", "setup_music.py", "windows_actions.py",
            "device_inventory.py", "legacy_app.py", "render_previews.py",
            "requirements.txt", "requirements-desktop.txt", "desktop-version.txt",
            "Build-Desktop.ps1", "Install-Desktop.ps1", "Install-UserData.ps1", "Uninstall-Desktop.ps1",
            "Setup.cmd", "Launch.cmd", "Launch-Live.cmd",
            ".gitignore", ".gitattributes",
            # user / maker specs
            "README.md", "DESKTOP.md", "DESKTOP_STAGE.md", "CONTROL_CENTER_V5.md", "ONSHAPE.md", "CAROUSEL.md",
            "FLOATING_KNOB.md", "APP_ICON.md",
            "control_center/**",
            "profiles/**", "tools/profiles/**",
            "assets/**",
            "tests/**",
            # design reference without third-party covers and app logos (ART_DENY); prompts stay private
            "design-reference/**",
        ],
        deny=[
            "design-reference/**/*prompt*",              # design-tool prompts
            "design-reference/r3-feedback-for-claude-design.md",
            "design-reference/ui-v2-analysis/live-checks.md",
            "design-reference/ui-v2-analysis/like-star-mismatch.md",
            "design-reference/ui-v2-analysis/check-favourite-playlists.md",
            "tests/fixtures/alive_oracle.json",          # generated (node tests/js/alive_oracle.cjs)
            "design-reference/app-profiles-contact-sheet.png",   # third-party app logos; the harness tests
                                                         # that write it stay (they do not read it)
            "tests/test_tl_bug_001_published_tools.py",  # compares the private tools with a public checkout
            # read the author's private records or audit tools (work/audit, firmware/RECOVERY.md)
            "tests/test_tl_bug_004_recovery_doc.py", "tests/test_tl_bug_006_recovery_doc.py",
            "tests/test_tl_bug_013_ledger_note.py", "tests/test_hn_res_001_sampler_ctx_rate.py",
            "tests/test_fw_pub_003_release_strings.py", "tests/test_fw_perf_010_lcd_bench_window.py",
            # compare renders that show real covers or titles
            "tests/test_dd_des_009_navigator_goldens.py", "tests/test_render_music.py",
            "tests/test_r3_navigator_scene.py",
            "firmware/**",                                # release assets and the author's install records
            "ACCEPTANCE.md", "design-qa.md", "LEGACY-DEMO.md",
            "previews/**", "vendor/**", "logs/**", "build/**", "dist/**",
        ],
        byte_exact=["profiles/**"],
        renames={".github/workflows/karl-profiles.yml": ".github/workflows/karl-profiles.yml"},
    ),
    Spec(
        dest="harness", repo="work", sub="lcd-preview",
        include=[
            "CMakeLists.txt", "build.py", "build.ps1", "lv_conf.h", "README.md",
            "*.cpp", "*.c", "*.h", "*.py", "*.cjs",
            "tjpgd_shim/**", "artwork2/**", "fixtures/**", "goldens/**",
            "perf/baseline-cc5.7.json",
            "cc54-handoff/regression-checks-cc54.json", "cc54-handoff/lvgl-heap.json",
            "media_store_traces.json", "cc54_copy.json",
        ],
        deny=[
            "r3_sheet.py",                                # one-off author contact sheet (the README names the others)
            "rendered/**", "build/**", "build-*/**", "cc3*/**", "cc4-*/**", "cc5-*/**", "r3-handoff/**",
            "quiet-listening/**", "alive_sequences.json", "light_pixels.json",   # generated by the tests
            "**/*.obj", "**/*.exe", "**/*.pdb", "**/*.ilk", "**/*.ppm",
        ],
    ),
    Spec(
        dest="tools", repo="work",
        include=[
            "nanod_cc5_tooling.py", "build_nanod_cc5.py", "package_nanod_cc5.py", "prepare_nanod_cc5_install.py",
            "install_nanod_cc5.py", "finalize_nanod_cc5.py", "rollback_nanod_cc5.py", "backup_nanod_cc5.py",
            "check_nanod_cc5.py", "check_nanod_cc5_lease.py", "check_nanod_cc5_look.py", "check_desktop_v7.py",
            "compare_nanod_inventory.py", "inspect_nanod_header.py", "nanod_alive_tour.py",
            "nanod_device_checks.py", "nanod_enter_bootloader_v2.py", "nanod_lease_check.py",
            "nanod_live_readiness.py", "probe_knob_frames.py", "probe_nanod.py",
            "run_no_tk.py", "sync_public.py", "release_nanod_cc5.py", "nanod_register_range_check.py",
            "lcd_bench_frames.json",
            "stage_checks/*.py",
        ],
    ),
]

# Public placeholders the gate tolerates (fictional or documentation values; never a real one).
ALLOWED_MAC = {"AA:BB:CC:DD:EE:FF", "00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF", "02:00:00:00:00:01",
               "11:22:33:44:55:66"}
ALLOWED_MAC_FAMILY = re.compile(r"^12:34:56:78:[0-9A-F]{2}:[0-9A-F]{2}$")   # the placeholder knob and its neighbours
ALLOWED_IPV4_PRIVATE = re.compile(
    r"^(?:192\.168\.1\.(?:5\d|9|40|99)|192\.168\.0\.\d{1,3}|192\.168\.50\.\d{1,3}|10\.0\.0\.\d{1,3}|"
    r"172\.20\.\d{1,3}\.\d{1,3}|127\.\d+\.\d+\.\d+|\d+\.\d+\.0\.0|\d+\.0\.0\.0)$")
# Documentation ranges (RFC 5737), loopback, any/broadcast and well-known public resolvers.
ALLOWED_IPV4_REVIEW = re.compile(
    r"^(?:192\.0\.2\.\d+|198\.51\.100\.\d+|203\.0\.113\.\d+|0\.0\.0\.0|255\.255\.255\.\d+|"
    r"127\.\d+\.\d+\.\d+|1\.1\.1\.1|8\.8\.8\.8|8\.8\.4\.4|1\.2\.3\.4|\d+\.\d+\.0\.0|\d+\.0\.0\.0)$")
ALLOWED_EMAIL = re.compile(r"(?:@(?:[\w-]+\.)*(?:example\.(?:com|org|net|invalid)|[\w-]+\.(?:invalid|test|example))$|"
                           r"^(?:user|pw|someone|listener|name|test)@)", re.IGNORECASE)
ALLOWED_HOME = re.compile(
    r"^(?:[A-Za-z]:[\\/]Users[\\/](?:someone|Public|Default|<user>|<you>|you|USERNAME|user|name)|"
    r"/Us" r"ers/(?:someone|<user>|you|user|name)|%USER" r"PROFILE%)$", re.IGNORECASE)
# The token classes stay quiet for obvious test values (TEST-..., fake, placeholder, all-zero ids).
ALLOWED_TOKENISH = re.compile(r"(?i)(test|fake|dummy|example|placeholder|sample|bench|demo|x{4,}|0{8,}|redacted|<)")
# token= values that are vocabulary, not secrets: lower-case words (haptic tokens, icon names, test labels).
TOKEN_VALUE = re.compile(r"""[:=]\s*["']([^"']*)""")
VOCAB_VALUE = re.compile(r"^[a-z][a-z0-9 ._-]{0,31}$")
SHORT_SONOS = re.compile(r"^RINCON_(?:\d{1,3}|0{6,}\d*|[A-Z]*TEST\w*)$")

# ---------------------------------------------------------------------------------------------------------
# Rewrite rules that hold no private value (layout and path arithmetic)

SEP = r"[\\/]+"
# The workspace root on the author's machine, any user name, either slash form, optional escaping.
_DOCS = "Docu" + "ments"
WORKSPACE_RE = (r"[A-Za-z]:" + SEP + "Users" + SEP + r"[^\\/\s'\"`]+" + SEP + _DOCS + SEP + "Codex" + SEP
                + r"2026-09-21" + SEP + r"ex(?=[\\/'\"`\s]|$)")
PIO_KNOB_RE = r"[A-Za-z]:" + SEP + "Users" + SEP + r"[^\\/\s'\"`]+" + SEP + _DOCS + SEP + "Codex" + SEP + "pio-knob"
APPDATA_RE = r"[A-Za-z]:" + SEP + "Users" + SEP + r"[^\\/\s'\"`]+" + SEP + "AppData" + SEP + "Local(?=[\\/])"
SCRATCH = "scr" "atch" "pad"
OTHER_HOME_RE = r"(?<![\w%])([A-Za-z]:" + SEP + "Users" + SEP + r")(?!someone\b|Public\b|Default\b|<)[A-Za-z][\w.-]*"


def _sub_sep(m: re.Match, new: str) -> str:
    """Replace keeping the slash style of the match (backslash, doubled backslash or slash)."""
    s = m.group(0)
    if "\\\\" in s:
        return new.replace("/", "\\\\")
    if "\\" in s:
        return new.replace("/", "\\")
    return new


@dataclass
class Rule:
    name: str
    pattern: re.Pattern
    repl: object                      # str or callable(match) -> str
    only: list[str] | None = None     # public path globs the rule applies to (None: every text file)
    skip: list[str] | None = None     # public path globs it never touches


def R(name, pattern, repl, only=None, skip=None, flags=0):
    return Rule(name, re.compile(pattern, flags), repl, only, skip)


# Order matters: workspace-absolute paths first, then the layout prefixes, then path arithmetic.
LAYOUT_RULES: list[Rule] = [
    R("workspace:outputs-app", WORKSPACE_RE + SEP + "outputs" + SEP + "nanod-desktop-demo",
      lambda m: _sub_sep(m, "<repo>/app")),
    R("workspace:firmware", WORKSPACE_RE + SEP + "work" + SEP + "NanoD_RatchetH1", lambda m: _sub_sep(m, "<repo>/firmware")),
    R("workspace:harness", WORKSPACE_RE + SEP + "work" + SEP + "lcd-preview", lambda m: _sub_sep(m, "<repo>/harness")),
    R("workspace:tools", WORKSPACE_RE + SEP + "work(?=[\\\\/'\"`\\s]|$)", lambda m: _sub_sep(m, "<repo>/tools")),
    R("workspace:root", WORKSPACE_RE, "<repo>"),
    R("pio-core", PIO_KNOB_RE, "<pio-core>"),
    R("session-temp", r"(?:%LOCALAPPDATA%|[A-Za-z]:" + SEP + "Users" + SEP + r"[^\\/\s'\"`]+" + SEP + "AppData" + SEP
      + "Local)" + SEP + "Temp" + SEP + "cla" "ude" + SEP + r"[^\s`'\")]*", "<scratch>"),
    R("private-plan", r"[A-Za-z]:" + SEP + "Users" + SEP + r"[^\\/\s'\"`]+" + SEP + r"\.cla" r"ude" + SEP + r"[^\s`'\")]*",
      "<the author's private plan>"),
    R("scratch-path", r"(?<![\w<])(?:\.\.\.?|…)?[\\/]?" + SCRATCH + r"(?=[\\/])", "<scratch>"),
    R("scratch-word", r"\b(?:the )?(?:session )?" + SCRATCH + r"\b", "a scratch folder"),
    R("appdata", APPDATA_RE, lambda m: "%LOCALAPPDATA%"),
    R("squareline", r"/Us" r"ers/[^/\s]+/SquareLine", "/Us" "ers/<user>/SquareLine", only=["firmware/src/fonts/*.c"]),
    R("home", OTHER_HOME_RE, lambda m: m.group(1) + "someone"),
    R("sharp-bundle", r"'[^'\n]*node_modules[\\/]+sharp'", "process.env.SHARP_MODULE_PATH || 'sharp'",
      only=["harness/*.cjs"]),
    R("runs-as", r"\bruns as [A-Z][a-z]+\b(?= \()", "runs as the signed-in user", only=["app/*.md"]),
    # relative layout prefixes, both slash forms, optional doubled backslashes
    R("prefix:app", r"(?<![\w.-])(?:\.[\\/]+)?outputs(\\\\|[\\/])nanod-desktop-demo(?![\w-])",
      lambda m: "app", skip=["app/tests/test_alive_wire.py"]),
    R("prefix:firmware", r"(?<![\w.-])work(\\\\|[\\/])NanoD_RatchetH1(?![\w-])", "firmware"),
    R("prefix:harness", r"(?<![\w.-])work(\\\\|[\\/])lcd-preview(?![\w-])", "harness"),
    R("prefix:stage-checks", r"(?<![\w.-])work(\\\\|[\\/])stage_checks(?![\w-])",
      lambda m: "tools" + m.group(1) + "stage_checks"),
    R("prefix:tool-venvs", r"(?<![\w.-])work(\\\\|[\\/])(nanod-flash-venv|nanod-pio-venv|platformio-core)",
      lambda m: "tools" + m.group(1) + m.group(2)),
    R("prefix:tool-scripts", r"(?<![\w.-])work(\\\\|[\\/])(\w+\.py)\b", lambda m: "tools" + m.group(1) + m.group(2)),
    R("prefix:cd-app", r"\bcd outputs(\\\\|[\\/])nanod-desktop-demo\b", "cd app"),
    # path arithmetic (the source layout puts work/ and outputs/ one level deeper than the public repo)
    R("arith:harness-app", r"\b(root|ROOT|work|WORK)\.parents\[1\] / (['\"])outputs\2 / \2nanod-desktop-demo\2",
      lambda m: f"{m.group(1)}.parent / {m.group(2)}app{m.group(2)}", only=["harness/**"]),
    R("arith:harness-app2", r"\b(work|WORK)\.parent / (['\"])outputs\2 / \2nanod-desktop-demo\2",
      lambda m: f"{m.group(1)} / {m.group(2)}app{m.group(2)}", only=["harness/**"]),
    R("arith:harness-firmware", r"(['\"])NanoD_RatchetH1\1", lambda m: f"{m.group(1)}firmware{m.group(1)}",
      only=["harness/**"]),
    R("arith:harness-tool", r"\b(root|ROOT)\.parent / (['\"])(\w+\.py)\2",
      lambda m: f"{m.group(1)}.parent / {m.group(2)}tools{m.group(2)} / {m.group(2)}{m.group(3)}{m.group(2)}",
      only=["harness/**"]),
    R("arith:harness-venv", r"\$PSScriptRoot/\.\./\.\app/", "$PSScriptRoot/../app/",
      only=["harness/*.ps1"]),
    R("arith:tools-app", r"(['\"])app\1", lambda m: f"{m.group(1)}app{m.group(1)}",
      only=["tools/**"]),
    R("arith:tools-app2", r"(['\"])outputs\1, \1nanod-desktop-demo\1", lambda m: f"{m.group(1)}app{m.group(1)}",
      only=["tools/**"]),
    R("arith:tools-app3", r"(['\"])outputs\1 / \1nanod-desktop-demo\1", lambda m: f"{m.group(1)}app{m.group(1)}",
      only=["tools/**"]),
    R("arith:tools-firmware", r"\bWORK / (['\"])NanoD_RatchetH1\1", lambda m: f"ROOT / {m.group(1)}firmware{m.group(1)}",
      only=["tools/**"]),
    R("arith:tools-stage", r"\.\.(\\\\|/)\.\.(\\\\|/)work(\\\\|/)stage_checks",
      lambda m: f"..{m.group(1)}tools{m.group(1)}stage_checks", only=["tools/**"]),
    R("arith:harness-workspace", r"^WORKSPACE = WORK\.parent\b", "WORKSPACE = WORK", only=["harness/*.py"], flags=re.M),
    R("arith:harness-workspace2", r"^WORKSPACE = ROOT\.parents\[1\]", "WORKSPACE = ROOT.parent", only=["harness/*.py"],
      flags=re.M),
    R("arith:harness-app3", r"(['\"])outputs\1 / \1nanod-desktop-demo\1", lambda m: f"{m.group(1)}app{m.group(1)}",
      only=["harness/**"]),
    R("arith:harness-cmake", r"\.\./NanoD_RatchetH1\b", "../firmware", only=["harness/**"]),
    R("arith:tools-harness", r"\bWORK / (['\"])lcd-preview\1", lambda m: f"ROOT / {m.group(1)}harness{m.group(1)}",
      only=["tools/**"]),
    R("arith:app-firmware", r"\b(ROOT\.parents\[1\]|parents\[3\]|parents\[2\]) / (['\"])work\2 / \2NanoD_RatchetH1\2",
      lambda m: ("ROOT.parent" if m.group(1).startswith("ROOT") else "parents[2]") + f" / {m.group(2)}firmware{m.group(2)}",
      only=["app/tests/**", "app/tools/**"]),
    R("arith:app-harness", r"\b(ROOT\.parents\[1\]|ROOT\.parent|parents\[3\]) / (['\"])work\2 / \2lcd-preview\2",
      lambda m: ("parents[2]" if m.group(1) == "parents[3]" else "ROOT.parent") + f" / {m.group(2)}harness{m.group(2)}",
      only=["app/tests/**", "app/tools/**"]),
    R("arith:app-tools", r"\bparents\[3\] / (['\"])work\1(?! / \1stage_checks)",
      lambda m: f"parents[2] / {m.group(1)}tools{m.group(1)}", only=["app/tests/**"]),
    R("readme-tools", r"\(work / name\)\.is_file\(\)", "(work / 'tools' / name).is_file()",
      only=["harness/readme_tests.py"]),
    R("karl-workflow", r"\bROOT / (['\"])\.github\1", lambda m: f"ROOT.parent / {m.group(1)}.github{m.group(1)}",
      only=["app/tests/test_karl_profiles_action.py"]),
    R("build-pins-stand-in", r"(['\"])NanoD_RatchetH1\1", lambda m: f"{m.group(1)}firmware{m.group(1)}",
      only=["app/tests/test_hn_bug_003_build_pins.py"]),
    R("handoff-name", r"\bCLAUDE_CODE_HANDOFF\.md\b", "HANDOFF_NOTES.md", only=["harness/**", "app/**"]),
    R("arith:app-stage",r"parents\[3\] / (['\"])work\1 / \1stage_checks\1",
      lambda m: f"parents[2] / {m.group(1)}tools{m.group(1)} / {m.group(1)}stage_checks{m.group(1)}",
      only=["app/tests/**"]),
    R("arith:app-work", r"\bROOT\.parents\[1\] / (['\"])work\1", lambda m: f"ROOT.parent / {m.group(1)}tools{m.group(1)}",
      only=["app/tests/**"]),
    R("arith:app-work-sub", r"\bWORK / (['\"])(lcd-preview|NanoD_RatchetH1)\1",
      lambda m: "WORK.parent / " + m.group(1) + ("harness" if m.group(2) == "lcd-preview" else "firmware") + m.group(1),
      only=["app/tests/**"]),
    # release tooling: the author's pins become environment variables (as the first public port did)
    R("tooling:paths", r'^APP = ROOT / "app"$', 'APP = ROOT / "app"',
      only=["tools/nanod_cc5_tooling.py"], flags=re.M),
    R("tooling:firmware", r'^FIRMWARE_SOURCE = ROOT / "firmware"$', 'FIRMWARE_SOURCE = ROOT / "firmware"',
      only=["tools/nanod_cc5_tooling.py"], flags=re.M),
    R("tooling:pio-core", r'^PIO_CORE = .*$',
      "# PlatformIO core dir (toolchains, packages). NANOD_PIO_CORE overrides the in-repo default (git-ignored).\n"
      'PIO_CORE = Path(os.environ.get("NANOD_PIO_CORE") or ROOT / ".pio-core")',
      only=["tools/nanod_cc5_tooling.py"], flags=re.M),
    R("tooling:chip-mac", r'^CHIP_MAC = "[^"]*".*$',
      "# The ROM port reports the chip MAC as its USB serial number. Set NANOD_CHIP_MAC to your knob's MAC\n"
      "# (esptool flash_id prints it); the placeholder never matches a real chip, so nothing is flashed.\n"
      'CHIP_MAC_PLACEHOLDER = "12:34:56:78:9A:BC"\n'
      'CHIP_MAC = os.environ.get("NANOD_CHIP_MAC", "").strip() or CHIP_MAC_PLACEHOLDER',
      only=["tools/nanod_cc5_tooling.py"], flags=re.M),
    R("tooling:root-comment", r"(ROOT = WORK\.parent)\s+# .*$", r"\1", only=["tools/nanod_cc5_tooling.py"], flags=re.M),
]

# ---------------------------------------------------------------------------------------------------------
# Glob matching ("**" spans folders, "*" and "?" stay inside one name)

_GLOB_CACHE: dict[str, re.Pattern] = {}


def glob_re(pattern: str) -> re.Pattern:
    rx = _GLOB_CACHE.get(pattern)
    if rx is None:
        out, i = "", 0
        while i < len(pattern):
            if pattern.startswith("**/", i):
                out += "(?:.*/)?"
                i += 3
            elif pattern.startswith("**", i):
                out += ".*"
                i += 2
            elif pattern[i] == "*":
                out += "[^/]*"
                i += 1
            elif pattern[i] == "?":
                out += "[^/]"
                i += 1
            else:
                out += re.escape(pattern[i])
                i += 1
        rx = _GLOB_CACHE[pattern] = re.compile(out + r"\Z")
    return rx


def matches(path: str, patterns) -> bool:
    return any(glob_re(p).match(path) for p in patterns or ())


def is_protected(public_path: str) -> bool:
    return matches(public_path, PROTECTED)


# ---------------------------------------------------------------------------------------------------------
# Private rewrite map (outside the repository)

@dataclass
class MapRule:
    pattern: re.Pattern
    replace: str
    case_preserve: bool
    combinable: bool = True    # no backreferences or inline global flags: safe inside one alternation


def _word(find: str) -> str:
    esc = re.escape(find)
    esc = re.sub(r"(?:\\\s|\\ )+", r"\\s+", esc)
    return r"(?<!\w)" + esc + r"(?!\w)"


def _mac_variants(mac: str) -> list[tuple[str, str]]:
    """(regex, replacement-style) for a MAC with colons, dashes or no separator, any case."""
    octets = re.findall(r"[0-9A-Fa-f]{2}", mac)
    return [(r"(?<![0-9A-Fa-f:-])" + sep.join(octets) + r"(?![0-9A-Fa-f])", sep) for sep in (":", "-", "")]


def load_scrub_map(path: Path) -> tuple[list[MapRule], set[str], list[str]]:
    """Return (rules, keep, extra_gate_terms). Never prints a value from the map."""
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    rules: list[MapRule] = []
    extra: list[str] = []
    # Exact values first, longest first (a title before the artist inside it); regex rules after,
    # in file order (they mop up derived forms such as slugs and near-copies of an identifier).
    raw = doc.get("rules", [])
    entries = (sorted((e for e in raw if e.get("match") != "regex"), key=lambda e: -len(e.get("find", "")))
               + [e for e in raw if e.get("match") == "regex"])
    for e in entries:
        find, repl, mode = e["find"], e.get("replace", ""), e.get("match", "word")
        if mode == "mac":
            placeholder = re.findall(r"[0-9A-Fa-f]{2}", repl)
            for rx, sep in _mac_variants(find):
                rules.append(MapRule(re.compile(rx, re.IGNORECASE), sep.join(placeholder), True))
            continue
        if mode == "word":
            rx = re.compile(_word(find), re.IGNORECASE)
        elif mode == "word-cs":
            rx = re.compile(_word(find))
        elif mode == "literal":
            rx = re.compile(re.escape(find))
        elif mode == "literal-ci":
            rx = re.compile(re.escape(find), re.IGNORECASE)
        elif mode == "regex":
            rx = re.compile(find)
            rules.append(MapRule(rx, repl, False, combinable=False))
            continue
        else:
            raise SystemExit(f"sync_public: scrub map rule with unknown match mode {mode!r}")
        rules.append(MapRule(rx, repl, mode in ("word", "literal-ci", "mac")))
        # The same value as a JSON or JS string escape (fixtures write "é"), either hex case.
        if mode in ("word", "word-cs", "literal", "literal-ci") and any(ord(c) > 127 for c in find):
            esc_find = json.dumps(find)[1:-1]
            esc_repl = json.dumps(repl)[1:-1]
            for form in {esc_find, re.sub(r"\\u([0-9a-f]{4})", lambda m: "\\u" + m.group(1).upper(), esc_find)}:
                flags = re.IGNORECASE if mode in ("word", "literal-ci") else 0
                rules.append(MapRule(re.compile(re.escape(form), flags), esc_repl, False))
        if mode in ("word", "word-cs", "literal", "literal-ci") and e.get("gate", True):
            extra.append(find)
    keep = {" ".join(k.split()).casefold() for k in doc.get("keep", [])}
    for g in doc.get("art_deny", []):
        if g not in ART_DENY:
            ART_DENY.append(g)
    return rules, keep, extra


def _case_like(src: str, repl: str) -> str:
    if src.isupper() and any(c.isalpha() for c in src):
        return repl.upper()
    if src[:1].islower() and repl[:1].isupper() and src.lower() == src:
        return repl.lower()
    return repl


def apply_map(text: str, rules: list[MapRule]) -> tuple[str, int]:
    total = 0
    for r in rules:
        if r.case_preserve:
            text, n = r.pattern.subn(lambda m, r=r: _case_like(m.group(0), r.replace), text)
        elif r.combinable:      # an exact value: the replacement is literal text, never a template
            text, n = r.pattern.subn(lambda m, r=r: r.replace, text)
        else:
            text, n = r.pattern.subn(r.replace, text)
        total += n
    return text, total


# ---------------------------------------------------------------------------------------------------------
# Source selection

def git_files(repo: Path, sub: str) -> list[str] | None:
    """Tracked files under repo/sub, relative to sub (posix). None when repo is not a git work tree."""
    try:
        out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z", "--", sub or "."],
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    files = []
    prefix = (sub.rstrip("/") + "/") if sub else ""
    for raw in out.split(b"\0"):
        if not raw:
            continue
        p = raw.decode("utf-8", errors="surrogateescape")
        if prefix and not p.startswith(prefix):
            continue
        files.append(p[len(prefix):])
    return files


def is_text(data: bytes) -> bool:
    if b"\0" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


@dataclass
class Item:
    public: str          # public path, posix, repo-relative
    source: Path
    spec: Spec
    rel: str             # source path relative to repo/sub
    data: bytes = b""
    rewritten: bool = False
    rules_hit: dict[str, int] = field(default_factory=dict)
    private_hits: int = 0


@dataclass
class Plan:
    items: dict[str, Item] = field(default_factory=dict)
    denied: list[tuple[str, str]] = field(default_factory=list)          # (source path, reason)
    excluded_tests: list[tuple[str, str]] = field(default_factory=list)  # (public path, fixture it reads)
    dangling: list[tuple[str, str]] = field(default_factory=list)        # (public path, fixture it names)
    untracked_explicit: list[str] = field(default_factory=list)
    missing_explicit: list[str] = field(default_factory=list)


def literal_names(spec: Spec) -> list[str]:
    return [p for p in spec.include if not any(c in p for c in "*?")]


def select(private_root: Path, specs=SPECS) -> Plan:
    plan = Plan()
    art_names: dict[str, str] = {}
    for spec in specs:
        repo = private_root / spec.repo
        base = repo / spec.sub if spec.sub else repo
        tracked = git_files(repo, spec.sub)
        if tracked is None:
            raise SystemExit(f"sync_public: {spec.repo} is not a git work tree")
        # A file named literally in INCLUDE is taken even when untracked (a deliberate, reviewed choice).
        names = set(tracked)
        for lit in literal_names(spec):
            if lit not in names and (base / lit).is_file():
                names.add(lit)
                plan.untracked_explicit.append(f"{spec.dest}/{lit}")
            elif lit not in names:
                plan.missing_explicit.append(f"{spec.dest}/{lit}")
        for rel in sorted(names):
            if spec.dest == "tools" and "/" in rel and not rel.startswith("stage_checks/"):
                continue   # the tools spec takes top-level work/*.py and stage_checks/ only
            public = spec.renames.get(rel) or (f"{spec.dest}/{rel}" if spec.dest else rel)
            if rel in spec.renames:
                pass
            elif not matches(rel, spec.include):
                continue
            src_label = f"{spec.repo}/{spec.sub + '/' if spec.sub else ''}{rel}"
            if matches(rel, GLOBAL_DENY) or matches(public, GLOBAL_DENY):
                plan.denied.append((src_label, "never-publish"))
                continue
            if matches(rel, ART_DENY):
                plan.denied.append((src_label, "third-party art (D-ART)"))
                pp = PurePosixPath(rel)
                # How code names the file: folder/name, a quoted name, or a long dashed stem.
                for key in (f"{pp.parent.name}/{pp.name}", f"'{pp.name}'", f'"{pp.name}"'):
                    art_names[key] = public
                if len(pp.stem) >= 8 and "-" in pp.stem:
                    art_names[pp.stem] = public
                continue
            if matches(rel, spec.deny):
                plan.denied.append((src_label, "deny rule"))
                continue
            if is_protected(public):
                plan.denied.append((src_label, "README-owned path"))
                continue
            if not (base / rel).is_file():
                continue
            plan.items[public] = Item(public=public, source=base / rel, spec=spec, rel=rel)
    # Excluded with its test: a test that reads a denied art fixture leaves with it; other files
    # that name one are reported as dangling references.
    if art_names:
        rx = re.compile("|".join(re.escape(n) for n in sorted(art_names, key=len, reverse=True)))
        for public, item in list(plan.items.items()):
            data = item.source.read_bytes()
            if not is_text(data):
                continue
            m = rx.search(data.decode("utf-8"))
            if not m:
                continue
            area_rel = public.split("/", 1)[1] if "/" in public else public
            if matches(area_rel, TEST_GLOBS):
                del plan.items[public]
                plan.excluded_tests.append((public, art_names[m.group(0)]))
            else:
                plan.dangling.append((public, art_names[m.group(0)]))
    # A test module that imports an excluded test module leaves too (until nothing changes).
    gone = {PurePosixPath(p).stem for p, _f in plan.excluded_tests}
    gone |= {PurePosixPath(s).stem for s, r in plan.denied if PurePosixPath(s).name.startswith("test_")}
    while gone:
        rx = re.compile(r"^\s*(?:from|import)\s+(" + "|".join(re.escape(g) for g in sorted(gone)) + r")\b", re.M)
        newly = set()
        for public, item in list(plan.items.items()):
            area_rel = public.split("/", 1)[1] if "/" in public else public
            if not matches(area_rel, TEST_GLOBS) or not public.endswith(".py"):
                continue
            m = rx.search(item.source.read_text(encoding="utf-8", errors="replace"))
            if m:
                del plan.items[public]
                plan.excluded_tests.append((public, f"imports {m.group(1)}"))
                newly.add(PurePosixPath(public).stem)
        gone = newly
    return plan


# ---------------------------------------------------------------------------------------------------------
# Rewrite

def rewrite(plan: Plan, map_rules: list[MapRule]) -> None:
    for public, item in plan.items.items():
        data = item.source.read_bytes()
        if matches(item.rel, item.spec.byte_exact) or not is_text(data):
            item.data = data
            continue
        text = data.decode("utf-8")
        new = text
        for rule in LAYOUT_RULES:
            if rule.only and not matches(public, rule.only):
                continue
            if rule.skip and matches(public, rule.skip):
                continue
            new, n = rule.pattern.subn(rule.repl, new)
            if n:
                item.rules_hit[rule.name] = item.rules_hit.get(rule.name, 0) + n
        new, n = apply_map(new, map_rules)
        item.private_hits = n
        item.rewritten = new != text
        item.data = new.encode("utf-8")


# ---------------------------------------------------------------------------------------------------------
# Gate (scrub_check's scanner; matched text is never printed)

def load_scrub_check(path: Path):
    spec = importlib.util.spec_from_file_location("scrub_check_for_sync", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"sync_public: cannot load scrub_check from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def gate_terms(terms_path: Path, keep: set[str], extra: list[str]) -> list[str]:
    terms = []
    if terms_path.is_file():
        terms = [ln.rstrip("\r\n") for ln in terms_path.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    out, seen = [], set()
    for t in terms + extra:
        key = " ".join(t.split()).casefold()
        if key in keep or key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _class_matches(sc, cls: str, line: str) -> list[str]:
    if cls == "mac":
        return [m.group(0) for m in sc.RE_MAC.finditer(line)]
    if cls.startswith("ipv4-"):
        return [m.group(0) for m in sc.RE_QUAD.finditer(line)]
    if cls == "email":
        return [m.group(0) for m in sc.RE_EMAIL.finditer(line)]
    if cls == "home-path":
        return [m.group(0) for m in sc.RE_HOME.finditer(line)]
    if cls == "long-string-review":
        return [m.group(0) for m in sc.RE_LONG.finditer(line)]
    if cls == "serial-review":
        return [m.group(0) for m in sc.RE_SERIAL.finditer(line)]
    for name, rx in sc.TOKEN_PATTERNS:
        if name == cls:
            return [m.group(0) for m in rx.finditer(line)]
    return []


def tolerated(sc, cls: str, line: str, private_ids: list[re.Pattern]) -> bool:
    """True when every match of cls on the line is a public placeholder (never a private value)."""
    if cls == "term":
        return False
    found = _class_matches(sc, cls, line)
    if not found:
        return False
    for s in found:
        if any(p.search(s) for p in private_ids):
            return False
        if cls == "mac":
            norm = re.sub(r"-", ":", s).upper()
            if norm not in ALLOWED_MAC and not ALLOWED_MAC_FAMILY.match(norm):
                return False
        elif cls == "ipv4-private":
            if sc.is_private_ipv4([int(x) for x in s.split(".")]) and not ALLOWED_IPV4_PRIVATE.match(s):
                return False
        elif cls == "ipv4-review":
            octets = [int(x) for x in s.split(".")]
            if sc.is_private_ipv4(octets):
                if not ALLOWED_IPV4_PRIVATE.match(s):
                    return False
            elif not ALLOWED_IPV4_REVIEW.match(s) and not sc.RE_VERSION_QUAD.fullmatch(s):
                return False
        elif cls == "email":
            if not ALLOWED_EMAIL.search(s):
                return False
        elif cls == "home-path":
            if not ALLOWED_HOME.match(s):
                return False
        elif cls in ("long-string-review", "serial-review"):
            pass   # identifiers, digests and encoded art: tolerated unless a private id is inside (above)
        elif cls == "token:assign":
            v = TOKEN_VALUE.search(s)
            value = re.sub(r"\\+u[0-9a-fA-F]{4}\w*", "", v.group(1) if v else s)   # escaped NUL tests
            if not (ALLOWED_TOKENISH.search(value) or
                    (VOCAB_VALUE.match(value) and sum(c.isdigit() for c in value) <= 3)):
                return False
        elif cls == "token:sonos":
            if not (SHORT_SONOS.match(s) or ALLOWED_TOKENISH.search(s)):
                return False
        elif cls.startswith("token:"):
            if not ALLOWED_TOKENISH.search(s):
                return False
        else:
            return False
    return True


@dataclass
class GateResult:
    scanned: int = 0
    tolerated: dict[str, int] = field(default_factory=dict)
    failures: list[tuple[str, int, str]] = field(default_factory=list)   # (public path, line, class)


def run_gate(sc, files: dict[str, bytes], terms: list[str], private_ids: list[re.Pattern]) -> GateResult:
    res = GateResult()
    compiled = sc.compile_terms(terms) if terms else None
    allow_versions = set(sc.BUILTIN_VERSIONS) | sc.discover_versions([], auto=True)
    for public, data in sorted(files.items()):
        if not is_text(data):
            continue
        text = data.decode("utf-8")
        res.scanned += 1
        lines = text.splitlines()
        for cls, lineno, _masked in sc.scan_text(text, compiled, allow_versions):
            line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
            if tolerated(sc, cls, line, private_ids):
                res.tolerated[cls] = res.tolerated.get(cls, 0) + 1
            else:
                res.failures.append((public, lineno, cls))
        # Exact private identifiers in any form, whatever the class (MAC without separators, ids).
        if any(p.search(text) for p in private_ids):
            for i, line in enumerate(lines, 1):
                if any(p.search(line) for p in private_ids):
                    res.failures.append((public, i, "private-id"))
    return res


def private_id_patterns(map_rules: list[MapRule]) -> list[re.Pattern]:
    """Every map pattern doubles as an exact detector (the replacement text never matches it).
    One combined pattern keeps the scan linear in the text size."""
    if not map_rules:
        return []
    parts, separate = [], []
    for r in map_rules:
        if not r.combinable:
            separate.append(r.pattern)
            continue
        body = r.pattern.pattern
        parts.append(f"(?i:{body})" if r.pattern.flags & re.IGNORECASE else f"(?:{body})")
    return ([re.compile("|".join(parts))] if parts else []) + separate


def print_gate(res: GateResult, limit: int = 60) -> None:
    tol = ", ".join(f"{k} {v}" for k, v in sorted(res.tolerated.items())) or "none"
    print(f"gate: scanned {res.scanned} text file(s); placeholders tolerated: {tol}")
    if not res.failures:
        print("gate: OK (0 hits)")
        return
    by_cls: dict[str, int] = {}
    for _p, _l, c in res.failures:
        by_cls[c] = by_cls.get(c, 0) + 1
    print(f"gate: FAIL ({len(res.failures)} hit(s): " + ", ".join(f"{k} {v}" for k, v in sorted(by_cls.items())) + ")")
    for p, l, c in res.failures[:limit]:
        print(f"  {p}:{l} [{c}]")
    if len(res.failures) > limit:
        print(f"  ... {len(res.failures) - limit} more (use --gate-report FILE for all rows)")


# ---------------------------------------------------------------------------------------------------------
# Public side: what exists, what is stale

def public_files(public_root: Path, areas: list[str]) -> list[str]:
    files = set()
    for args in (["ls-files", "-z"], ["ls-files", "-z", "--others", "--exclude-standard"]):
        try:
            out = subprocess.run(["git", "-C", str(public_root)] + args + ["--"] + areas,
                                 capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            out = b""
        for raw in out.split(b"\0"):
            if raw:
                files.add(raw.decode("utf-8", errors="surrogateescape"))
    if not files:   # not a git tree (tests): walk the folders
        for a in areas:
            base = public_root / a
            if base.is_file():
                files.add(a)
            elif base.is_dir():
                for p in base.rglob("*"):
                    if p.is_file() and ".git" not in p.parts:
                        files.add(p.relative_to(public_root).as_posix())
    return sorted(f for f in files if (public_root / f).is_file())


def classify_public(plan: Plan, existing: list[str], specs=SPECS) -> tuple[list[str], list[str]]:
    """(stale, orphans) among public files the plan does not produce. Protected paths are neither."""
    stale, orphans = [], []
    for p in existing:
        if p in plan.items or is_protected(p):
            continue
        spec = next((s for s in specs if s.dest and p.startswith(s.dest + "/")), None)
        renamed = next((s for s in specs if p in s.renames.values()), None)
        if renamed is not None:
            stale.append(p)
            continue
        if spec is None:
            continue
        rel = p[len(spec.dest) + 1:]
        allowed = (matches(rel, spec.include) and not matches(rel, spec.deny) and not matches(rel, ART_DENY)
                   and not matches(rel, GLOBAL_DENY) and not matches(p, GLOBAL_DENY))
        if spec.dest == "tools" and "/" in rel and not rel.startswith("stage_checks/"):
            allowed = False
        (stale if allowed else orphans).append(p)
    return stale, orphans


# ---------------------------------------------------------------------------------------------------------
# Main

def default_private_root() -> Path | None:
    cand = HERE.parent.parent
    if (cand / "work" / "NanoD_RatchetH1").is_dir() and (cand / "app").is_dir():
        return cand
    return None


def resolve_paths(args) -> dict[str, Path]:
    priv = args.private_root or os.environ.get("NANOD_PRIVATE_ROOT") or default_private_root()
    if not priv:
        raise SystemExit("sync_public: set --private-root or NANOD_PRIVATE_ROOT (the folder holding work/ and outputs/)")
    priv = Path(priv).resolve()
    pub = Path(args.public_root or os.environ.get("NANOD_PUBLIC_ROOT") or priv / "publish" / "desk-dial").resolve()
    smap = Path(args.scrub_map or os.environ.get("NANOD_SCRUB_MAP")
                or priv / "work" / "audit" / "private" / "scrub-map.json").resolve()
    terms = Path(args.terms or os.environ.get("NANOD_SCRUB_TERMS") or smap.parent / "terms.txt").resolve()
    sc = Path(args.scrub_check or os.environ.get("NANOD_SCRUB_CHECK")
              or priv / "work" / "audit" / "tools" / "scrub_check.py").resolve()
    for name, p in (("private root", priv), ("public root", pub)):
        if not p.is_dir():
            raise SystemExit(f"sync_public: {name} not found")
    if not smap.is_file():
        raise SystemExit("sync_public: scrub map not found (set --scrub-map or NANOD_SCRUB_MAP)")
    if not sc.is_file():
        raise SystemExit("sync_public: scrub_check.py not found (set --scrub-check or NANOD_SCRUB_CHECK)")
    try:
        pub.relative_to(priv / "work")
        raise SystemExit("sync_public: the public root must not be inside the private work tree")
    except ValueError:
        pass
    for inside in (smap, terms):
        try:
            inside.relative_to(pub)
            raise SystemExit("sync_public: the scrub map and terms must live outside the public repository")
        except ValueError:
            pass
    return {"private": priv, "public": pub, "map": smap, "terms": terms, "scrub_check": sc}


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="plan and gate, write nothing")
    mode.add_argument("--apply", action="store_true", help="write the plan into the public tree")
    mode.add_argument("--check", action="store_true", help="exit 1 when the public tree differs from the plan")
    ap.add_argument("--private-root")
    ap.add_argument("--public-root")
    ap.add_argument("--scrub-map")
    ap.add_argument("--terms")
    ap.add_argument("--scrub-check")
    ap.add_argument("--prune-orphans", action="store_true",
                    help="also delete public files in the synced folders that no rule produces")
    ap.add_argument("--list", action="store_true", help="print every planned path, not only counts")
    ap.add_argument("--gate-report", help="write every gate row (path, line, class) to this JSON file")
    ap.add_argument("--out", help="with --dry-run: also write the planned files into this new, empty folder "
                                  "(outside the public repo) for review; the gate result is unchanged")
    args = ap.parse_args(argv)

    paths = resolve_paths(args)
    map_rules, keep, extra = load_scrub_map(paths["map"])
    sc = load_scrub_check(paths["scrub_check"])
    terms = gate_terms(paths["terms"], keep, extra)
    ids = private_id_patterns(map_rules)

    plan = select(paths["private"])
    rewrite(plan, map_rules)

    for p in plan.items:
        if is_protected(p):
            raise SystemExit(f"sync_public: internal error, plan writes a README-owned path: {p}")

    pub = paths["public"]
    areas = sorted({s.dest for s in SPECS if s.dest}) + sorted({v for s in SPECS for v in s.renames.values()})
    existing = public_files(pub, areas)
    stale, orphans = classify_public(plan, existing)
    new = [p for p in plan.items if not (pub / p).is_file()]
    changed = [p for p in plan.items if (pub / p).is_file() and (pub / p).read_bytes() != plan.items[p].data]
    same = len(plan.items) - len(new) - len(changed)

    rule_totals: dict[str, int] = {}
    for it in plan.items.values():
        for k, v in it.rules_hit.items():
            rule_totals[k] = rule_totals.get(k, 0) + v
    rewritten = [it for it in plan.items.values() if it.rewritten]
    private_files = sum(1 for it in plan.items.values() if it.private_hits)
    private_total = sum(it.private_hits for it in plan.items.values())

    print(f"sync_public: {'dry run' if args.dry_run else 'check' if args.check else 'apply'}")
    per_area: dict[str, int] = {}
    for p in plan.items:
        a = p.split("/", 1)[0]
        per_area[a] = per_area.get(a, 0) + 1
    print("planned files: " + ", ".join(f"{a} {n}" for a, n in sorted(per_area.items())) + f" (total {len(plan.items)})")
    print(f"copies: new {len(new)}, changed {len(changed)}, unchanged {same}")
    print(f"rewrites: {len(rewritten)} file(s); layout/path rules: "
          + (", ".join(f"{k} {v}" for k, v in sorted(rule_totals.items())) or "none")
          + f"; private-map replacements {private_total} in {private_files} file(s)")
    print(f"deletions: stale allow-listed {len(stale)}; orphans (not allow-listed) {len(orphans)}"
          + (" -> deleted" if args.prune_orphans else " -> kept (use --prune-orphans)"))
    reasons: dict[str, int] = {}
    for _s, r in plan.denied:
        reasons[r] = reasons.get(r, 0) + 1
    print("not copied: " + (", ".join(f"{r} {n}" for r, n in sorted(reasons.items())) or "none"))
    if plan.excluded_tests:
        print(f"excluded with its test (reads third-party art): {len(plan.excluded_tests)}")
        for p, f in plan.excluded_tests:
            print(f"  {p}  (reads {f})")
    if plan.dangling:
        print(f"references to excluded art kept (dangling): {len(plan.dangling)}")
        for p, f in plan.dangling:
            print(f"  {p}  (names {f})")
    if plan.untracked_explicit:
        print("explicitly listed but untracked in its repo (copied): " + ", ".join(plan.untracked_explicit))
    if plan.missing_explicit:
        print("explicitly listed but missing: " + ", ".join(plan.missing_explicit))
    if args.list:
        for p in sorted(new):
            print(f"  + {p}")
        for p in sorted(changed):
            print(f"  ~ {p}")
        for p in stale:
            print(f"  - {p} (stale)")
        for p in orphans:
            print(f"  {'-' if args.prune_orphans else '?'} {p} (orphan)")

    # The gate covers everything the public synced folders will hold afterwards.
    final: dict[str, bytes] = {p: it.data for p, it in plan.items.items()}
    if not args.prune_orphans:
        for p in orphans:
            final[p] = (pub / p).read_bytes()
    res = run_gate(sc, final, terms, ids)
    print_gate(res)
    if args.gate_report:
        Path(args.gate_report).write_text(json.dumps(
            {"failures": [{"file": p, "line": l, "class": c} for p, l, c in res.failures],
             "tolerated": res.tolerated, "scanned": res.scanned}, indent=1), encoding="utf-8")

    if args.out and args.dry_run:
        out = Path(args.out).resolve()
        for forbidden in [pub] + [paths["private"] / sp.repo / sp.sub for sp in SPECS if sp.repo != "work"] + [
                paths["private"] / "work" / "lcd-preview", paths["private"] / "work" / "stage_checks"]:
            try:
                out.relative_to(forbidden)
                raise SystemExit("sync_public: --out must be outside the public repo and the private trees")
            except ValueError:
                pass
        if out.exists() and any(out.iterdir()):
            raise SystemExit("sync_public: --out folder must be new or empty")
        for p, it in plan.items.items():
            dst = out / p
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(it.data)
        print(f"out: wrote {len(plan.items)} planned file(s) for review")

    drift = bool(new or changed or stale or (orphans and args.prune_orphans))
    if args.check:
        print("check: " + ("DRIFT" if drift else "in sync"))
        return 1 if (drift or res.failures) else 0
    if args.dry_run:
        return 1 if res.failures else 0

    # --apply
    if res.failures:
        print("apply: refused, the gate failed; nothing was written")
        return 1
    for p in new + changed:
        dst = pub / p
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(plan.items[p].data)
    for p in sorted(set(stale + (orphans if args.prune_orphans else []))):
        if is_protected(p) or p in plan.items:
            continue
        (pub / p).unlink(missing_ok=True)
    after = {p: (pub / p).read_bytes() for p in public_files(pub, areas) if not is_protected(p)}
    res2 = run_gate(sc, after, terms, ids)
    print("after apply:")
    print_gate(res2)
    if res2.failures:
        print("apply: the written tree fails the gate; review with git status / git diff before committing")
        return 1
    print(f"apply: wrote {len(new) + len(changed)}, deleted {len(stale) + (len(orphans) if args.prune_orphans else 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
