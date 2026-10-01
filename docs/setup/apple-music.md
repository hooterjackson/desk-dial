# Set up Apple Music

Desk Dial can show your Apple Music library on the knob: the albums and playlists you added recently, your favourite playlists, and a Like button for the song that is playing. The music itself still plays through your Sonos speaker. Apple Music only supplies the library and the covers.

This guide takes you from nothing to a signed-in knob. Set up Apple Music **before** Home Assistant (see [Limits and known issues](#limits-and-known-issues) for why).

## What you need, and what it costs

Apple does not let a desktop app read your library with just your Apple ID. It requires the developer route, which has two paid parts:

- **An Apple Developer Program membership**: 99 USD per year (price checked on developer.apple.com, 30 September 2026). This is what lets you create the signing key below. Desk Dial does not receive any of this money.
- **An Apple Music subscription** on the same Apple ID. Without it, your library is empty and the sign-in page cannot grant access.

You also need a web browser on the PC. The sign-in page runs there.

Why so much ceremony? Apple's MusicKit works with two tokens. A *developer token* proves that an app is allowed to talk to Apple Music; Desk Dial signs it on your PC with a private key that only a Developer Program member can create. A *user token* proves that *you* agreed to let that app see your library; Apple issues it after you consent in the browser. Desk Dial needs both.

## Step 1: Create a Media ID and a MusicKit key

Do this once, in your browser, signed in to your developer account.

1. Open **Certificates, Identifiers & Profiles** on developer.apple.com.
2. Under **Identifiers**, add a new identifier of type **Media IDs**. Give it any description and a reverse-domain style identifier (for example `media.example.deskdial`). Enable **MusicKit** on it and register it.
3. Under **Keys**, add a new key. Tick **Media Services (MusicKit, …)**, choose the Media ID you just made, and continue.
4. Download the key. It is a small text file ending in **.p8**. Apple lets you download it **once**; if you lose it you must create a new key. Keep it somewhere private.
5. Note two 10-character codes:
   - the **Key ID**, shown next to the key you created;
   - your **Team ID**, shown at the top right of the Membership page.

Desk Dial checks that the Team ID and Key ID are exactly 10 letters or digits and that the file contains a private key. It does not contact Apple at this point.

## Step 2: Enter the key in Settings › Music

1. On the PC, right-click the Desk Dial icon in the tray and open **Settings**, then the **Music** page.
2. Type your **Apple Team ID** and **MusicKit Key ID**.
3. Press **Choose .p8 key** and pick the file you downloaded.

The small note beside the button says "Key and token are protected locally with Windows". That is where they go, and nowhere else (see [Where your credentials live](#where-your-credentials-live)).

## Step 3: Authorize Apple Music

1. Press **Authorize Apple Music** at the bottom of the Music page. The Settings window says "Complete Apple Music authorization in your browser."
2. Your browser opens a page titled **Connect Apple Music · Desk Dial**. The address starts with `http://127.0.0.1:` followed by a port number. That address is your own PC; the page is served by Desk Dial itself and is not reachable from any other machine. It stays valid for 15 minutes and accepts one sign-in.
3. The page states what you are allowing: Desk Dial may read your Apple Music library and may mark songs as Favourites when you press Like, and a Favourite can add the song to your library. The page loads Apple's MusicKit script from Apple's servers; this is the only outside connection it makes.
4. Press **Authorize Apple Music**. Apple shows its own sign-in and consent dialog. Sign in with the Apple ID that has the Apple Music subscription.
5. When Apple finishes, the page says "Connected. You can close this tab and return to the knob companion." The user token travels from the browser straight back to Desk Dial on your PC. Nothing is sent to anyone else.

If the page says "Apple Music could not initialize. Check your MusicKit setup in the companion app", the Team ID, Key ID or key file do not match. Check them and press Authorize again.

**You should see** in Settings: the Apple Music column at the top of the window turns to **Signed in · Library and likes available**.

**You should see** on the knob: from Home, tap **button 1** (Music), then **button 2** (Recent). The **Recently Added** list fills with your albums and playlists, with their covers, newest first.

<picture><source srcset="../media/music-lists.webp" type="image/webp"><img src="../media/music-lists.gif" alt="The knob's round screen showing the Recently Added list: album covers stacked in a scrolling list, the knob turning through them" width="480"></picture>

## What Apple Music is used for

Once signed in, these parts of Desk Dial work:

- **Recently Added** and **Playlists** on the knob and in the full-screen explorer on the PC.
- **Play** and **Play next** from those lists (Desk Dial looks up each song in Apple's catalogue so Sonos can play it).
- **Like** in the Up next screen.
- Covers in the Up next screen.

Playing, pausing, volume, seeking and the queue work without Apple Music, because they talk to the Sonos speaker directly.

## Where your credentials live

Everything Apple-related is stored in one file on the PC:

`%LOCALAPPDATA%\DeskDial\data\credentials.bin`

It holds the text of your .p8 key, your Team ID and Key ID, and the Apple Music user token. The file is encrypted with Windows Data Protection (DPAPI) for your Windows user account only. In one sentence: any program running as *your* Windows user while you are signed in can ask Windows to decrypt it, but another user account, another PC, or someone who copies the file cannot.

Desk Dial never writes keys or tokens to its log files, and the plain-text `settings.json` next to it never contains them.

To remove them, quit Desk Dial and delete `credentials.bin`. You can also revoke the key on developer.apple.com, which makes the stored key useless.

## Tokens, expiry and "Sign-in expired"

- The **developer token** is signed on your PC each time it is needed and is valid for one hour. Apple allows at most six months, but Desk Dial deliberately keeps it short. You never see or manage it.
- The **user token** is Apple's. Apple decides when it stops working; this typically happens after months, or at once if you change your Apple ID password or revoke the app's access.

When Apple refuses the user token, Desk Dial shows **Sign-in expired** in the Settings strip, with the note "Like and Favourite playlists are paused until you sign in again." On the knob, the Recently Added list shows **Apple Music sign-in expired · Renew on your PC**, and a Like press is refused with the same message. Open Settings › Music and press **Authorize Apple Music** again; you do not need to choose the key file again, Desk Dial reuses the stored one.

## Limits and known issues

- **The only thing Desk Dial writes to Apple Music is Like.** It adds the song to your Favourites. There is no Unlike: Apple refused that request for this kind of sign-in, so Desk Dial does not even contain the code for it. On a song you already liked, the knob says **Unfavourite in Music app**; do it there.
- **Re-authorising with a new .p8 key clears the saved Home Assistant token.** Choosing a key file and pressing Authorize replaces the whole credential file with the new Apple credentials, so a Home Assistant token stored there is lost and you must enter it again in Settings › Home Assistant. Pressing Authorize *without* choosing a new key file keeps everything. Set up Apple Music first, then Home Assistant.
- **Apple's consent page needs an internet connection** to load Apple's MusicKit script. If the page says "Apple Music could not load", check your connection and retry.
- **One account per PC.** Desk Dial stores one set of Apple credentials. Authorising with another Apple ID replaces the first.
- **Windows only.** The encrypted store uses Windows DPAPI; there is no equivalent on other systems.
- The project is tested on one knob (the author's) with one Apple Music account.
