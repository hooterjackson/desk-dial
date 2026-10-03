# App profiles

An app profile tells Desk Dial and the knob what to do in one application: what turning the knob and
holding buttons 1–4 send, the command wheel, parameter mode, and what the knob's screen shows. Profiles
are data only. Desk Dial never runs anything from a profile file.

The profile format is Karl Malota's (katbinaris), from his `feat/firmware-esp-idf-quadra` firmware
branch, used with his permission.

## Files

| File | What it is |
|---|---|
| `karl/<id>.json` | Karl's profile JSON, `"format": 1`, exported from his firmware unchanged |
| `karl/SOURCE.json` | Karl's commit and the SHA-256 and size of each exported file |
| `<id>.windows.json` | The Windows sidecar, `"overlay": 1`: detection, Windows keys, slot and feel changes, status |

Desk Dial looks for profiles in three places. When two places have the same id, the higher one wins:

1. `%LOCALAPPDATA%\DeskDial\data\profiles\user\`: imported files. Desk Dial never overwrites these.
2. `%LOCALAPPDATA%\DeskDial\data\profiles\updates\`: fetched files.
3. This folder, bundled with the app (read only).

A source checkout uses `local\profiles\user\` and `local\profiles\updates\` instead.

Each id takes Karl's file from the highest place that has a valid one. It takes the sidecar from the
highest place whose sidecar fits that file. So an updated Karl file keeps the bundled Windows layout. A
file that fails the checks is skipped, and the problem is reported. If an id has no valid file left, the
last good version stays loaded.

The file name must be the profile's `id`: `figma.json` and `figma.windows.json`.

## Karl's format, briefly

The field names follow Karl's C structs. Enums are lowercase names. A missing field reads as 0, false or
none.

- **Header:** `id` (1–11 chars, `a-z 0-9 _ -`, never a Windows device name such as `con`, `nul`, `com1` or `lpt1`), `name` (≤ 15), `legend` (4 texts, ≤ 7 each).
- **Icons:** `icon24` / `icon48`, base64 of RGB565 big-endian pixels (1152 / 4608 bytes).
- **Visual:** `visual` (`label` | `shape`), `shape` (`cube` | `pyramid` | `octa`), `shape_style`
  (`face` | `grips` | `thick`), `shape_stepped`, `plasma` (3 × 0xRRGGBB).
- **`slots`:** `knob`, `f1`…`f4`. Each has a `kind` (`none` | `drag` | `wheel` | `keys` | `tap` |
  `commands`), `label` (≤ 23) and `buttons` (mouse bits 1 left, 2 right, 4 middle). It can also have
  `modifier`, `axis_y`, `px_per_rad` (0–2000), `sign` (−1..1), `cw` / `ccw` / `tap` keys, `macro` /
  `tap_macro` names, `feel` (`saw` | `sine` | `viscose`), `detents` (0–36) and `fx` (`none` | `zoom` |
  `orbit` | `pan` | `flash`).
- **`rings`:** up to 8 rings, each with `name` (≤ 23), `tab` (≤ 6), `slot` and 1–32 `cmds`. Each command
  has a `name` (≤ 23), a `kind` (`keys` | `actions` | `macro`), and `key`, `phrase` (≤ 60, typed into
  the app's search), `macro`, `scene` and `param`.
- **Scenes:** `base` plus up to 16 `frames` (`ms` 0–60000), each with up to 48 elements of 9 numbers.
- **`search`:** `open` key, `open_wait` and `result_wait` in 10 ms ticks. Needed by `actions` commands.
- **`param_keys`, `macros`:** up to 16 macros of up to 64 steps (`key`, `text` ≤ 120, `wait` ≤ 10000 ms).

Keys are `[modifier, keycode]`. These are USB HID usages, meaning key positions on a US keyboard. The
modifier bits are 1 Ctrl, 2 Shift, 4 Alt (Option), 8 GUI (Cmd), and the same four again for the right
side.

On Windows, Cmd always becomes Ctrl and Option becomes Alt. To send something else for one shortcut, override
it in the sidecar's `keys`. (An older sidecar option, `gui`, was removed; a sidecar that still has it is
refused.)

Desk Dial reads each key as the US character it types:

- Letters and digits work on any layout.
- Punctuation (`- = [ ] \ ; ' ` , . /`) is looked up in the foreground window's keyboard layout. A
  command whose character needs AltGr, or needs a Shift the chord doesn't hold, is refused on the knob
  ("Not on this keyboard"), so the wrong key is never sent.
- F-keys, Enter, Esc, Tab, the arrows and the keypad keys are fixed keys.

Desk Dial is stricter than Karl's reader. It refuses:

- a file over 128 KB, or nested deeper than 32;
- any byte that isn't printable ASCII;
- duplicate keys, `null`, NaN or Infinity;
- floats beyond ±1e7;
- fractions where a whole number belongs;
- a chord that leaves the app, anywhere in the profile (a command, slot, macro step or parameter key):
  anything with the Windows key, Alt+Tab, Alt+Esc, Ctrl+Esc, Ctrl+Shift+Esc, Alt+F4, Alt+Space,
  Ctrl+Alt+Del / End, and, for a profile with website rules, the tab and window keys the browser keeps
  (Ctrl+T / N / W / Tab / PgUp / PgDn / F4, with or without Shift where Chrome uses it) and the developer
  tools (F12, Ctrl+Shift+I / J). Use the sidecar's `keys` to override or disable such a command.

## The Windows sidecar

