# Nano_D++ r2.1: follow-up 1 from engineering

Thank you for r2.1: we're building from it now. Four things surfaced after r2.1 that need a design decision. Please send a small **r2.2** covering only these, with the changelog in the same style. Everything else in r2.1 stands.

## 1. Like is add-only (Apple's rule, verified live)
- **What we tested.**
  - On the user's account, the knob can **add** a favourite (`POST /v1/me/favorites`). It reaches the iPhone within seconds.
  - It **cannot remove one.** The documented removal clears Apple's server but never reaches the user's devices.
  - Apple's own web-player removal is refused for third-party apps, with 400 "Insufficient Permissions".
  - Apple Support (article 111118) confirms that third-party apps can't remove favourites.
- **What we need from you.**
  - **Up next, button 3 on a row that's already liked.** Our proposal: the heart stays filled pink and button 3 dims to the "already liked" state. A press shows the reason `Unfavourite in the Music app` with a Head shake. Please confirm or redesign this, including the knob meta copy (12 px, ≤ 170 px), the button LED (pink at 0.30 or 0.14?), and the row's heart.
  - **Remove the unlike moment**, and any "heart turns off" animation.
  - **Show the three row-heart states distinctly:** liked (filled), not liked (outline), and not known yet (your "not known yet" outline), plus the dimmed heart for non-catalog rows.

## 2. Copy approval pass
Engineering added these strings for states r2.1 leaves without copy. Please approve each one or rewrite it within its limit. Knob meta and sub lines are 12 px and ≤ 170 px; sub lines at 14 px are ≤ 170 px; status lines are ≤ 160 px.

| Where | Proposed text | Why |
|---|---|---|
| knob meta | `Can't seek · no length` | queue item with an unknown or over-long duration |
| knob meta / Home status | `Sonos unavailable` | explorer opens with Play dimmed while Sonos is down |
| knob meta | `Not available` | unplayable list item |
| knob meta | `Queue changed` (shortened from `Queue changed · order kept`, which overflowed) | shuffle-off restore refused because the queue changed |
| knob meta | `Didn't shuffle · try again` | shuffle failure |
| knob meta | `Nothing to shuffle` | fewer than 2 upcoming songs |
| knob meta | `Didn't save · try again` | Like failed (rate limit or server error) |
| knob meta | `Starting…` / `Pausing…` / `Shuffling…` | reason for a press dimmed because an action is still running, in modes where the busy line isn't visible |
| knob meta / title | `Library not loaded` | Apple Music library failed to load |
| knob sub (14 px) | `Home, then Browse` (shortened from `Home, then Browse to retry`, which overflowed) | retry hint under that title |
| knob meta | `Sign-in expired` | Apple Music sign-in expired, in a list |
| knob meta / Home status | `Group changed` | the Sonos group changed during an action |
| knob meta | `Can't open on screen` | the PC refused to open an overlay (busy or GPU error) |
| toast | `… · {u} songs unavailable` | plural form of the partial-playlist toast |
| explorer | `Nothing recently added` / `Add an album or a playlist to your library in the Music app.` | empty Recently Added tab |
| explorer | `Library not loaded` / `Go Home, then Browse to retry.` | explorer error state |
| explorer | `Apple Music sign-in expired` / `Open Settings on your PC to sign in again.` | sign-in expired with nothing cached, on either tab |
| knob idle row, slot 1 | `Play` / `Pause` (follows the icon) | `Play/Pause` can't fit the 46 px idle-row column |
| knob meta | `Unfavourite in the Music app` | new, see §1 |

## 3. Seek timing on the real system
- **Each jump takes about 2.7 s** before Sonos plays again, with near-silence meanwhile. We had estimated 0.5–2 s. Sonos also reports the new position before it has finished buffering.
- **So `Jumping…` can be on screen for up to about 5 s.** Please confirm the knob holds the frozen target time and `Jumping…` for that long, and say whether the ring shows the Working comet meanwhile. We propose yes.
- **Several quick turns** still send only one jump, 250 ms after the last detent.

## 4. Play next timing
- **What we measured.** Inserting takes about 0.5 s per song. Looking an album's songs up in Apple Music first takes 3–6 s when uncached, and we now pre-load the focused item and its neighbours.
- **So a full album takes a few seconds**, and `Queueing… k of n` will be visible for 1–10 s. No change is needed if the design is happy with that; tell us if you want a different treatment for the first second or two, before k counts up.
