# Desktop companions

Desk Dial lives in the Windows tray. Most of the time the knob's own screen is all you look at, but three things can appear on your monitor: the Navigator, a small glass card that mirrors the knob; two full-screen music overlays (the Music explorer and Up next); and short toasts. None of them ever takes keyboard focus away from what you are doing.

A detent is one click of the knob. The buttons are button 1 to button 4, left to right.

## The Navigator

The Navigator is a compact card, 250 units wide, at the left edge of your primary monitor, vertically centred. It is drawn as frosted glass over whatever is behind it. It is click-through: the mouse goes straight past it to the window underneath, and it never takes focus.

<picture><source srcset="../media/navigator.webp" type="image/webp"><img src="../media/navigator.gif" alt="A narrow frosted card slides in from the left edge of the desktop; it reads Lights › Studio, shows a brightness bar and a temperature bar, and a 2 by 2 grid of the four button words" width="480"></picture>

### What it shows

Every card has three parts: the path at the top (where you are on the knob), the content for that screen, and a 2 x 2 grid with what buttons 1 to 4 do right now.

| Knob screen | Path | Content |
| --- | --- | --- |
| Home | Home | The playing song's cover, title and artist, a status line, and a volume bar that lights while you turn |
| Home with the knob on brightness (hold 4) | Home › Studio | The Lights card |
| Music | Music | The same now-playing card |
| Recently Added | Music › Recently Added | A fan of covers with the chosen album in front |
| Playlists | Music › Playlists | The same, with the playlist's cover mosaic |
| Tracks | Music › Tracks | Five rows of the queue centred on the chosen one, the playing row marked with a note |
| Seek | Music › Tracks › Seek | The position being set |
| Lights | Lights › Studio | A brightness bar and a temperature bar; the scene's name; per-light rows only when the lights differ or one is unavailable |
| Scenes | Lights › Studio › Scenes | The scene rows with their kind (Scene, Script, Automation) |
| Windows picker, Music explorer, Up next | – | Hidden: these have their own screen |
| Onshape | – | Hidden: no card yet |

Under the grid sits the HOLD row: small chips for the holds that exist on this screen. "1 Home" appears on screens two levels down (Recently Added, Tracks, Scenes), and "4 Queue", "4 Play next", "4 Knob to lights" or "4 Knob to music" where hold 4 has an action. While you hold the button, the chip fills up over the hold's length: 0.6 s for button 1, 1 s for button 4. A tap flashes its key white.

### When it shows

The Navigator appears on any turn or press. On Home, Music and Lights it slides out 4 seconds after your last input. On the list screens (Recently Added, Playlists, Tracks, Seek, Scenes) it stays for 20 seconds, so you can browse without it blinking. It is hidden while the window picker, the Music explorer or Up next is open, and while the knob is disconnected.

Settings › General › Navigator has three choices: Auto-hide (the default, as above), Pinned (always on screen while the knob is connected) and Off.

### The glass

The blur behind the card is a snapshot of the desktop under it, not a live blur. It is captured when the card shows, refreshed every 2 seconds while the card is up, and only redrawn when the picture actually changed. If you drag a window under the Navigator, the glass follows a beat later.

## The Music explorer and Up next

Two music screens are too big for the knob and open on the monitor instead: the Music explorer (tap 2 on Recently Added: your albums and playlists as a wall of covers) and Up next (tap 2 on Tracks: the queue). Both are described in [music.md](music.md); here is only how they behave on the desktop.

- They cover the monitor, but never take focus. Your keyboard keeps typing into whatever app was active.
- A click on the centre card (explorer) or on the highlighted row (Up next) acts like a press of button 4; any other click, right-click or wheel turn on the overlay is swallowed.
- Tap 4 to play: the overlay closes 380 ms later and the knob goes Home with "Starting…".
- Hold 1 closes the overlay and goes Home. An overlay also closes after 60 seconds without knob input, when the PC locks or sleeps, and when the knob disconnects.
- The Navigator is hidden while either is open.

<picture><source srcset="../media/desktop-explorer-16x9.webp" type="image/webp"><img src="../media/desktop-explorer-16x9.gif" alt="A wall of album covers across the monitor, the centre one large with its title and artist below; a knob turn slides the row sideways" width="480"></picture>

## Toasts

Some actions end with a short toast on the PC: "Playing Morning Mix", "Queued next · Blue Hours", "Side by side · Mail and Notes", "Lights · Evening", "Couldn't run Evening". Toasts never take focus either.

## The tray

Desk Dial's icon sits in the tray. The tooltip reads "Desk Dial · Knob connected" or "Desk Dial · Knob not found". A left click shows the knob (see below). A right click opens the menu, top to bottom:

| Item | What it does |
| --- | --- |
| Knob connected / Knob not found | Header, not clickable |
| Status line | The current detail, for example "Knob ready · installed profiles active" or "F24 is unavailable · close the conflicting hotkey app". Not clickable |
| Show knob | See the next section |
| Open Settings… | Opens the Settings window |
| Connect knob / Disconnect knob | Attaches to or releases the knob's USB port |
| App mode › | A submenu listing every app (ticked while it is on); picking one turns it on or off if it is Manual or Auto in Settings › Apps. See [Apps](apps.md) |
| Quit | Stops Desk Dial. Closing Settings does not quit; only this does |

<img src="../media/app-icons.png" alt="The Desk Dial app icon and the tray icon in its dark and light variants at 16, 20, 24 and 32 pixels" width="480">

## The floating knob (older firmware only)

Earlier builds of Desk Dial drew a floating picture of the knob on the desktop: its screen and LED ring, mirrored live. With the current firmware the Navigator stands in for it, and the floating knob is held hidden for as long as the knob is connected.

Two honest notes about that:

- No setting brings the floating knob back. Settings › General › Navigator › Off hides the Navigator card, but the floating knob stays hidden too.
- The tray's "Show knob" item (and a left click on the tray icon) peeks the floating knob for 2.5 seconds. With the current firmware it does nothing you can see.

The floating knob still appears for a knob running an older Desk Dial firmware that does not have the navigation the Navigator mirrors.

## Limits and known issues

- The Navigator is always on the primary monitor's left edge; its position cannot be changed.
- There is no Navigator card for Onshape mode.
- The glass behind the Navigator is a snapshot refreshed every 2 seconds, so it lags a moving window.
- "Show knob" does nothing visible with the current firmware, and Navigator › Off leaves you with no mirror of the knob at all.
- The Music explorer and Up next cover one monitor; they do not span several.
- Tested on one knob and one PC (the author's).
