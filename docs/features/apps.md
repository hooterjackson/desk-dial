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

Settings › Apps draws these badges in capitals: TESTED, NOT YET TESTED, BASIC.

- **Tested** means the author has tried the profile on Windows.
- **Not yet tested** means nobody has tried it on Windows yet: the shortcuts come from Karl's profile (made on a Mac), mapped Cmd to Ctrl and Option to Alt and checked against the app's own Windows shortcut documentation. When an owner confirms an app works, its badge becomes **Community tested**. If a command is wrong, [open an issue](https://github.com/hooterjackson/desk-dial/issues).
- **Basic** means the knob scrolls and nothing more: Karl's profile has no commands for that app yet.

Websites are recognised in Chrome, Edge, Brave, Vivaldi and Opera; only Chrome has been tried. Firefox is not supported.

## Off, Manual or Auto

Every app has one of three modes in **Settings › Apps**:

- **Off**: Desk Dial never switches to it.
- **Manual**: you turn it on and off yourself from the tray: right-click the tray icon, open **App mode** and pick the app.
- **Auto**: it comes on by itself while the app is in front. You can also pick it in the tray's App mode menu.

The App mode menu lists every app. Picking one that is Off says "Turn {app} on in Settings › Apps first."; without a knob running the current firmware it says "{app} needs the knob connected (firmware with the r3 screens).", and with a list or Seek open on the knob, "Close the open screen on the knob first."

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

Onshape keeps its own wording for the first two: "Point at the model" / "Put the cursor on it" and "Click the model first" / "Keys go to the page" (see [Onshape](onshape.md)). Each message shows for two seconds, with the error sound and a buzz.

## Settings › Apps

<p><img src="../media/settings-apps.png" alt="Desk Dial Settings, Apps page: Onshape (Tested), Figma and Plasticity (Not yet tested), Blender and AutoCAD (Basic), each with its icon, Off / Manual / Auto, where its profile came from, how it is recognised and a Rules button; below them Import profile, Open profiles folder, Check for updates, and the daily-fetch checkbox, off" width="420"></p>

The page lists one row per app: its icon, its name, its status badge, Off / Manual / Auto, a line saying where the profile came from (Karl, Imported or Updated) and how it is recognised, and a **Rules…** button.

The intro on the page reads: "Each app profile sets what the knob and its buttons do in that app. Manual: turn it on from the tray’s App mode menu. Auto: on while the app is in front. Hold all four knob buttons for 1 s for Home."

**Rules…** opens "Rules · {app}", with two lists, **Programs** and **Websites**, and the built-in rules underneath. Add a program by its file name (such as `Figma.exe`) or a website by its host (such as `figma.com` or `*.figma.com`). If you paste a whole web address, Desk Dial keeps only the host and says "Kept the host only: {host}. Desk Dial never stores a web address."; a pasted file path keeps only the file name. Each list holds up to 32 entries. A rule can never point at a command shell, a terminal or Windows itself (see below).

The Knob page now only points here: "Onshape and other apps: Settings › Apps."

## Adding and updating profiles

- **Import profile…** takes a profile file (`.json`). If a matching Windows add-on (`<id>.windows.json`) sits next to it, that comes along too. Everything is checked first, and a profile is only data: nothing in it is run. For a new app the page says "Imported {app}. Choose Manual or Auto to use it." Importing a new version of an app you already have turns that app Off first: "Imported {app}. It's Off: choose Manual or Auto to use it." A file that fails the checks says "Couldn't import {file}: {problems}".
- **Open profiles folder** opens `%LOCALAPPDATA%\DeskDial\data\profiles\user\`, where your imports live.
- **Check for updates** asks this repository for newer versions of the bundled profiles, once, when you click. Possible answers are "Profiles are up to date.", "Updated: {names}.", "Couldn't reach the Desk Dial repo. Your profiles haven't changed." and, for a file it rejects, "{app}: {reason}. Kept the current version."
- **Fetch updated profiles from the Desk Dial repo (once a day)** does the same check daily. It is off until you tick it.

Imports, updates and Rules changes take effect straight away; nothing needs a restart. A file you copy into the folder by hand is picked up at the next import, update or start. Updates are kept in `%LOCALAPPDATA%\DeskDial\data\profiles\updates\`; the profiles that ship with Desk Dial stay in the app's own `profiles\` folder.

To write or change a profile, see the author guide in [app/profiles/README.md](../../app/profiles/README.md).

## Privacy

- To recognise an app, Desk Dial reads the file name of the program in front and, in a browser, the host in its address bar (for example `figma.com`). It looks at the window title only to notice a change (and, for Onshape, when the address bar cannot be read); titles and web addresses are never stored or logged.
- It reads only for apps set to Manual or Auto (and the one that is on). With every app Off, it reads nothing about the window in front at all.
- The log and `status.json` record only which app was picked and whether it matched by program or by website.
- Nothing is sent to an app while the screen is locked or a Windows permission prompt (UAC) is showing.
- The update check, off unless you turn it on or click **Check for updates**, makes one HTTPS request for `app/profiles/index.json` from this repository on `raw.githubusercontent.com`, plus any files that changed. It sends nothing about you, your PC or the profiles you use, and checks each file's size and checksum before using it.

## Known limits

- Figma and Plasticity are not yet tested, and Blender and AutoCAD are basic (scroll only), as above. App profiles are new in v2.0.0; beyond Onshape they are not yet tested on real hardware.
- **Run your apps normally, not as administrator.** Windows blocks input from an ordinary program to one running as administrator; Desk Dial then lets go of everything, and the knob shows no message.
- While you hold Ctrl, Shift, Alt or the Windows key on your keyboard, the knob's shortcuts and typed text are skipped.
- There is no Navigator card while an app is on.
- Onshape's command wheel and parameter mode need the current firmware; other apps show their wheel as text on an older knob.

## What a profile can never do

- **Target a shell or Windows itself.** Command prompts, PowerShell, terminals, Explorer, Start, Settings and the lock and permission screens can never be an app's program, in a profile or in Rules.
- **Send dangerous shortcuts.** Anything with the Windows key, Alt+Tab, Alt+Esc, Alt+F4, Alt+Space, Ctrl+Esc, Ctrl+Shift+Esc and Ctrl+Alt+Del are never sent. For website apps, the browser's tab and window shortcuts (new tab, close tab, next tab and the like) and its developer tools are blocked too. A profile that contains one is refused when it is loaded.
- **Type into the wrong place.** Before typing text after a shortcut, Desk Dial checks again that the app or page still has keyboard focus.
- **Act on the lock screen.** Nothing is sent while the screen is locked or a Windows permission prompt (UAC) is up.

App icons: pixel art by Karl Malota ([katbinaris](https://github.com/katbinaris)), from his Nano_D app profiles.
