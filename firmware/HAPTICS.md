# r4 feel and sound (firmware 1.0.0-cc5.7, Desk Dial 7.3.0.0)

Plan stages F2 (haptics) and F3 (clicks and offline volume). The design target is Claude Design r4
(`app/design-reference/design_handoff_nano_d_r4`: README sections 2, 4, 6, 7, 9 and
`prototypes/haptic-lab.js`). The effect player, the pulse and the click synthesis are adapted, with his permission,
from Karl Malota's `NanoD_RatchetH1` branch `feat/firmware-esp-idf-quadra` (`control_task.c`, `haptic_params.h`,
`i2s_task.c`); the files that carry his work say so in their headers.

Everything here is additive and capability-gated. A host that sends none of the new fields (Desk Dial 7.2.x, the
simulator, any older tool) gets the 1.0.0-cc5.6 feel exactly and a silent knob. Desk Dial 7.3 sends them only to a
knob that reports the capabilities; on 1.0.0-cc5.6 / cc5.5 it keeps today's profiles and sends nothing new.

| Where | Code |
|---|---|
| Token table, laws, wall, effects, fold-back, trip, cross-task words | `src/cc_haptic_fx.h` (header-only, platform-neutral) |
| Click bank, voice, request ring | `src/audio/cc_sound.h` (header-only, platform-neutral) |
| Token loop, walls, detent pulses, freeze | `src/haptic.cpp` (`token_target`, `wall_penetration`, `end_freeze`) |
| Supply, requests, trip, effects, offline volume, recalibration | `src/foc_thread.cpp` |
| I2S player (MAX98357A) | `src/audio/audio.cpp` |
| hold.tension, Consumer reports, offline mode | `src/hmi_thread.cpp` |
| Wire fields, capabilities | `src/control_center.cpp`, `src/cc_frame_parse.cpp` |
| Recalibration replies and the save | `src/com_thread.cpp` |
| Desk Dial | `control_center/controller.py` (`feel()`, `_haptic()`), `device.py`, `runtime.py`, `ui.py` |
| Host tests | `harness/haptic_fx_tests.py` (+ `.cpp`), `tests/test_r4_feel.py`, `cpp11_gate.py` |

## 1. Capabilities and wire

`{"capabilities":"?"}` adds five ints, each `1`:

| Capability | Meaning |
|---|---|
| `feel` | control `feel` (a token) and `reducedHaptics` (bool); the knob runs feel.fade, hold.tension and the r4 wall |
| `hapticFx` | frame `haptic`: `{"token": <event>, "seq": 1..0x7FFFFFFF}` |
| `knobSound` | control `sound`: 0 off, 1 Low, 2 Medium, 3 High |
| `knobVolume` | control `soundVolume`: the master volume, 0..100 % (2026-09-30; overrides `sound`) |
| `offlineVolume` | informational: with no host on the port for 2 s the knob is the PC's volume (section 8) |
| `recalibration` | `{"recalibrate":true}` / `{"recalibrate":{"acceptDirection":true}}` answer `calibrating` / `calibrated` (section 9) |

Control (on top of the cc5.6 fields): `feel` (one of `detent.value`, `detent.dimmer`, `detent.list`,
`detent.coarse`, `detent.fine`, `fluid.scrub`, `fluid.light`, `free.spin`), `reducedHaptics`, `sound`. A present
invalid value rejects the control (`Invalid feel token`, `Reduced haptics must be a boolean`, `Invalid sound level`).
They are per control and never stored: a release gives the native profile back, legacy and silent.

Frame `haptic` follows the strict rule (an unknown token, a missing or bad seq rejects the frame; unknown keys inside
are ignored). Events: `confirm.tick`, `confirm.thump`, `nudge.left`, `nudge.right`, `refuse.buzz`, `error.buzz`,
`confirm.off` (Lights "All off": r4 4.4 "off: 1 pulse", r4 6 "lights off: BUTTON_THUMP at lower amplitude"; the one
token added to the r4 list). The COM task plays each new seq once (the FOC task takes it); a claim only seeds the seq,
so a reconnecting host's last event never replays. Frames are coalesced and re-sent as heartbeats: the seq makes both
harmless.

