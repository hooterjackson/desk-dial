# Privacy and data

Desk Dial runs on your PC and talks to things on your own network plus, if you set it up, Apple Music. This page lists everything it reads, everything it sends, where it keeps your data, and how to remove it. Each statement was checked against the current source code; where something could not be checked on real hardware it says so.

## What it reads on your PC

| What | When | Why | Kept? |
|---|---|---|---|
| The titles of your open windows | When you open the Windows picker (button 2 on Home) | To show the window list on the knob and the live previews on the PC | No. Titles are shown on the knob over USB and never written to a log. |
| The program name of the front window and, for Chrome, Edge, Brave, Vivaldi or Opera, the host in its address bar; the window title only to notice a change (and, for Onshape, when the address bar cannot be read) | Only for apps set to Manual or Auto in Settings › Apps (and the one that is on); with every app Off, nothing is read | To recognise the app you are working in (see [Apps](features/apps.md)). Only the host is compared; the full address never leaves the function that reads it | No. Logs and `status.json` keep only which app matched and whether by program or by website. |
| The knob's own profiles and settings (including its serial number) | Once each time the knob connects | To back them up before the app takes control | Yes, in `backups\` (see below). |
| Your taskbar theme (dark or light) | At start, when Windows signals a theme change, and every 30 s as a backstop | To pick the matching tray icon | No. |
| The Windows "animation effects" setting | While Settings › General › Motion is "Match Windows" | To follow your preference for reduced motion | No. |

Window titles are read with the ordinary Windows function for the caption of a top-level window. The app check reads a browser's address bar through UI Automation, the same interface screen readers use; it reads only the one text field and turns the result into a host name before anything else sees it. Nothing else on your screen is read.

## What it sends, and where

