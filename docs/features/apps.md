# Apps

Desk Dial can turn the knob into a controller for the program in front of you. Each app has a **profile**: what turning does, what each button does, and which knob screen it shows. The profiles come from Karl Malota's Nano_D app profiles, with a small Windows add-on for each.

Onshape has its own page, [Onshape](onshape.md); everything there still applies. This page covers all the apps, the Settings › Apps page, and how to add or update a profile.

Desk Dial is tested on one knob (the author's). This page describes Desk Dial v2.0.0.

## Which apps

| App | Status | Picked when this is in front |
|---|---|---|
| Onshape | Tested (in Chrome) | cad.onshape.com or a company workspace (`*.onshape.com`) in a browser |
| Figma | Not yet tested | Figma.exe, or figma.com in a browser |
| Plasticity | Not yet tested | Plasticity.exe |
| Blender | Basic | blender.exe |
| AutoCAD | Basic | acad.exe |

- **Tested** means checked on the author's knob.
- **Not yet tested** means nobody has tried it on Windows yet: the shortcuts come from Karl's profile (made on a Mac), mapped Cmd to Ctrl and Option to Alt and checked against the app's own Windows shortcut documentation. When an owner confirms an app works, its badge becomes **Community tested**. If a command is wrong, [open an issue](https://github.com/hooterjackson/desk-dial/issues).
- **Basic** means the knob scrolls and nothing more: Karl's profile has no commands for that app yet.

Websites are recognised in Chrome, Edge, Brave, Vivaldi and Opera; only Chrome has been tried. Firefox is not supported.

## Off, Manual or Auto

Every app has one of three modes in **Settings › Apps**:

- **Off**: Desk Dial never switches to it.
- **Manual**: you turn it on from the tray. Right-click the tray icon and open **App mode**, which has one toggle for each app set to Manual. With no app set to Manual, the menu shows "Set an app to Manual in Settings › Apps".
- **Auto**: it is on while the app is in front.

Every app except Onshape starts Off. Onshape keeps the mode you had before this version, because your earlier Onshape mode setting carries over.

In any app, hold all four knob buttons for 1 second to go back to Home.

## The knob in an app

On a knob with the current firmware, each app gets its own screen: Onshape its cube and command wheel, Figma its name and icon, Plasticity a pyramid. "LOADING..." shows for a moment while a profile is sent to the knob; if the knob has dropped a profile from its memory, a text screen shows until it has been sent again. A knob with older firmware shows a text screen instead.

When a button cannot do its job, the knob tells you why:

| The knob says | Underneath | Why |
|---|---|---|
| Point at the app | Put the cursor on it | The mouse pointer is not over the app. |
| Click the app first | Keys go to the app | The app does not have keyboard focus. |
| Not on this keyboard | Its key needs another layout | The shortcut uses a key your keyboard layout does not have. |
| Not on Windows | This command is off here | The command does not exist on Windows. |

Onshape keeps its own messages; see [Onshape](onshape.md).

## Settings › Apps

The page lists one row per app: its icon, its name, its status badge, Off / Manual / Auto, a line saying where the profile came from (Karl, Imported or Updated) and how it is recognised, and a **Rules…** button.

The intro on the page reads: "Each app profile sets what the knob and its buttons do in that app. Manual: turn it on from the tray’s App mode menu. Auto: on while the app is in front. Hold all four knob buttons for 1 s for Home."

**Rules…** opens "Rules · {app}", with two lists, **Programs** and **Websites**, and the built-in rules underneath. Add a program by its file name (such as `Figma.exe`) or a website by its host (such as `figma.com` or `*.figma.com`). If you paste a whole web address, Desk Dial keeps only the host and says "Kept the host only: {host}. Desk Dial never stores a web address." A rule can never point at a command shell, a terminal or Windows' own shell; those are refused.

The Knob page now only points here: "Onshape and other apps: Settings › Apps."

## Adding and updating profiles

- **Import profile…** takes a profile file (`.json`). If a matching Windows add-on (`<id>.windows.json`) sits next to it, that comes along too. The page then says "Imported {app}. Choose Manual or Auto to use it.", or "Couldn't import {file}: {problems}" and what is wrong.
- **Open profiles folder** opens `%LOCALAPPDATA%\DeskDial\data\profiles\user\`, where your imports live.
- **Check for updates** asks this repository for newer versions of the bundled profiles, once, when you click. Possible answers are "Profiles are up to date.", "Updated: {names}.", "Couldn't reach the Desk Dial repo. Your profiles haven't changed." and, for a file it rejects, "{app}: {reason}. Kept the current version."
- **Fetch updated profiles from the Desk Dial repo (once a day)** does the same check daily. It is off until you tick it.

Imports and updates take effect straight away; nothing needs a restart. Updates are kept in `%LOCALAPPDATA%\DeskDial\data\profiles\updates\`; the profiles that ship with Desk Dial stay in the app's own `profiles\` folder.

To write or change a profile, see the author guide in [profiles/README.md](../../profiles/README.md).

## Privacy

- To recognise an app, Desk Dial reads the file name of the program in front and, in a browser, the host in its address bar (for example `figma.com`). It looks at the window title only to notice a change (and, for Onshape, when the address bar cannot be read); titles and web addresses are never stored or logged.
- With no app set to Auto and none on, it reads nothing about the window in front at all.
- The log and `status.json` record only which app was picked and whether it matched by program or by website.
- Nothing is sent to an app while the screen is locked or a Windows permission prompt (UAC) is showing.
- The update check, off unless you turn it on or click **Check for updates**, makes one HTTPS request for `profiles/index.json` from this repository on `raw.githubusercontent.com`, plus any files that changed. It sends nothing about you.

## Known limits

- Figma and Plasticity are not yet tested, and Blender and AutoCAD are basic (scroll only), as above.

App icons: pixel art by Karl Malota ([katbinaris](https://github.com/katbinaris)), from his Nano_D app profiles.
