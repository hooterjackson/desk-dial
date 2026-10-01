# Set up Home Assistant

The knob's **Lights** screen controls the lights of one room through Home Assistant: brightness and colour temperature by turning, scenes by button. This guide connects Desk Dial to your Home Assistant and picks that room.

If you also use Apple Music, set that up **first** (see [Limits and known issues](#limits-and-known-issues)).

## What you need

- A running Home Assistant on your network, reachable from the PC.
- Your lights assigned to an **Area** in Home Assistant (Settings › Areas, labels & zones). Desk Dial controls one area.
- A long-lived access token from your Home Assistant profile (created in step 1).

## Step 1: Create a long-lived access token

1. In Home Assistant, click your user name at the bottom left to open your profile, then the **Security** tab.
2. Scroll to **Long-lived access tokens** and press **Create token**. Name it, for example, "Desk Dial".
3. Copy the token now. Home Assistant shows it once.

The token acts as you. Desk Dial only uses it for lights, scenes, scripts and automations (see [What Desk Dial does in your Home Assistant](#what-desk-dial-does-in-your-home-assistant)), but anyone holding the token could do anything your account can. Treat it like a password.

## Step 2: Enter the address and token

On the PC, right-click the Desk Dial icon in the tray, open **Settings**, then the **Home Assistant** page.

**Address.** Type the address you use in your browser, in the form `http://host:port` or `https://host:port`. The field suggests `http://homeassistant.local:8123`, which is the default for a standard installation. Any path prefix is allowed; a user name, password, `?` or `#` in the address is refused. Examples:

- `http://192.0.2.10:8123`
- `https://ha.example.net`

**http or https?** Prefer https when your Home Assistant offers it. Over plain http the token travels across your local network unencrypted on every request, and Desk Dial does not warn you about this yet. Over https, Desk Dial checks the certificate like a browser does: a certificate from a public authority (for example through Nabu Casa or Let's Encrypt) works, but a self-signed certificate will very likely be rejected and the test will report that it cannot reach Home Assistant. There is no setting to skip the check.

**Long-lived access token.** Paste the token. The field hides it; **Show** reveals it while you check. Once saved, a token is never shown again; the caption changes to "saved (leave empty to keep it)".

## Step 3: Test connection, choose the Area, Save

1. Press **Test connection**. Desk Dial reads your Home Assistant without changing anything.
2. The status line shows **Connected · Home Assistant <version> · token valid**, and the **Area** menu lists your areas with their light count, for example "Study · 3 lights".
3. Choose the area the knob should control. Below, two lists show what you picked: **Lights in <area>** with each light's state, and **Scenes, scripts and automations**.
4. Press **Save**. Save is only enabled after a successful test. The token goes into the encrypted credential store; the address and area go into `settings.json`.

If the test fails, the status line tells you why:

- **Can't reach <address>. Check the address and that Home Assistant is running.** The address is wrong, Home Assistant is down, or (over https) the certificate was rejected.
- **Token rejected (401). Create a long-lived access token in your Home Assistant profile.** The token was pasted wrongly or has been deleted in Home Assistant.

**You should see** in Settings: the Home Assistant column at the top of the window reads **Connected · <area> · N lights · N scenes**.

**You should see** on the knob: from Home, tap **button 3** (Lights). The Lights screen shows the area's name, the current brightness and colour temperature, and a ring that follows the knob. Turn it and the lights follow.

<picture><source srcset="../media/lights-brightness.webp" type="image/webp"><img src="../media/lights-brightness.gif" alt="The knob's round screen on Lights: a brightness ring and a large percentage that climb as the knob turns, the room's lights brightening in the background" width="480"></picture>

## What the knob controls

- **Every light in the area, including lights you add later.** Desk Dial reads Home Assistant's registries, so a light assigned to the area afterwards appears on the knob without a restart. Light groups are skipped so a light is never driven twice.
- **Brightness** is 1 % per detent (a detent is one click of the knob). **Colour temperature** is 100 K per detent, between 2200 K and 6500 K, narrowed to what your lights support. Button 3 switches the knob between the two.
- **Lights without colour temperature.** If none of the area's lights can change colour temperature, the knob shows brightness only and button 3 answers **No colour temperature**. Mixed areas work: colour temperature stays available as long as at least one light in the area supports it, and the value shown averages the lights that do.
- **All off / Turn on** on button 4, and **Scenes** on button 2.
- Changes made elsewhere (a wall switch, the Home Assistant app) show on the knob within a moment.

## Scenes, scripts and automations

Button 2 opens the **Scenes** list. It contains, up to 20 entries:

- the scenes, scripts and automations **assigned to the chosen area** in Home Assistant;
- scenes that belong to no area but **set at least one of the area's lights**.

Turn to choose, tap button 4 to run. A scene is activated, a script is run, an automation is triggered. Nothing else of yours can be started from the knob.

## What Desk Dial does in your Home Assistant

Desk Dial opens one WebSocket connection to Home Assistant and falls back to plain REST calls when it is interrupted. It allows itself exactly these actions, and refuses anything else before sending it:

- turn the area's lights on or off, set brightness and colour temperature (every change fades over 0.4 s);
- activate a listed scene, run a listed script, trigger a listed automation;
- create and later activate one scene of its own: **`scene.desk_dial_snapshot`**.

That last one is how **All off** works. Before switching the area off, Desk Dial saves the current state of the area's lights into `scene.desk_dial_snapshot` in your Home Assistant, so that **Turn on** can bring back exactly what you had. You will see this entity appear in Home Assistant after the first All off. It is safe to leave alone; if you delete it, the next All off creates it again, and Turn on simply turns the lights on to their last state.

Writes are spaced out (at most four per second) and a turn always ends with the final value, so a fast spin does not flood your installation.

## Where the token lives

The token is stored in `%LOCALAPPDATA%\DeskDial\data\credentials.bin`, encrypted with Windows Data Protection (DPAPI) for your Windows user account only: another user account or another PC cannot read it, but a program running as you can. It is never written to the log, never placed in a URL and never shown in Settings after it is saved. The address and area are plain text in `settings.json` next to it.

To disconnect: delete the token in your Home Assistant profile, then quit Desk Dial and delete `credentials.bin`.

## Without Home Assistant

Everything else in Desk Dial works without it: music, the Windows picker and Onshape. The Lights screen shows **Not connected · Home Assistant · Open Settings on your PC**, and the Settings column says **Not connected · Add your address and token below**. The same screen appears when Home Assistant is unreachable; when the token was refused it reads the same with an error tone.

## Limits and known issues

- **One area, lights only.** Switches, covers, fans and media players in the area are ignored. Colour (hue) is not controlled, only brightness and colour temperature.
- **Plain http sends the token unencrypted** on your local network, and Desk Dial does not warn about it yet. Use https where you can.
- **Self-signed certificates are rejected.** Certificate checking is always on and there is no override. Use a trusted certificate or http on a network you trust.
- **Re-authorising Apple Music with a new .p8 key erases the saved Home Assistant token.** You will see **Token rejected** or **Not connected** afterwards; paste the token again and Save. Set up Apple Music first.
- **At most 20 scenes** are listed.
- The project is tested on one knob (the author's) against one Home Assistant installation.
