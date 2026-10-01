# Set up the window picker

The window picker shows your open windows as live previews on the screen. Turn the knob to browse them, tap a button to switch, or snap two windows side by side. It needs nothing beyond Desk Dial itself.

Tested on one knob and one PC (the author's). Version {{RELEASE}}.

<picture><source srcset="../media/desktop-picker-16x9.webp" type="image/webp"><img src="../media/desktop-picker-16x9.gif" alt="A row of live window previews slides across a frosted desktop as the knob turns; the centre one grows and its name appears under it" width="480"></picture>

## Nothing to install

The picker uses features Windows already has: live window previews drawn by Windows itself, Windows' own snap-to-half window placement and a global keyboard shortcut. Desk Dial is portable and runs from its folder; there is no driver, service or browser extension.

## How it opens

1. On the knob's Home screen, tap **button 2** (its label reads "Win").
2. The picker appears on the monitor that holds the window you were working in.
3. It opens on the window you used just before the current one, so one tap of button 4 switches back to it.

The picker opens from Home only. From Music or Lights, hold button 1 to go Home first.

What happens under the hood: when you tap button 2 on Home, the knob types a key that no keyboard has, **F24**. Desk Dial has asked Windows to treat F24 as a global shortcut. Windows lets an application come to the front when the user presses its shortcut, which is why the picker can take the foreground and your typing (Enter, Esc, arrows) while it is open. A message over the USB cable alone would be refused focus.

## Using it

| Button | Action |
| --- | --- |
| Turn | Browse the windows. The list has firm stops at each end and no wrap-around. |
| Button 1 | Home (closes the picker without switching) |
| Button 2 | Snap the centre window to the left half |
| Button 3 | Snap the centre window to the right half |
| Button 4 | Switch to the centre window |

Snapping: tap button 2 on one window and the knob says "Left: App · pick right". Browse to another and tap button 3. Both windows are placed side by side on that monitor and the picker closes on its own.

The keyboard works too while the picker is open: arrows or the mouse wheel browse, Enter or a click on the centre card switches, Esc closes.

The picker closes by itself after 60 seconds without input, and at once if another window takes the front.

## If the knob says "F24 is unavailable"

Settings shows "F24 is unavailable · close the conflicting hotkey app" when another program has already registered F24 as its shortcut. Windows allows one owner per shortcut, so Desk Dial cannot open the picker until that program lets go.

To find it:

1. Think of programs that register keyboard shortcuts: keyboard and mouse utilities, macro tools, streaming or screen-recording tools, remote-desktop helpers, and other knob or dial companions.
2. Quit them one at a time. After each, unplug and reconnect the knob (Desk Dial registers F24 each time the knob connects) and watch the Knob line in Settings.
3. When the status reads "Knob ready", the last program you quit was the owner. Change its shortcut away from F24, or stop it from starting with Windows.

Everything else on the knob works while F24 is taken; only the picker is affected.

## What the picker lists

Ordinary application windows with a title, including minimised ones. It leaves out tool windows, hidden and cloaked windows, the desktop and taskbar, and Desk Dial's own windows. When nothing qualifies the knob reads "No eligible windows".

## What cannot be snapped

- **Windows running as administrator.** Windows does not let a normal program move a window of a program with higher rights. The knob says "Couldn't move App" and the window stays where it was.
- **A window that is not responding** ("App not responding").
- **A window whose smallest size is wider than half the screen** ("App can't fit half").
- If a switch fails to bring the window forward, the knob says "Didn't come forward · retry"; if the window closed while the picker was open, "Closed · can't switch".

## Monitors

The picker opens on the monitor holding the window that was in front when you pressed, and snaps to that monitor's two halves (the taskbar is left uncovered).

On a 16:9 monitor you see the centre window and two on each side. On a 32:9 ultrawide the cards are smaller and you see four on each side.

<picture><source srcset="../media/desktop-picker-32x9.webp" type="image/webp"><img src="../media/desktop-picker-32x9.gif" alt="On an ultrawide monitor the picker shows nine window previews in a row, four either side of the centre one" width="480"></picture>

## Settings

**Settings › Windows › Switcher background:** *Frosted* (the default) blurs the whole screen behind the previews; *No background* dims it instead. On a PC that does not allow the window mode the frost needs, only Frosted is offered and a note says so. Applies as soon as you click Save.

**Settings › General › Motion:** *Match Windows* follows the Animation effects switch in Windows Settings › Accessibility › Visual effects; *Full* and *Reduced* force it either way. With reduced motion the previews jump into place and only fade, there is no slide when the picker opens and no flying preview when you snap. Applies when you click Save; the knob's own animations follow the same choice.

## Limits and known issues

- One global shortcut (F24) shared with every other program on the PC; another owner blocks the picker.
- Windows running as administrator can be switched to but not snapped.
- Window titles are read when the picker opens, shown on the knob over the USB cable and never written to the logs.
- Tested on one PC. Multi-monitor setups with mixed scaling have not been tried.
