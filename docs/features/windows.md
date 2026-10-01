# Windows

The window picker puts live previews of your open windows on the screen, in a row you turn through with the knob. Switch to one, or snap two side by side, without touching the mouse.

A detent is one click of the knob. The buttons are button 1 to button 4, left to right.

## Opening the picker

From Home, tap 2. The knob sends Windows the F24 key; Desk Dial has registered that key as a hotkey, and a hotkey is the only way Windows lets a background program bring a window to the front. That is why the picker opens only from Home, and only while the knob is connected.

The picker appears on the monitor you are working on: a frosted band across the screen with window previews on it. The window you came from sits in the middle.

<picture><source srcset="../media/desktop-picker-16x9.webp" type="image/webp"><img src="../media/desktop-picker-16x9.gif" alt="A frosted band across a 16:9 monitor with five window previews, the middle one large and sharp, two smaller ones fading out on each side; the band scrolls as the knob turns" width="480"></picture>

## Buttons on the picker

| Button | Tap | Hold |
| --- | --- | --- |
| 1 | Home: close the picker and go back to the window you came from | Home (the same) |
| 2 | Snap left: put the chosen window on the left half | – |
| 3 | Snap right: put the chosen window on the right half | – |
| 4 | Switch to the chosen window | – |

## Turning through the windows

Each click moves the highlight one window. The knob uses coarse clicks, 12 per turn, with a wall at each end of the row; the row does not wrap.

The previews are live: Windows draws each one from the real window, so a video keeps playing and a terminal keeps scrolling inside its card. Under each card you see the app's name and the window's title. Two windows of the same app get a longer label so you can tell them apart.

A window that closed while the picker was open stays in the row marked "Closed · can't switch"; buttons 2 to 4 are dimmed on it.

## Switch

Tap 4. The chosen window comes to the front, the picker closes, and Home shows "Switched to Mail" for a couple of seconds. A toast on the PC reads the app and the window's title.

If Windows refuses to bring the window forward, the picker stays open with "Didn't come forward · retry".

## Snap left and Snap right

Tap 2 to put the chosen window on the left half of the monitor. The card is washed with the window's colour, the button lights up, and the line reads "Left: Mail · pick right". If you do not turn the knob, the highlight advances by itself to the next window that is not yet snapped, so the second snap is one more tap.

Tap 3 on another window for the right half. Once both halves are set, the picker closes on its own and a toast reads "Side by side · Mail and Notes".

If you snap one side and then tap 1 to go Home, the window you came from fills the other half, so you still end up with a pair.

Three things can stop a snap, each with its own line on the knob:

| On the knob | Why |
| --- | --- |
| Mail not responding | Windows reports the app as hung. |
| Couldn't move Mail | The window refused the move. Windows running as administrator cannot be moved by a normal program, so they show this. |
| Mail can't fit half | The window has a minimum size larger than half the monitor; it was placed but kept its size. |

A failed snap frees the side again, with a short red flash.

## Wide monitors

On a 16:9 monitor the picker shows two cards on each side of the centre. On a 32:9 monitor there is room for four on each side.

<picture><source srcset="../media/desktop-picker-32x9.webp" type="image/webp"><img src="../media/desktop-picker-32x9.gif" alt="The same frosted band on a 32:9 ultrawide, nine previews across, four shrinking away on each side of the centre card" width="480"></picture>

## Frosted or no background

Settings › Windows › Switcher background has two choices. Frosted (the default) blurs the whole screen behind the cards. No background shows the cards and their labels straight over your desktop. If this PC does not allow the window mode that No background needs, Settings says so and the picker keeps Frosted.

## Closing

The picker closes when you Switch, when both halves are snapped, on tap or hold of 1, after 60 seconds without any knob input, when another program takes the foreground, and when the PC locks or sleeps. Closing with button 1 or by idling gives focus back to the window you came from; a lock or sleep does not.

## When the key is taken

If another program has already claimed F24 as its hotkey, Desk Dial cannot open the picker. The tray's status line reads "F24 is unavailable · close the conflicting hotkey app". Quit that program (or change its hotkey) and reconnect the knob from the tray.

## Limits and known issues

- The picker opens from Home only.
- Snap places windows on the monitor the picker is on, in two equal halves; there are no quarters or thirds.
- Windows running as administrator can be switched to but not snapped ("Couldn't move").
- Windows with a large minimum size are moved but not resized ("can't fit half").
- F24 must be free. A program that binds every function key will block the picker.
- Window titles are read when the picker opens and shown on the knob over USB; they are not written to the log.
- Tested on one knob and one PC (the author's).
