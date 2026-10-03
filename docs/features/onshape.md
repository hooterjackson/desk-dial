# Onshape mode

In Onshape mode the knob is a 3D mouse for Onshape, the browser-based CAD tool: the knob alone zooms, each of three buttons turns it into orbit, tilt or pan, one tap undoes, and one hold opens a wheel of modelling commands drawn on the knob's own screen. Desk Dial sends ordinary mouse and keyboard input to the browser; Onshape itself is not changed and needs no plug-in.

Onshape is one of the apps on [Apps](apps.md): set it to Manual or Auto in Settings › Apps. Turning it on, and the rules for when the knob acts, are in [the setup page](../setup/onshape.md). In short: Chrome or Edge, Onshape in front, and the mouse pointer over the model.

<picture><source srcset="../media/onshape-knob.webp" type="image/webp"><img src="../media/onshape-knob.gif" alt="The knob's screen in Onshape mode: a wireframe cube turns as the knob turns, with the labels TILT, ORBIT, WHEEL and PAN under the four buttons; holding button 3 brings up a ring of commands" width="480"></picture>

Onshape mode is tested on one knob (the author's) and one PC. Some parts are not yet checked by eye in Onshape; they are listed at the end.

## The buttons

The buttons are numbered 1 to 4 from left to right.

| Input | What happens |
|---|---|
| Turn the knob | Zoom (mouse-wheel notches; one full turn is 24 of them). |
| Hold 1 and turn | Tilt: the view pitches up and down (a right-button drag up and down the screen). |
| Hold 2 and turn | Orbit: the view spins left and right (a right-button drag across the screen). |
| Hold 4 and turn | Pan: the view slides sideways (a middle-button drag across the screen). |
| Tap 3 | Undo (Ctrl+Z). |
| Hold 3 | The command wheel (below). |
| Hold all four buttons for 1 s | Home: leaves Onshape mode. |

Tilt, orbit and pan use Onshape's default mouse preset: right-drag rotates, middle-drag pans. If you have changed the mouse controls in Onshape's preferences, the knob follows your preset, not these names.

Some details worth knowing:

- A drag begins on the first click of the knob after the button goes down, and ends when you let the button go. The pointer then jumps back to where it was.
- Hold two modifiers and the newest one wins: 1 then 2 orbits; release 2 and the knob tilts again.
- Holding button 1 does **not** go Home here, unlike every other screen. Tapping button 1 alone does nothing; the screen reminds you to hold all four for Home.
- Undo is skipped while you are physically holding Shift, Ctrl, Alt or the Windows key, so Ctrl+Z never turns into a different shortcut.
- One full turn moves the pointer about 760 pixels during a drag, whatever your screen's size.

## The command wheel (hold 3)

Press and hold button 3. After a quarter of a second, or as soon as you turn, a ring of commands appears on the knob's screen. Turn to move the highlight along it, one entry per twelfth of a turn; the first position is Cancel and the ring stops at both ends. Let go of 3 to run the highlighted command. The knob then replays a short animated card of what the command does for about a second (the echo).

There are four rings. While the wheel is open, button 1 steps between the Model and Modify rings, button 2 opens the Sketch ring and button 4 the View ring. Each ring remembers the entry you last ran, so hold 3 and release without turning repeats it.

| Ring | Commands and the shortcut Desk Dial sends |
|---|---|
| **Model** | Sketch (Shift+S) · Extrude (Shift+E) · Revolve (Shift+W) · Fillet (Shift+F) · Chamfer and Shell (tool search) |
| **Modify** | Boolean · Split · Transform · Pattern ("linear pattern") · Mirror · Move face (all tool search) |
| **Sketch** | Line (L) · Rectangle (G) · Circle (C) · Arc (A) · Dimension (D) · Trim (M) · Construction (Q). These single letters only work while a sketch is open in Onshape. |
| **View** | Front (Shift+1) · Right (Shift+4) · Top (Shift+5) · Isometric (Shift+7) · Normal to (N) · Zoom to fit (F) · Section (Shift+X) |

"Tool search" means Desk Dial opens Onshape's search box with Alt+C, types the tool's name, waits a moment and presses Enter. Onshape has no direct shortcut for these tools. Whether the first search hit is always the right tool has not been verified.

Opening the wheel while 1, 2 or 4 is held (while tilting, orbiting or panning) does nothing. Pressing a third button closes the wheel without running anything, because that is the start of the Home chord.

## Parameter mode

Six commands open a dialog with a number in it: Extrude (depth), Fillet (radius), Chamfer (distance), Shell (thickness), Transform and Move face (distance). After one of these the knob stays on the dialog and turns the number until you end it with button 3.

Step sizes follow Onshape's own number fields: **0.1 per step** with the knob alone, **0.01** while button 1 is held, **1.0** while button 4 is held. One step is a sixteenth of a turn (a forty-eighth for the fine step).

There are two ways to apply the change, and button 2 switches between them (the choice is remembered):

- **A (scroll, the default):** each step is one mouse-wheel notch over the number field, with Ctrl or Shift held for the small and large steps. The knob shows the change so far, for example +0.30. Your pointer has to be over the number field.
- **B (type):** the knob holds the value itself, starting from the command's default (25 for depth, 1 for radius, and so on) and clamped to a sensible range; the screen nudges when it hits an end. Once the knob rests for a third of a second Desk Dial selects the field (Ctrl+A) and types the value, for example 27.50.

Tap 3 to confirm (Enter). Hold 3 for more than 0.6 s and let go to cancel (Escape). Buttons 1, 2 and 4 never drag in parameter mode.

## What the knob's screen shows

The Onshape screen on the knob is Karl Malota's design, adapted with his permission from his own firmware branch: the wireframe cube, the animated command cards, the ring, the parameter screen, the idle "plasma" and the Silkscreen pixel font.

- **The cube** follows the knob's shaft directly, from the knob's own angle sensor, with no round trip through the PC: it spins while you orbit, pitches while you tilt, slides while you pan and grows while you zoom. When you let go of orbit or tilt it eases back to a clean isometric pose over about a fifth of a second. The cube is a picture of the knob's movement, not a copy of your model.
- **The legend** under the buttons reads TILT · ORBIT · WHEEL · PAN. A held button lights its label.
- **Undo** flashes the screen briefly.
- **Point at the model** appears for two seconds when the pointer was not over Onshape and the input was refused.
- **The idle plasma**: after five seconds without input the screen drifts into a slow colour ripple around the Onshape icon, in teal, green and lime. Any input ends it.

## Feel and sound

- Zooming has smooth, soft clicks, the same feel as the music volume. There are no end stops: zoom is unlimited in both directions.
- While a modifier button is held (1, 2 or 4) the clicks disappear and the knob turns with a light, fluid resistance, so a drag feels like a continuous motion. The clicks return when you let go.
- Undo gives a short tick. A refused input (pointer off the model) gives a buzz, at most once a second.
- The wheel and parameter mode have no clicks of their own and no end stops in the motor; the highlight simply stops at the end of a ring.

## Limits and known issues

- **Chromium browsers only.** Tested in Chrome; Edge, Brave, Vivaldi and Opera are recognised, not yet tried. Firefox is deliberately not supported: its page and tab strip share one window class, so a middle-button drag could land on a tab and close it.
- **Drags end on their own after 800 ms without a turn**, and the pointer cannot be dragged past the edge of the screen: a long orbit may stop at the screen edge and start again from where the pointer was.
- **Hold 3 and release repeats a command.** Once the wheel has shown (after about a quarter of a second), letting go runs whatever is highlighted, which is the command you last ran in that ring. If you only wanted Undo, tap 3 quickly instead.
- **Elevated browser untested.** If the browser runs as administrator and Desk Dial does not, Windows blocks the input.
- **Keyboard layouts.** Shortcuts are typed for the keyboard layout of the window in front; a shortcut whose key that layout lacks is not sent, and the knob says "Not on this keyboard". Not yet tried on a non-US layout on real hardware.
- **Not yet checked on real hardware:** the direction of tilt, whether each tool-search phrase lands on the right tool, and whether the browser's Ctrl+wheel page zoom ever wins over the number field in parameter mode A.
- **Numbers are metric.** Parameter mode B's starting values (depth 25, radius 1) assume a document in millimetres.
- **The wheel and the cube need the current firmware.** On an older knob Onshape mode still zooms, drags and undoes, but button 3 is Undo only and the screen is plain text.
