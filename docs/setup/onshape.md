# Setting up Onshape

Onshape mode turns the knob into a 3D mouse for Onshape, the browser-based CAD tool. Turn the knob to zoom, hold a button and turn to orbit, tilt or pan, tap a button to undo, and hold one to open a wheel of modelling commands. What the knob does once the mode is on is described in [the Onshape feature page](../features/onshape.md). This page covers turning it on and how it decides when to act.

Onshape mode is tested on one knob (the author's) and one PC. It is the newest part of Desk Dial, so read the "Not yet verified" list at the end before you rely on it.

## What you need

- Desk Dial v2.0.0 running on the PC, with the knob connected and showing its Home screen.
- Onshape open in **Google Chrome** (tested). Microsoft Edge, Brave, Vivaldi and Opera are recognised, not yet tried; Firefox is not supported (see Limits).
- The knob's own screen running the current firmware (v2.0.0). The command wheel and the 3D cube only appear on a knob running it; an older knob can still zoom, orbit, tilt, pan and undo, but shows a plain text screen instead.

## Turn it on

1. Open Desk Dial's Settings from the tray icon.
2. Go to **Apps** and find the **Onshape** row. It has three choices: **Off**, **Manual** and **Auto**. If you used Onshape mode in an earlier version, your choice has carried over; otherwise it is Off.
3. Pick one. The Apps page applies it at once, with no Save.

The other apps on that page (Figma, Plasticity, Blender, AutoCAD) work the same way; see [Apps](../features/apps.md).

| Setting | What it does |
|---|---|
| **Off** | The knob never enters Onshape mode. Choosing Off while the mode is on leaves it. |
| **Manual** | You switch the mode on and off yourself from the tray icon's **App mode** menu, where Onshape has a toggle that is ticked while it is on. Nothing changes until you use it. |
| **Auto** | The knob enters Onshape mode by itself when an Onshape tab is the front window, and leaves half a second after Onshape is no longer in front, back to Home. |

In both Manual and Auto, the knob only sends input to Onshape while an Onshape window is in front and your mouse pointer is over the model (see below).

### The tray item

The tray's **App mode** menu lists the apps you set to Manual; with none, it shows "Set an app to Manual in Settings › Apps". If a toggle does nothing, it tells you why in a short message:

- "Turn Onshape on in Settings › Apps first." (the setting is Off);
- "Onshape needs the knob connected (firmware with the r3 screens)." (no knob, or an older knob);
- "Close the open screen on the knob first." (a list, the window picker or the seek screen is open on the knob; close it and try again).

Leaving the mode from the tray, or by holding all four buttons on the knob, is a deliberate exit. In Auto, Desk Dial then waits until Onshape has gone to the background and come to the front again before it enters by itself again, so the knob does not fight you.

## How Auto recognises an Onshape tab

Auto looks at the window in front, several times a second, and asks two questions:

1. **Is it a supported browser?** The program must be `chrome.exe`, `msedge.exe`, `brave.exe`, `vivaldi.exe` or `opera.exe`.
2. **Is it showing Onshape?** Either the window title's last segment is exactly "Onshape", or the browser's address bar shows an Onshape address. Desk Dial reads the address bar through Windows' accessibility interface (UI Automation) and keeps only the host part: `cad.onshape.com`, or a company workspace such as `yourcompany.onshape.com`. Onshape's marketing, learning, forum and status pages (`www.onshape.com`, `learn.onshape.com`, `forum.onshape.com` and similar) do not count.

Switching tabs inside one browser window is noticed too. Window titles and addresses are compared and dropped; they are never written to a log or a file.

The check runs only while some app is set to Auto or one is on. With every app Off or on Manual (and none on), Desk Dial reads nothing about the window in front.

## The pointer must be over the model

Every turn, drag, undo and wheel command is sent only when **the mouse pointer is over the Onshape page itself, inside the window that is in front**. The tab strip, the address bar and the bookmarks bar do not count, nor does any other window on top. If the pointer is somewhere else the knob refuses the input: it buzzes once, and its screen says **Point at the model** with the hint "Put the cursor on it". Move the pointer over the model and turn again.

Desk Dial never moves your pointer to find the model for you. During an orbit, tilt or pan it does move the pointer to make the drag, and puts it back where it started when the drag ends.

## Leaving Onshape mode from the knob

On every other screen, holding button 1 takes the knob Home. **In Onshape mode it does not**: button 1 is the tilt modifier. Instead, **press and hold all four buttons together for one second**. The second counts from the moment the fourth button goes down; let any of them go earlier and nothing happens. While three or more buttons are down, the knob sends nothing to Onshape, so pressing the four one after another never zooms, drags or undoes on the way. The knob's status line reads "Hold all 4 for Home" meanwhile.

In Auto, this counts as a deliberate exit (see "The tray item" above).

## Keyboard layout

The command wheel sends Onshape's keyboard shortcuts as Windows virtual keys: the letter and digit keys are sent as their US-layout positions, with Shift, Ctrl or Alt held where the shortcut needs it. On a US keyboard layout this matches Onshape's shortcut list. On other layouts a key may land on a different character, and Onshape may then run a different tool or nothing. This has not been checked on a non-US layout. The text that the wheel types into Onshape's tool search (for example the word "chamfer") is sent as Unicode characters and is layout independent.

## Not yet verified

These parts work in Desk Dial's own tests but have not been checked by eye in Onshape on real hardware:

- **Tilt direction.** Hold 1 and turn clockwise drags the mouse downwards, which should bring the top of the model towards you. If Onshape turns it the other way on your PC, say so in an issue.
- **Tool-search commands.** Chamfer, Shell and the whole Modify ring (Boolean, Split, Transform, Pattern, Mirror, Move face) are run by opening Onshape's tool search with Alt+C, typing the tool's name and pressing Enter. Whether the first hit is always the intended tool is not verified.
- **Number fields.** Parameter mode changes the number in an open dialog by sending mouse-wheel notches over the field, with Ctrl or Shift for the small and large steps. Whether the browser's own Ctrl+wheel page zoom ever wins over Onshape's field has not been checked.
- **A browser running as administrator.** Windows blocks input from a normal program into an elevated one. If your browser runs as administrator and Desk Dial does not, the knob's input would most likely be dropped; Desk Dial notices the short send and releases anything it was holding. Untested.

## Limits and known issues

- Chrome and Edge only. Firefox is deliberately not recognised: its tab strip and page share one window class, so a middle-button drag could land on a tab and close it.
- Only one Onshape window is tracked: the one in front.
- The address-bar check needs Chrome or Edge's address bar to be readable through UI Automation. If a browser update changes it, Auto falls back to the window title, which Onshape rarely sets to "Onshape". If Auto never enters although Onshape is in front, use Manual.
- There is no indicator on the PC that Onshape mode is on besides the tray item's text. The knob's own screen shows it.
- A drag (orbit, tilt or pan) is released after 800 ms without a turn, and the pointer cannot be dragged past the edge of the screen. See the feature page's Limits.
- Not yet tested on real hardware: the items under "Not yet verified" above.