```json
{"overlay": 1, "status": "community",
 "detect": {"exe": ["Figma.exe"], "host": ["figma.com", "*.figma.com"],
            "exclude_host": ["help.figma.com"], "content_class": ["Chrome_RenderWidgetHostHWND"]},
 "keys": {"ALIGN/TIDY UP": "ctrl+alt+t", "*/RENAME": "f2", "UTILITY/COPY PROPERTIES": null,
          "STRUCTURE/GROUP": {"chord": null, "disabled_reason": "Not in Figma for Windows"},
          "@search": "ctrl+k"},
 "slots": {"knob": {"notches_per_turn": 24, "feel": "BINARIS BEER", "detents": 67},
           "f1": {"kind": "drag", "label": "TILT", "buttons": 2, "axis_y": true, "button": 0}},
 "legend": ["TILT", null, null, null],
 "notes": ["Where each override comes from."]}
```

| Key | Meaning |
|---|---|
| `overlay` | Must be `1` |
| `status` | `tested`, `community` or `basic` (Settings shows Tested / Not yet tested / Basic; see below) |
| `detect.exe` | Program file names, such as `Figma.exe`. No folders |
| `detect.host` | Bare hosts for Chromium browsers (Chrome, Edge, Brave, Vivaldi, Opera); `*.x.com` = any subdomain of `x.com`. No `https://`, path or port |
| `detect.exclude_host` | Hosts that never match |
| `detect.content_class` | Window classes the pointer must be over |
| `keys` | `"RING/COMMAND"` or `"*/COMMAND"` → a Windows chord, or `null` = disabled on Windows (drawn grey, refused). An object form adds a `disabled_reason` (≤ 60 chars). `@search` and `@param_keys.numeric / confirm / cancel / uniform / select_all / axis0..2` override those keys |
| `slots` | A partial Karl slot per `knob` / `f1`…`f4`. `cw`, `ccw` and `tap` may be chords (`"ctrl+z"`) or `null`, and `modifier` may be `"ctrl+shift"`. Windows extras: `feel` (a Desk Dial knob profile name), `haptic` (Karl's feel enum), `notches_per_turn` (wheel notches per knob turn), `button` (0–3: the physical button that selects the slot) and `detents` (up to 1000) |
| `params` | `"RING/COMMAND"` → `{"unit": "mm"}` (≤ 7 chars, typed after the value) |
| `legend` | 4 texts under the keycaps; `null` keeps Karl's |
| `notes` | Text or a list of lines, ≤ 400 chars each. Cite the app's Windows shortcut page for each override, and mark the rest "unverified" |

Chords are written as modifiers then one key: `ctrl`, `shift`, `alt`, `win`, then a key such as `z`,
`7`, `f5`, `/`, `enter`, `esc`, `tab`, `space`, `delete`, `home`, `pgup`, `up`, `num1`, `num+` or
`numenter`.

Unknown keys are refused. So is a reference to a command, slot or macro that doesn't exist. When Karl
renames a command, the sidecar has to follow.

Without a sidecar, a profile isn't detected (no rules) and its status is `community` (or `basic` with no
rings).

## Shipped profiles

The status is shown in Settings › Apps:

- **Tested** (`tested`): the author has tried this profile on Windows.
- **Not yet tested** (`community`): the shortcuts are mapped from Karl's Mac profile and checked against
  the app's Windows shortcut docs, but the author hasn't tried them. It becomes "Community tested" once an
  owner of the app confirms it.
- **Basic** (`basic`): scroll only, no command wheel.

| App | Status | Detection | Notes |
|---|---|---|---|
| Onshape | tested | `cad.onshape.com`, `*.onshape.com` (not www, learn, forum…) | Desk Dial's own layout (below) |
| Figma | community | `Figma.exe`, `figma.com`, `www.figma.com` | Karl's chords, Cmd → Ctrl |
| Plasticity | community | `Plasticity.exe` | Karl's chords |
| Blender | basic | `blender.exe` | Scroll only (Karl's template) |
| AutoCAD | basic | `acad.exe` | Scroll only (Karl's template) |

Onshape's buttons work like this:

- the knob alone zooms (24 wheel notches per turn, BINARIS BEER feel);
- hold 1 and turn = tilt, hold 2 = orbit, hold 4 = pan;
- tap 3 = Undo, hold 3 = the command wheel;
- holding all four buttons for 1 s goes Home (every profile).

## Validate a profile

```
python tools/profiles/validate.py profiles
python tools/profiles/validate.py path\to\figma.json
python tools/profiles/validate.py path\to\figma.windows.json
```

Each profile gets one line: its status, the size of the compiled knob profile, its CRC and its feature
bits. Every problem is printed in plain words. The exit status is 0 when everything is valid and 1 when
anything isn't. The compiled profile for the knob must fit in 32768 bytes.

## Refreshing Karl's files

```
python tools/profiles/import_karl.py [--karl <clone>] [--ref <sha>] [--cjson <dir>]
```

1. The script builds Karl's own `tools/profile_json_test` unchanged, with a pinned cJSON v1.7.18 (checked
   by SHA-256) and a generated `class/hid/hid.h`. It uses MSVC on Windows, or `cc` / `gcc` with Karl's
   `run.sh` flags elsewhere.
2. It dumps his built-ins and validates them.
3. It rewrites `karl/` and `karl/SOURCE.json`.
4. It prints a summary of the changes: added, removed and renamed commands, broken sidecar references, and
   size changes.

Nothing is written if any file fails.