## 2. Units (why the numbers differ from Karl's)

The haptic loop commands a "current" target that SimpleFOC turns into `Uq = target x 5.3 ohm` (torque, voltage mode),
capped at 2.2 V (F1). The legacy detent PID runs P = 3 A/rad with a 0.4 A (2.12 V) limit. Karl's Kp / Kd are volts per
radian. The anchor is the user's ruling that Home volume must feel like today's BINARIS BEER: **detent.value Kp 3 =
the legacy P 3 A/rad**, and every other token keeps Karl's ratio to it. Kd is in A/(rad/s), numerically Karl's number
times `CC_HAPTIC_KD_SCALE` (1.0; a `-D` to tune by feel). Damping uses the filtered shaft velocity (SimpleFOC LPF,
10 ms) with a 0.5 rad/s deadband, never the PID's derivative (its D stays 0, section 6).

## 3. Tokens -> parameters

| Token | Law | Detents / turn | Kp (A/rad) | Kd (A/(rad/s)) | Detent pulse | Coast | Detent sound | Reduced haptics |
|---|---|---|---|---|---|---|---|---|
| detent.value | SINE | profile's (BINARIS BEER 67) | 3 | 0.01 | 15 % | yes (D1) | wood-tock 45 % | VISCOSE Kd 0.02 |
| detent.dimmer | SINE | profile's (67) | 3 | 0.04 | 20 % | yes (D1) | wood-tock 50 % | VISCOSE Kd 0.05 |
| detent.list | SAW | 20 | 6 | 0.01 | 35 % | no | wood-tock 60 % | SINE 20, no pulse, silent |
| free.spin | SAW | 20 | 6 | 0.01 | 35 % | **yes** | wood-tock 60 % | SINE 20, no pulse, no coast |
| detent.coarse | SAW | 12 | 11 | 0.02 | 50 % | no | tick-thud 70 % | SINE 12, Kp 6, no pulse |
| detent.fine | SAW | 36 | 2.5 | 0.01 | 25 % | no | fine (2x) 40 % | SINE 36, silent |
| fluid.scrub | VISCOSE | profile's (counting only) | 0 | 0.08 | — | no | fine (2x) 30 % per count | same |
| fluid.light | VISCOSE | profile's (counting only) | 0 | 0.02 | — | no | fine (2x) 30 % per count | same |
| (none) | legacy PID | profile's | P 3 | 0 | — | > 30 rad/s | silent | — |

- **SINE** is `A sin(2 pi e / w)` with `A = Kp w / 2`: the same peak holding force as SAW's `Kp e` at the midpoint,
  but smooth (soft steps), zero at the centre and the midpoint. **SAW** is the legacy law. **VISCOSE** has no well:
  positions are still counted at the profile's pitch (the host's 5 s Seek steps, Onshape deltas).
- The density replaces the preset's `detent_count` only where the token names one; value and dimmer keep BINARIS
  BEER's 67 per turn (1.5 turns for 0..100, close to r4's 1.4 for the dimmer), so volume keeps today's travel.
- The spring keeps the profile's `output_ramp` slew (as `default_pid` applies it) and the legacy 0.4 A limit; spring
  + damping + effect is clamped to the 2.2 V cap. The legacy anti-ringing trim (x0.75 inside 0.75 % of a pitch) stays.
- Brightness is heavier than volume (r4 9) by Kd 0.04 vs 0.01 on the same well.

**feel.fade** (r4 4.2): on a claim, or when the token or reduced haptics change, Kp ramps 0 -> 1 over 120 ms, and again
from the arm re-anchor (`cc_can_arm`: the grid moves once more when the LEDs and the screen are installed). A re-entry
with the same token does not fade (the host re-enters for list growth and passive refreshes; a fade then would soften
the knob mid-turn). After a sleep wake the detents fade in over 150 ms (r4 4.4 Sleep). The wall never fades.