| Destination | What goes there | When |
|---|---|---|
| Your Sonos speaker (the IPv4 address you typed, port 1400, on your LAN) | Volume, play, pause, skip, seek, queue commands, and requests for the speaker's own cover images | Every second while the app runs (a status poll) and when you act on the knob |
| Your Home Assistant (the address you typed) | Your long-lived access token, light commands, scene and script calls, and a request to save a snapshot scene named `scene.desk_dial_snapshot` before "All off" | One WebSocket connection while the app runs, with plain HTTPS requests as a fallback |
| `api.music.apple.com` | Your developer token (signed on the PC from your MusicKit key) and your Apple Music user token, with requests for Recently Added, Playlists, song details and queue covers; one write only: Like (adding a favourite) | When you use the music screens with Apple Music set up |
| `*.mzstatic.com` (Apple's artwork servers) | Requests for cover images, with no credentials | When a cover is needed |
| `js-cdn.music.apple.com` | Your browser loads Apple's MusicKit script from here during "Authorize Apple Music" | Only during authorisation |
| `raw.githubusercontent.com` (this repository's `app/profiles/index.json`, then any changed profile files) | A plain HTTPS request, with nothing about you | Only when you click Check for updates in Settings › Apps, or once a day if you tick Fetch updated profiles (off by default) |

That is the whole list. There is no telemetry, no crash reporting to anyone, and no update check. The author checked this by searching the whole `control_center` package for every address literal and every network call: the only hosts named in the code are the ones above, plus `127.0.0.1` for the local authorisation page and Microsoft documentation links in code comments.

Two things never cross the network at all: the knob's profile backups and your window titles.

### How the Home Assistant token travels

If the address you enter starts with `http://`, the token and every command cross your LAN unencrypted. Anyone able to capture traffic on that network could read the token and use it against your Home Assistant. Use `https://` if your installation offers it. Settings shows a warning under the address when it starts with `http://`, and still allows it.

With `https://` the certificate is checked in the normal way, so a self-signed certificate will most likely be refused ("Can’t reach Home Assistant on this network."). Not yet tested on real hardware.

### How Apple Music authorisation works

"Authorize Apple Music" in Settings starts a tiny web server on your PC, bound to `127.0.0.1` only, and opens its page in your browser. The page loads Apple's MusicKit script and asks you to allow Desk Dial to read your library and mark favourites. Apple hands the resulting user token to the page, and the page posts it back to the local server, protected by a one-time code and a 15-minute deadline. The token goes only to your PC; the local server logs nothing and closes when Settings closes.

## Where your credentials live and how they are protected

Three secrets are stored: the text of your MusicKit private key (`.p8`), your Apple Music user token, and your Home Assistant long-lived access token. All three live in one file:

`%LOCALAPPDATA%\DeskDial\data\credentials.bin`

Two more files next to it use the same format for recovery data about the Sonos queue (`queue-recovery.bin`) and the shuffle state (`shuffle-restore.bin`).

Each file is encrypted with Windows DPAPI (the Data Protection API) in current-user mode. Only your Windows account on this PC can decrypt it; a different user on the same machine, or a copy of the file moved to another PC, cannot be read. The file is written atomically, so a crash mid-save leaves either the old file or the new one, never a half-written one.

What DPAPI does **not** protect against:

- Any program running under your own Windows account can decrypt the file just as Desk Dial does. Malware on your account has your tokens.
- Anyone who knows your Windows password, or has your account's recovery material, can decrypt it.
- A backup tool that runs as you and copies the file preserves the encrypted bytes, but they are useless on another machine or account unless your Windows profile is migrated with them.

If you suspect a token has leaked: revoke the long-lived access token in Home Assistant (Profile › Security), and revoke the MusicKit key in your Apple developer account. Then quit Desk Dial, delete `credentials.bin`, and set the services up again.

## Where everything else lives

Everything is under `%LOCALAPPDATA%\DeskDial\` (normally `C:\Users\<you>\AppData\Local\DeskDial\`):

| Path | Contents | Format |
|---|---|---|
| `data\credentials.bin` | MusicKit key text, Apple Music user token, Home Assistant token | DPAPI-encrypted |
| `queue-recovery.bin`, `shuffle-restore.bin` | What Desk Dial needs to restore the Sonos queue and shuffle state | DPAPI-encrypted |
| `data\settings.json` | Speaker IP address, Home Assistant address and area, button order, every Settings choice (sounds, haptics, LEDs, motion, navigator, app modes and your app rules). Never a token | Plain JSON |
| `data\queue-ledger.json` | A record of the songs Desk Dial itself queued on the speaker | Plain JSON |
| `logs\app.log` (+ `.1` to `.3`) | The app's diary: connections, errors, state changes. 1 MB each, rotated | Plain text |
| `logs\crash.log` (+ `.1`) | Written only if the app dies: time, process id, and the Python stack of every thread | Plain text |
| `logs\status.json` | A snapshot of the running app, rewritten every second (see below) | Plain JSON |
| `logs\smoke-test.json`, `logs\music-check.json` | Results of the self-test modes, if you ran them | Plain JSON |
| `backups\control-center-inventory-<time>-<id>.json` | Your knob's profiles and settings as read at connect: profile names and their haptic parameters, the serial number, firmware version, device name, orientation and LED brightness, plus the COM port | Plain JSON |

Album covers are cached in memory only and vanish when the app quits. Nothing is stored on the knob by Desk Dial.

The `backups\` folder gains one file per connection and is never pruned; after months of daily use it will hold hundreds of small files. You may delete old ones at any time; keep at least one if you ever want to compare your knob's profiles with what Karl's firmware shipped.

## What the logs contain

`app.log` records what the app did and what went wrong: when the knob connected, which screen was entered, when a service could not be reached, and warnings with the type of an error. By design it never contains a token, a window title, a browser address, a cover URL or the contents of an HTTP response. Paths written to it include your Windows user name.

`crash.log` is only written when the process dies unexpectedly. It holds the time, the process id and a stack trace of every thread. Stack traces contain file paths of the program, not your data.

`status.json` is a read-only view of the running app, meant for diagnosis. It contains:

- the path of the running `DeskDial.exe` and of the data folder (both include your Windows user name)
- whether a knob is connected, the knob's firmware details and the current screen
- whether Apple Music is authorised (yes or no, never the token)
- the speaker's online state and volume
- the Home Assistant area id and the light ids in it (never the address or the token)
- the active app and how it matched (program or website), and refusal counts (never a window title or address)
- counters for the stage, the picker, artwork and frame timing

### How to share logs safely

Attach `app.log`, `crash.log` and `status.json` to an issue after replacing your Windows user name in every path. Remove the Home Assistant area and light ids from `status.json` if you would rather not share them. Never attach `credentials.bin`, the two other `.bin` files, anything in `data\` (your speaker address and settings) or anything in `backups\` (your knob's serial number).

## Uninstall footprint

Desk Dial ships as a portable zip. There is no installer, no auto-start entry and no uninstaller in this release, so nothing is written to the registry and nothing runs at start-up unless you set that up yourself.

To remove it completely:

1. Quit Desk Dial from the tray.
2. If you created a start-up shortcut or a scheduled task for it, remove that.
3. Delete the folder you unzipped (`DeskDial\` with `DeskDial.exe` and `_internal\`).
4. Delete `%LOCALAPPDATA%\DeskDial\`. This removes the encrypted credentials, the settings, the logs and the knob backups.
5. Optionally revoke the tokens you created for it: the long-lived access token in Home Assistant, and the MusicKit key in your Apple developer account. The Home Assistant snapshot scene `scene.desk_dial_snapshot`, if it exists, can be deleted in Home Assistant.

The knob keeps whatever firmware is on it. To return to Karl's firmware see the [flashing guide](flashing.md).

## Limits and known issues

- Home Assistant over `http://` is allowed (with a warning in Settings), so the token can travel unencrypted on your LAN.
- Self-signed Home Assistant certificates are likely to be refused; not yet tested on real hardware.
- `status.json` and `app.log` contain your Windows user name in file paths.
- The `backups\` folder is never pruned.
- Window titles are shown on the knob's screen while the picker is open; anyone who can see the knob can read them.