**hold.tension** (r4 4.2; open question 1 answered: four steps, never a per-tick ramp): while button 1 (physical slot
0) is held on a screen with a crumb (hold 1 = Home, 600 ms) or button 4 (slot 3) on a screen whose frame declares
`holdMarker` (1000 ms), never on the app canvas, Kd = max(token Kd, 0.0375 / 0.065 / 0.0925 / 0.12) by quarter of the
hold. It ends at the release (no event) and at the hold's maturity (the host's thump lands then). Hold 1 wins over a
held button 4, as the LED hold rings do. Off with reduced haptics.

## 4. Walls (r4 4.3)

At a bound, past the centre of the committed detent by `pen`, the torque is a wall in **volts**: stiffness ramps from
the law's centre stiffness (SAW Kp, SINE Kp x pi: continuous with the well) to 3x that one pitch out, capped at
2.2 V x the fold-back factor. No step, no zero crossing: the push-back grows the further you go. The wall is never
zeroed by coasting and never slewed. The legacy `lim` events, `atLimit`, `last_limit_position` and the
`inward_from_boundary` restore are unchanged. Token mode only (legacy / native / Onshape on cc5.6 hosts keep today's).

`cc_wall_hit(dir)` (`src/cc_wall.h`, for the MOTION job's M13 stretch and end LEDs) is called once per refused detent
(the attractor moved to a new detent past the bound), in every mode: dir +1 past the end / max, -1 past the start /
min. Returning into the committed detent re-arms it.

**Fold-back** (at the wall only): energy += (V_applied^2 - 1.21) dt, floored at 0. Over 100 V^2 s (about 27 s of a
full 2.2 V lean) the wall force ramps down (1 /s) to at least 50 %; at 50 % the applied 1.1 V equals the cooling rate,
so a continued lean holds there. Below 50 V^2 s it recovers at 0.25 /s. **Provisional numbers**, to be calibrated by
the 3-minute wall-lean test (section 12).

## 5. Effects

| Event | Pulses (fraction of the 2.2 V cap) | Sound (level before the master) | Reduced haptics |
|---|---|---|---|
| confirm.tick | 1 x 60 % | wood-tock 60 % | 1 x 50 % |
| confirm.thump | 2 x 100 %, 12 ms apart | thump 40 ms, 100 % | 1 x 60 % |
| confirm.off | 1 x 80 % | thump 70 % | 1 x 50 % |
| nudge.left / nudge.right | 1 x 80 %, signed | tick-thud 60 % | 1 x 50 %, unsigned |
| refuse.buzz | 3 x 60 %, 30 ms apart; at most once a second | 3 x wood-tock 40 %, 30 ms apart | 1 x 80 % (a nudge), 1 tock |
| error.buzz | 3 x 100 %, 70 ms apart | 3 x tick-thud 60 %, 70 ms apart | 1 x 80 %, 1 thud |
| detent pulse (list / coarse / fine) | 35 / 50 / 25 %, against the motion | the token's detent sound | none |

The pulse: a 4 ms impact that is **one full sine period** (the sign says which lobe leads, so a nudge leans its way;
"phase-signed"), then Karl's 70 Hz tail at 1/6 over 20 ms, fading to zero. Deviation D2: Karl's impact is 0.4 of a
100 Hz period (a net push); in the knob model a half-sine thump flung a resting 67-detent knob a whole detent, a full
period has zero net impulse. The player (`CCFxPlayer`): `micros()` timing; no re-fire inside a pulse's 4 ms impact; no
pulse while coasting; a detent pulse never cuts an event, an event cuts a detent pulse or an older event after its
impact; the refuse limit is also enforced by the host. **Freeze**: an effect that starts with |v| < 2 rad/s freezes the
detent position until its pulses end + 60 ms; a turn never freezes. At the freeze's end the detents the shaft crossed
meanwhile are counted one by one (`end_freeze`), so none is lost; still, in a viscous feel, the grid moves with the
pulses' displacement instead (there is no well to pull the knob back). Effects play only for the claimed control.

Every sound follows its haptic: a pulse the player refuses makes no sound.

## 6. The uint16 range fix and the D rule

`correct_pid()` counted `end - start + 1` in a `uint16_t`, which wrapped to 0 for a range 65,536 positions wide
(Onshape's 0..65535 before Desk Dial 7.2.2) and so switched on the derivative term: the Onshape buzz. The count is now
`cc_positions()` (32-bit, >= 1) and the rule explicit: `haptic_pid->D = 0` (as every release before on every range that
did not wrap). Audit of every other `end_pos - start_pos` / bound product: `load_profile` (`num_detents`, never wraps
after the F1 sanitize), `detent_handler` and `bounds_handler` (VERNIER bounds scaled with `cc_scaled_position()`, 32-bit
and clamped at 65535; they wrapped for end x vernier > 65535), `nativeLeds()` (map over uint16, no wrap),
`control_center.cpp` (max 65535, min 0). Desk Dial's own guard (Onshape 0..60000) stays.

## 7. Supply voltage

The STSPIN233 runs from switched VBUS (Karl's `NanoFOC_D.kicad_sch`), so on a 9 V PD contract every commanded voltage,
the cap included, was 1.8x. The FOC task now sets `driver.voltage_power_supply` from the contract read at boot
(`cc_boot_pd_contract()`: the RDO read status, its object position, the sink PDO's voltage there, and whether
`init_pd()` rewrote the sink table this boot) before `driver.init()`. FW-BUG-022: the rule fails safe HIGH
(`cc_supply_volts()`), because the motor sees U x VBUS / supply and a supply assumed below VBUS over-drives everything,
the 2.2 V cap included (unknown -> 5 V was 1.8x at 9 V and 3-4x at 15-20 V):

| Boot read | Supply |
|---|---|
| read ok, no contract (position 0: a plain PC port), NVM rewritten this boot or not | 5 V (nothing changes on the user's PC port, the first boot of a new knob included) |
| read ok, contract voltage known (5..20 V) | that voltage |
| read failed, or position outside the sink table | 9 V, the highest sink PDO `init_pd()` programs |
| sink PDOs rewritten to NVM this boot (the old table, up to 20 V, holds until a power cycle), and the read failed or found a contract | 20 V |

Without an explicit contract VBUS is the USB default 5 V whatever the NVM holds, so a rewrite alone never lowers the
feel (or the first-boot alignment field) on a PC port. The 9 V fallback relies on `init_pd()` (plan F8) rewriting any
sink table that is not 5/9/9 V (it checks the PDO voltages, not only the count): a foreign table (5/20 V, say) is then
always a rewrite boot, and an unknown supply there is assumed 20 V.

Assuming too high only weakens the feel. diag `supplyVolts` reports the supply, `supplyAssumed` whether it was
assumed (no readable contract voltage).

## 7b. Rest sleep (2026-09-30)

- **Why:** the user felt a constant faint vibration at rest. With the knob still, the spring answers the angle
  sensor's noise and the damping answers the velocity estimate's noise, many times a second.
- **What:** `CCRestGate` (`cc_haptic_fx.h`) zeroes the output of both loops (token and legacy) once the knob has sat on
  its detent (|error| < 0.3 degrees, |velocity| < 0.8 rad/s, nothing playing) for 250 ms (350 until the user's check).
- **Waking:** it wakes the moment one of these happens:
  - the shaft moves one detent width from where it fell asleep (`cc_rest_wake_rad`: at least 2.5 and at most
    5.4 degrees, one volume detent; 0.5, 1.5, then 2.5 until the user's checks: a touch woke it); a pulsed feel wakes
    at its first counted step, half a detent, which plays its pulse and click;
  - the attractor moves that far away (a re-anchor);
  - anything plays: an effect, hold tension, a wall, the limit handler, a freeze.
- **After waking:** the spring restarts from zero through the output ramp; the legacy PID is reset. The damping ignores
  velocity below 0.8 rad/s (was 0.5), so the awake knob buzzes less too.
- **At a bound:** resting against the wall's edge is rest. A push into the wall wakes it by the same distance as any
  turn, and once awake the wall fades in over 120 ms with the feel (2026-09-30: at Lights 100 % it first never slept,
  then the lightest touch woke it and the stiff wall buzzed).
- **Diag:** `restAsleep`, `restSleeps`, `restWakes`.
- **Tests:** `haptic_fx_tests.cpp` `rest_tests()`, plus the pin that requires both loops to go through
  `rest_.step()`.

## 8. Sound (plan F3)

MAX98357A on I2S0: DIN 9, BCLK 10, LRC 11 (`nanofoc_d.h`; confirmed on Karl's board; no shutdown pin). 22.05 kHz,
16-bit, the same sample in both slots, 6 x 64-frame DMA (17.4 ms) with auto-clear. `-DAUDIO_EN=1` is on (platformio.ini)
**after** removing the old triggers: the boot chime, the native key clack, the per-detent `hard` sample fired from the
FOC task, the busy `Serial.println("x")`, the XT_I2S path and every WAV array (about 54 KB of flash). Profiles keep
their `audio` fields by name (one-byte name tokens), nothing plays them.

- **Bank**: rendered once into RAM at boot (PSRAM when present, 4.4 KB): WOOD_TOCK (5 ms, 2400 Hz chirping down from
  1.6x, decay 1080 /s), FINE (the tock at 2x pitch), TICK_THUD (50 ms: 1800 Hz tick + 330 Hz body, clipped), THUMP
  (40 ms: the harmonics 2..6 of 110 Hz without the fundamental, decay 140 /s, over a 1.2 kHz 4 ms attack, normalised to
  a 30000 peak). Karl's constants, except the two low bodies (2026-09-30, by ear: the knob's speaker plays neither Karl's
  110 Hz thump nor the thud's 100 Hz body; the user heard the tocks and no thump at High).
- **Requests**: the FOC task posts one (sound, gain, repeats, gap) when a pulse starts, into a lock-free SPSC ring of 16;
  the HMI task takes the loudest waiting one (the newest among equal gains) when the voice may retrigger (Karl's 4 ms
  minimum), counts the others as superseded (diag `audioSuperseded`), and cuts the current sound, so a press thump is
  never lost to a tock that follows it. A request that finds the ring full is lost and counted in diag `audioDropped`.
- **Gain**: the table's level x the master volume (percent). The levels are twice r4 section 6's, same ratios, so the
  thump is full scale at 100 % (2026-09-30: at r4's levels a Low tock was 12 % of full scale and near silent). The
  volume is the control's `soundVolume` 0..100 (capability `knobVolume`), else its `sound` level: Low 40 %, Medium
  70 %, High 100 %. Diag `soundVolume` reports it and `soundLevel` its nearest level.
- **Writer**: every HMI pass, non-blocking `i2s_write` (timeout 0); what the DMA cannot take waits for the next pass.
  Idle, nothing is written (the DMA sends zeros), so a click starts within one buffer (2.9 ms). While a sound plays the
  HMI passes at least every 3 ms. **Underrun**: a sound already playing that finds the whole writable DMA free (5 of
  the 6 buffers, 320 frames / 14.5 ms: the IDF 4.4 free-buffer queue holds buf_cnt-1) (diag `audioUnderruns`).
- **Every interaction sounds** (2026-09-30, the user; r4 6 kept value / dimmer detents, fluids and walls silent):
  value and dimmer detents tick (pulse + tock), fluid feels click on each count (sound only), a wall thuds (50 %)
  once per refused detent, and Desk Dial ticks every button press.
- **Silent**: coasting, reduced haptics, native (unclaimed) use, and any host that
  sends neither `sound` nor `soundVolume`. Idle hiss: the I2S clock runs as it did in every earlier release (the driver was installed before
  too); the hands-on check listens for it (section 12).

## 9. Offline system volume (plan F3)

A HID Consumer Control collection is **appended as report ID 4** (keyboard 1, mouse 2, gamepad 3 unchanged; the
serial `NANO_D`, VID/PID and the bootloader entry are unchanged). It is active only while no host has the CDC port open
(DTR) for >= 2 s and nothing is claimed. Then:
- the FOC task runs the fixed profile **OFFLINE VOLUME**: REGULAR, 36 detents per turn (one 2 % Windows step each),
  positions 0..200, output ramp 10000, the legacy strength; after every step the position goes back to 100 (the grid is
  untouched), so there is no end stop;
- each step is one Volume Increment (0xE9) / Decrement (0xEA) press and its release, one report per HMI pass (at most 20
  queued); consumer usages never wake the PC (while suspended they are dropped);
- the profile's own knob value (MIDI CC) and key actions are suppressed;
- the native profile comes back when a host opens the port (a claim that arrives first restores it before the claim).
F24 is unchanged: exactly one key code per Win press, released 60 ms later.

## 10. Self-spin trip

The flipped-torque model (`haptic_fx_tests.cpp`, a wrong calibration: torque sign reversed) shows every law runs away:
a well becomes a hill and the knob tumbles from hill to hill, a wall and a viscous feel drive it to its back-EMF speed,
the legacy loop oscillates around its 30 rad/s coasting speed. No hand spins the knob that fast for that long, so the
trip is a leaky timer: while |v| >= 15 rad/s the score rises 1 /s, otherwise it falls 0.5 /s; at 2 s it latches. In
the model every runaway trips at about 2.0 s; a hard flick, a 10 s list scroll at 12 rad/s, a 1.5 s spin at 25 rad/s
and a push through a wall do not. The latch holds a zero output (sleep and wake keep it) until the next claim or a key
press. A human spinning faster than 2.4 turns a second for 2 s straight trips it too (the knob goes limp until a key
press): recorded here as the accepted trade-off. diag `tripLatched`, `spinTrips`.

Model constants (assumptions, not measurements): J 3.25e-6 kg m^2 (a 20 g, 30 mm knob plus the rotor), Kt = Ke 0.04
N m/A, R 5.3 ohm, viscous friction 2e-6 N m s, 60 us passes, the 10 ms velocity LPF.

## 11. Recalibration

`{"recalibrate":true}` (and the legacy `{"R":"129=1"}`, which no longer runs a bare `initFOC()`) asks the FOC task,
which: releases nothing (the command is refused while claimed), announces `{"calibrating":true}`, disables for 1 s,
runs SimpleFOC's alignment (direction sweep, then the field held at 3 pi / 2 for the zero, at <= the 2.2 V cap), then
the pole-pair check (one electrical turn open-loop must move the shaft 2 pi / 7 +- 25 %), then the direction rule (a
changed direction is accepted only after a self-spin trip or with `{"recalibrate":{"acceptDirection":true}}`). A failure
restores the old direction and zero angle and re-enables. A success is saved through the handshake: the FOC task offers
the calibration while holding a zero output, the COM task takes it, writes Preferences (outside the task watchdog, like
`save`) and marks it done; 1.5 s without it is a failure. Then the detents are re-anchored. The answer is
`{"calibrated":{"ok":bool,"reason":"ok"|"init-failed"|"pole-check-failed"|"direction-changed"|"save-timeout"|"claimed"}}`.
diag `calState` (idle / running / saving), `calOutcome`.

Boot calibration (`src/cc_boot_cal.h`, host-tested in `haptic_fx_tests.cpp`):

- FW-TST-009: the stored pair is used only when whole and plausible (direction byte 0 / 1 / 255, a finite zero in
  [0, 2 pi]); anything else boots uncalibrated, so the whole alignment runs. The boot stores when the alignment
  succeeded and either value changed (a re-aligned zero too).
- FW-PUB-006: an alignment posts `CC_MOTOR_CAL_ALIGNING` (the LCD's "hands off" cue) and waits 1 s first; the pair is
  stored only when SimpleFOC's pole-pair check of that alignment passed (`pp_check_result`), else it runs from RAM
  (`unstored`) and the next boot aligns again.
- FW-BUG-030: a failed alignment (initFOC() 0) is kept (`failed`; diag `motorReady`, `motorCal`), the sleep wake
  never enables an uncalibrated motor, and the alignment is retried once after 5 s idle (no key, unclaimed, awake),
  saved through the same COM handshake as a recalibration. A second failure stays `failed` ("replug, hands off").

Desk Dial (Settings > Knob > Recalibrate motor): releases the control, sends the command, enters nothing meanwhile
(the seconds of alignment are not a timeout), and enters again on `calibrated`. After a `direction-changed` refusal the
same button asks again with `acceptDirection` (the confirmation the plan wanted on the knob screen; the knob-screen
steps are the MOTION job's, see the report).

## 12. Hands-on checks (the user, by feel and ear; nothing here is automated on hardware)

1. Home volume feels like cc5.6 (same travel, same strength, a little damping); brightness heavier (eyes closed).
2. Lists click with a quiet tock (Low); Windows and Scenes are heavier rotary steps; temperature clicks higher.
3. Every end: a wall that pushes back harder the further you go, no click, no sound, springs back.
4. Hold 1 / hold 4 stiffen during the hold; an early release relaxes with no event; the landing thumps.
5. Only hold landings, Play, Turn on and Scene run thump; a refused press buzzes at most once a second.
6. Reduced haptics: soft steps, one pulse instead of thumps and buzzes, walls still there.
7. Quit Desk Dial, wait 2 s: the knob sets Windows volume (2 % per detent), no end stop; open Desk Dial: native back.
8. Listen for idle hiss with sounds on and off.
9. Wall lean: lean on a list end for 3 minutes; the force should ease to about half after ~30 s and stay there
   (calibrates `CC_FOLD_BUDGET_V2S` / `CC_FOLD_COOL_V2`).
10. On a 9 V PD charger (if one is at hand): the feel matches the PC port.

## 13. Feature switches

All default 1 in `cc_haptic_fx.h`; `-D<NAME>=0` builds without: `CC_HAPTIC_TOKENS`, `CC_HAPTIC_FX`, `CC_HAPTIC_WALL`,
`CC_HAPTIC_FOLDBACK`, `CC_HAPTIC_TRIP`, `CC_SUPPLY_FROM_PD`, `CC_OFFLINE_VOLUME`; `AUDIO_EN` (platformio.ini) for sound;
`CC_HAPTIC_KD_SCALE` tunes every Kd. The runtime switch is the host: Desk Dial sends `feel` / `haptic` / `sound` only to
an r4 knob.

## 14. Deviations from r4

- D1: detent.value and dimmer keep today's coasting above 30 rad/s (r4 enables free spin only for long lists); a fast
  volume spin feels as it always has. Lists, coarse and fine never coast unless free.spin.
- D2: the pulse's impact is one full 250 Hz period (section 5).
- D3: value and dimmer keep the profile's density (67 / turn) instead of r4's 36; brightness stays 1 % per detent
  (r4: 2 %, 1 % below 10 %), 1.5 turns for the range (r4 1.4).
- D4: `confirm.off` is added for Lights "All off".
- D5: Sleep stays the cc_sleep motor-off (no fluid.light while asleep); the detents fade in over 150 ms after a wake.
- D6: hold.tension is four Kd steps (r4 open question 1).
