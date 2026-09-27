"""The Music explorer and Up next scenes (WP8): layout maths (DESKTOP_STAGE §6.6 H8), the pure model
(K4 §7.4, §8.2, §8.3 [r2.2], §13), the scenes on the stage engine with the fake device, a fake
host, a synchronous capture and a synchronous art service on one fake clock (§4.8), the art
service, the runtime adapter, and the static rules for the new modules (H2, WP7a's "no behaviour
change"). Headless: no window, no GPU, no network, no screen capture."""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import scene_music as SM  # noqa: E402
from control_center.stage.layout import StageLayout  # noqa: E402

G93 = StageLayout((0, 0, 5120, 1440))
QHD = StageLayout((0, 0, 2560, 1440))
MS = 10_000                                         # fake-clock ticks per ms (10 MHz)


def _anim(dev, oid, prop):
    return dev.animation_of(oid, prop)


def _end_s(a):
    return a["end"][0] if a and a.get("end") else None


def _step_s(a):
    """A delayed instant change (Batch.jump with an anchor): (hold s, value before, value after)."""
    segs = a["segs"]
    assert len(segs) == 1 and segs[0][2:] == (0.0, 0.0, 0.0), segs
    return a["end"][0], segs[0][1], a["end"][1]


def _lead_hold_s(a):
    """The leading hold of an animation (its first curve segment's offset), in s."""
    segs = a["segs"]
    if len(segs) >= 2 and segs[0][2] == 0.0 and segs[0][3] == 0.0 and segs[0][4] == 0.0:
        return segs[1][0]
    return 0.0


# =========================================================================== H8: layout maths
class ExplorerLayoutTests(unittest.TestCase):
    def test_tables_are_the_contract_tables(self):
        t16, t32 = SM.explorer_table(False), SM.explorer_table(True)
        self.assertEqual(t16.x, (0, 300, 470, 590, 660))
        self.assertEqual(t16.s, (1.0, 0.6, 0.42, 0.3, 0.22))
        self.assertEqual(t16.o, (1.0, 0.92, 0.55, 0.0, 0.0))
        self.assertEqual(t16.sh, (0.0, 0.24, 0.48, 0.6, 0.6))
        self.assertEqual(t32.x, (0, 300, 500, 680, 850, 1010, 1170, 1330, 1490))
        self.assertEqual(t32.s, (1.0, 0.6, 0.46, 0.42, 0.4, 0.4, 0.4, 0.4, 0.4))
        self.assertEqual(t32.o, (1.0, 0.92, 0.84, 0.76, 0.68, 0.6, 0.54, 0.5, 0.0))
        self.assertEqual((t16.a_max, t32.a_max), (4, 8))
        self.assertTrue(min(s for s, o in zip(t32.s, t32.o) if o > 0) >= 0.40)      # no visible card below 0.40

    def test_wide_and_k(self):
        self.assertTrue(G93.wide)
        self.assertEqual(G93.k, 2.0)
        self.assertFalse(QHD.wide)

    def test_card_slots_in_px_on_the_g93sc(self):
        """§7.2 "Size px" and "Centre offset px" columns at k = 2."""
        t = SM.explorer_table(True)
        cs = SM.card_size(G93)
        self.assertEqual(cs, 680)
        for a, (size, centre) in {0: (680, 0), 1: (408, 600), 2: (312.8, 1000), 3: (285.6, 1360),
                                  4: (272, 1700), 7: (272, 2660), 8: (272, 2980)}.items():
            slot = SM.card_slot(G93, t, a)
            self.assertAlmostEqual(cs * slot.s, size, places=3)
            self.assertEqual(slot.x + cs / 2 - 2560, centre)
            self.assertEqual(SM.card_slot(G93, t, -a).x + cs / 2 - 2560, -centre)
        self.assertEqual(SM.card_slot(G93, t, 20).a, 8)                              # beyond: the a_max slot
        self.assertEqual(SM.card_rest_y(G93), 296)
        self.assertEqual(SM.card_hit_rect(G93), (2220, 296, 2900, 976))

    def test_monitor_edge_cuts_a7_and_hides_a8(self):
        t = SM.explorer_table(True)
        cs = SM.card_size(G93)
        for a, visible_px in ((7, 36), (8, 0)):
            slot = SM.card_slot(G93, t, a)
            left = slot.x + cs / 2 - cs * slot.s / 2
            self.assertAlmostEqual(max(0.0, 5120 - left), visible_px, delta=0.5)

    def test_16x9_on_a_qhd_monitor(self):
        t = SM.explorer_table(QHD.wide)
        self.assertEqual(t.a_max, 4)
        self.assertEqual(SM.card_slot(QHD, t, 1).x + 340 - 1280, 600)

    def test_z_order_is_20_minus_a(self):
        self.assertEqual(SM.card_z_order([3, 4, 5, 6, 7], 5, 8)[-1], 5)
        self.assertEqual(SM.card_z_order([3, 4, 5, 6, 7], 5, 8)[:2], [3, 7])

    def test_rise(self):
        self.assertAlmostEqual(SM.card_rise_px(G93, 0.6), 36.0)


class DotsAndPreloadTests(unittest.TestCase):
    def test_dots_cap_window_and_fades(self):
        self.assertEqual(SM.DOTS_CAP, 82)
        d = SM.dots_window(5, 2)
        self.assertEqual((d.first, d.count, d.left_fade, d.right_fade, d.marker), (0, 5, False, False, 2))
        d = SM.dots_window(120, 60)
        self.assertEqual((d.first, d.count, d.left_fade, d.right_fade, d.marker), (19, 82, True, True, 41))
        d = SM.dots_window(120, 3)
        self.assertEqual((d.first, d.left_fade, d.right_fade, d.marker), (0, False, True, 3))
        d = SM.dots_window(120, 119)
        self.assertEqual((d.first, d.left_fade, d.right_fade, d.marker), (38, True, False, 81))
        ops = SM.dot_opacities(SM.dots_window(120, 60))
        self.assertEqual(ops[:4], [0.10, 0.20, 0.30, 0.40])
        self.assertEqual(ops[-3:], [0.30, 0.20, 0.10])
        self.assertEqual(SM.dots_window(0, 0).count, 0)

    def test_dots_row_geometry(self):
        self.assertEqual(SM.dots_left_units(9), 640 - (9 * 14 - 8) / 2)
        d = SM.dots_window(9, 4)
        self.assertEqual(SM.marker_x(G93, d), int(round(1280 + (SM.dots_left_units(9) + 4 * 14) * 2)))

    def test_preload_window(self):
        self.assertEqual(SM.preload_window(40, 100, True, 0), (28, 52))
        self.assertEqual(SM.preload_window(40, 100, True, +1), (28, 56))
        self.assertEqual(SM.preload_window(40, 100, True, -1), (24, 52))
        self.assertEqual(SM.preload_window(40, 100, False, +1), (34, 50))
        self.assertEqual(SM.preload_window(2, 5, True, 0), (0, 4))
        self.assertEqual(SM.preload_window(3, None, True, 0), (0, 15))

    def test_l0_set_and_build_order(self):
        self.assertEqual(SM.l0_indices(10, 100, 1), [8, 9, 10, 11, 12, 13])
        self.assertEqual(SM.l0_indices(0, 3, -1), [0, 1, 2])
        order = SM.build_order(10, 7, 13, +1)
        self.assertEqual(order[:3], [10, 11, 9])

    def test_placeholders(self):
        self.assertEqual(SM.placeholder_indices(0, None, 8), list(range(0, 9)))
        self.assertEqual(SM.placeholder_indices(5, 7, 4), [1, 2, 3, 4, 5, 6])


class UpNextLayoutTests(unittest.TestCase):
    def test_row_slots_at_k2(self):
        """§8.2's "Row px" column: centres 640, 440 / 840, 288 / 992, 168 / 1112."""
        for d, centre in ((0, 640), (1, 840), (-1, 440), (2, 992), (-2, 288), (3, 1112), (-3, 168)):
            slot = SM.row_slot(G93, d)
            self.assertEqual(slot.y + 88, centre)
        self.assertEqual(SM.row_slot(G93, 1).s, 0.78)
        self.assertEqual(SM.row_slot(G93, 4).o, 0.0)
        self.assertAlmostEqual(SM.row_slot(G93, -1, played=True).o, 0.72 * 0.6)

    def test_plate_and_columns(self):
        self.assertEqual(SM.plate_rect(G93), (2480, 552, 3600, 728))
        self.assertEqual(SM.row_left(G93), 2480)
        self.assertEqual(SM.upx(G93, SM.U_COVER), 760)


class ArtRuleTests(unittest.TestCase):
    def test_rungs(self):
        self.assertEqual(SM.art_rung(680), 1200)
        self.assertEqual(SM.art_rung(340), 600)
        self.assertEqual(SM.art_rung(112), 240)
        self.assertEqual(SM.art_rung(680, 400), 400)
        self.assertEqual(SM.art_rung(1360, 0, 4.0), 2000)

    def test_upscale_rule_and_insets(self):
        self.assertFalse(SM.is_extended(680, 600))
        self.assertTrue(SM.is_extended(680, 400))
        for need, src, inset in ((680, 400, 0.06), (680, 300, 0.17), (760, 400, 0.105)):
            self.assertAlmostEqual((1 - SM.extended_fraction(need, src)) / 2, inset, delta=0.006)

    def test_gen_hash_matches_bs_genof(self):
        """§13.6 / H8: samples computed by BS ``genOf`` (BS:537) in Node, verbatim."""
        bs = [["Hounds of Love", "Kate Bush", 7], ["Promises", "Floating Points, Pharoah Sanders & LSO", 4],
              ["Tropicália ou Panis et Circencis", "Various artists", 0],
              ["Elis & Tom", "Elis Regina & Antônio Carlos Jobim", 3], ["Late Night Drive", "", 4],
              ["Favorite Songs", "", 1], ["PAPER LANTERN Ep. 1", "", 5], ["😀 Smile 🎶", "Émilie", 3], ["", "", 5],
              ["Kind of Blue", "Miles Davis", 6], ["Águas de Março", "Elis Regina", 6], ["𝄞 Clef", "Bach", 6]]
        from control_center import artwork
        for title, artist, want in bs:
            self.assertEqual(SM.gen_index(title, artist), want, title)
            self.assertEqual(artwork.gen_index(title, artist), want, title)

    def test_plans(self):
        cover = SM.cover_plan({"title": "A", "artist": "B", "art_template": "https://x.mzstatic.com/{w}x{h}bb.jpg",
                               "art_max": 1200, "art_bg": 0x102030, "art_ink": 0xF0F0F0})
        self.assertEqual(cover.kind, "cover")
        self.assertEqual((cover.bg, cover.ink), (0x102030, 0xF0F0F0))
        gen = SM.cover_plan({"title": "A", "artist": "B"})
        self.assertEqual(gen.kind, "generated")
        self.assertEqual((gen.bg, gen.ink), (0x232325, 0xF2F2F2))               # S5-11
        self.assertEqual(SM.cover_plan({"title": "A", "art_template": "simulation://loading/x/{w}x{h}bb.jpg"}).kind,
                         "never")
        self.assertEqual(SM.cover_plan({"title": "A", "sonos_art": "http://10.0.0.2:1400/getaa?u=1"}).sources[0][0],
                         "sonos")
        tiles = [{"art_template": f"https://a.mzstatic.com/{i}/{{w}}x{{h}}bb.jpg", "art_max": 600} for i in range(4)]
        self.assertEqual(SM.playlist_plan({"title": "P", "mosaic": tiles, "art_state": "mosaic"}).kind, "mosaic")
        self.assertEqual(SM.playlist_plan({"title": "P", "mosaic": tiles[:1], "art_state": "single"}).kind, "single")
        self.assertEqual(SM.playlist_plan({"title": "P", "mosaic": [], "art_state": "generated"}).kind, "generated")
        own = SM.playlist_plan({"title": "P", "mosaic": [], "art_state": "generated", **tiles[0]})
        self.assertEqual(own.kind, "cover")                                      # K4 §22 Q1: own art last
        self.assertEqual(SM.playlist_plan({"title": "P", "id": "p1"}).kind, "pending")
        self.assertEqual(SM.explorer_plan({"title": "P", "kind": "playlist", "mosaic": tiles}, "recent").kind, "mosaic")


# =========================================================================== the pure model
class ModelTests(unittest.TestCase):
    def test_explorer_labels(self):
        self.assertEqual(SM.explorer_label({"title": "Hounds of Love", "artist": "Kate Bush", "year": 1985,
                                            "track_count": 12}, "recent"),
                         ("Hounds of Love", "Kate Bush", "1985 · 12 tracks"))
        self.assertEqual(SM.explorer_label({"title": "X", "artist": "Y", "track_count": 1}, "recent")[2], "1 track")
        self.assertEqual(SM.explorer_label({"title": "Favorite Songs", "auto": True, "count": 12,
                                            "duration_ms": 48 * 60000}, "favourites"),
                         ("Favorite Songs", "Favourite playlist · made by Apple Music", "12 songs · 48 min"))
        self.assertEqual(SM.explorer_label({"title": "Late Night Drive", "count": 48, "duration_ms": 192 * 60000},
                                           "favourites")[1:], ("Favourite playlist", "48 songs · 3 h 12 min"))
        self.assertEqual(SM.explorer_label({"title": "", "kind": "playlist"}, "favourites")[0], "Untitled playlist")
        self.assertEqual(SM.explorer_label(None, "recent"), ("", "", ""))

    def test_state_blocks_use_the_active_tabs_glyph(self):
        self.assertEqual(SM.state_block("empty", "favourites"),
                         ("queue", "No favourite playlists yet",
                          "Star a playlist in the Music app. It appears here within a few minutes."))
        self.assertEqual(SM.state_block("empty", "recent")[:2], ("clock", "Nothing recently added"))
        self.assertEqual(SM.state_block("signin", "recent")[1], "Apple Music sign-in expired")
        self.assertEqual(SM.state_block("error", "favourites")[1:], ("Library not loaded",
                                                                     "Go Home, then Browse to retry."))
        self.assertIsNone(SM.state_block("ready", "recent"))
        self.assertIsNone(SM.state_block("loading", "recent"))

    def test_heart_states_r22(self):
        """S5-34: liked filled; not liked outline 0.45; not known yet dashed 0.30; not in Apple
        Music outline 0.15 (never dashed); placeholder / card none."""
        row = {"catalog": True, "liked": True}
        self.assertEqual(SM.heart_state(row, True), "liked")
        self.assertEqual(SM.heart_state(dict(row, liked=False), True), "not_liked")
        self.assertEqual(SM.heart_state(dict(row, liked=None), True), "unknown")
        self.assertEqual(SM.heart_state(row, False), "unknown")
        self.assertEqual(SM.heart_state(dict(row, catalog=False), False), "not_catalog")
        self.assertEqual(SM.heart_state(row, True, placeholder=True), "none")
        self.assertEqual(SM.heart_state(row, True, card=True), "none")
        self.assertEqual(SM.HEART_LOOKS["not_liked"], (0.45, 0.0, 0.0))
        self.assertEqual(SM.HEART_LOOKS["unknown"], (0.0, 0.30, 0.0))
        self.assertEqual(SM.HEART_LOOKS["not_catalog"], (0.15, 0.0, 0.0))
        self.assertEqual(SM.HEART_LOOKS["liked"], (0.0, 0.0, 1.0))

    def test_rows(self):
        ctx = {"kind": "album", "title": "Hounds of Love", "sub": "Kate Bush · 1985"}
        base = {"title": "Cloudbusting", "artist": "Kate Bush", "album": "Hounds of Love", "segment": "base",
                "track_number": 5, "catalog": True}
        pn = dict(base, album="Blue Lines", artist="Massive Attack", segment="playnext")
        self.assertEqual(SM.row_lead(base, ctx), "number")
        self.assertEqual(SM.row_number(base), "05")
        self.assertEqual(SM.row_texts(base, ctx), ("Cloudbusting", "Kate Bush"))
        self.assertEqual(SM.row_lead(pn, ctx), "art")
        self.assertEqual(SM.row_texts(pn, ctx)[1], "Massive Attack · Blue Lines")
        self.assertEqual(SM.row_texts(dict(pn, catalog=False), ctx)[1], "Massive Attack · Blue Lines · not in Apple Music")
        self.assertEqual(SM.row_lead(base, {"kind": "playlist"}), "art")
        self.assertEqual(SM.row_lead(None, ctx, placeholder=True), "placeholder")
        self.assertEqual(SM.row_tag(3, 3)[0], "overlay.upnext.tag_now")
        self.assertEqual(SM.row_tag(3, 3)[1], (0x6E, 0xD9, 0x96))
        self.assertEqual(SM.row_tag(2, 3)[0], "overlay.upnext.tag_played")
        self.assertEqual(SM.row_tag(4, 3)[0], "overlay.upnext.tag_next")
        self.assertIsNone(SM.row_tag(5, 3))
        self.assertEqual(SM.card_texts(85), ("Sonos is shuffling the rest", "85 songs · order isn’t shown"))
        self.assertEqual(SM.placeholder_bar_width(1), 0.77)

    def test_hints_and_shuffle_line(self):
        self.assertEqual(SM.upnext_hints(False, False), (("1", "Back"), ("2", "Shuffle"), ("3", "Like"), ("4", "Play")))
        self.assertEqual(SM.upnext_hints(True, True)[1:3], (("2", "Shuffle off"), ("3", "Liked")))
        self.assertEqual(SM.shuffle_line("off"), ("In order", False))
        self.assertEqual(SM.shuffle_line("companion"), ("Shuffle on", True))
        self.assertEqual(SM.shuffle_line("sonos"), ("Shuffle on · Sonos picks the order", True))
        self.assertEqual(SM.EXPLORER_HINTS[2], ("3", "Playlists"))

    def test_big_cover_row(self):
        ctx = {"kind": "album", "title": "Hounds of Love"}
        rows = {0: {"album": "Hounds of Love", "segment": "base", "title": "a"},
                5: {"album": "Blue Lines", "segment": "playnext", "title": "b"}}
        self.assertEqual(SM.big_cover_row(rows, 5, 0, ctx)["title"], "a")        # the album's cover stays still
        self.assertEqual(SM.big_cover_row(rows, 5, 0, {"kind": "playlist"})["title"], "b")

    def test_motion_constants_are_app_a(self):
        from control_center.stage import motion_table as MT
        rows = {r[1]: r[4] for r in MT.APP_A if r[0] == "explorer"}
        self.assertEqual(rows["card.turn.x"], SM.TURN_MS)
        self.assertEqual(rows["card.enter.rise"], SM.ENTER_MS)
        self.assertEqual(rows["card.exit.rise"], SM.EXIT_MS)
        self.assertEqual(rows["play.grow"], SM.PLAY_GROW_MS)
        self.assertEqual(rows["ambient.crossfade"], SM.AMBIENT_MS)
        rows = {r[1]: r[4] for r in MT.APP_A if r[0] == "upnext"}
        self.assertEqual(rows["cover.crossfade"], SM.U_COVER_MS)
        self.assertEqual(rows["play.grow"], SM.U_PLAY_GROW_MS)
        self.assertEqual(rows["shuffle.exit"], SM.U_SHUFFLE_EXIT_MS)


# =========================================================================== scenes on the engine
def _rig(monitor="32:9", **kw):
    from control_center.stage.scenes import testing as T
    return T.SceneRig(monitor, keep_pixels=False, **kw)


def _payloads():
    from control_center.stage.scenes import testing as T
    return T


class ExplorerSceneTests(unittest.TestCase):
    def open(self, monitor="32:9", **kw):
        T = _payloads()
        rig = _rig(monitor)
        p = T.explorer_payload(rig.now(), **kw)
        rig.presenter.explorer_open(p)
        rig.settle()
        return rig, p

    def test_open_binds_the_range_and_staggers_the_entry(self):
        rig, p = self.open(index=4)
        self.assertEqual(rig.events(), [("opened", {"surface": "explorer"})])
        sc = rig.scene
        self.assertEqual(sorted(i for (_s, i) in sc.bound), list(range(0, 13)))      # 4 ± 8, clamped at 0
        c = sc.bound[(sc.set_id, 7)]                                                # a = 3
        a = _anim(rig.dev, c.box.ref.v3, "opacity")
        self.assertAlmostEqual(_lead_hold_s(a), 0.135, places=3)                    # 45 ms × a
        self.assertAlmostEqual(_end_s(a), 0.135 + 0.320, places=3)
        y = _anim(rig.dev, c.box.ptr, "offset_y")
        self.assertAlmostEqual(_end_s(y), 0.135 + 0.440, places=3)
        self.assertEqual(rig.host.input.hit_rect if hasattr(rig, "host") else rig.engine.input.hit_rect,
                         (2220, 296, 2900, 976))
        self.assertEqual(rig.dev.violations, [])

    def test_art_lands_with_the_240_ms_fade_and_the_loading_tile_first(self):
        rig, p = self.open(index=4)
        rig.land()                                                # S1: revealed a frame after its upload Commit
        sc = rig.scene
        c = sc.bound[(sc.set_id, 4)]
        self.assertIsNotNone(c.bound[0])                          # L1 art on the centre card
        self.assertIsNotNone(c.bound[1])                          # L0 (the 1200 rung) too
        self.assertIsNotNone(c.bound[2])                          # the loading tile landed first
        a = _anim(rig.dev, c.art.ref.v3, "opacity")
        self.assertIsNotNone(a)
        self.assertAlmostEqual(_end_s(a), 0.240, places=3)

    def test_turn_retargets_on_the_turn_curves_and_swaps_the_label(self):
        rig, p = self.open(index=4)
        rig.advance(800, 100)
        sc = rig.scene
        label_before = sc.label_shown
        rig.presenter.explorer_highlight({"index": 5, "control_id": 1, "bump": 0})
        rig.settle()
        c = sc.bound[(sc.set_id, 6)]                              # from a = 2 to a = 1
        self.assertAlmostEqual(_end_s(_anim(rig.dev, c.box.ptr, "offset_x")), 0.420, places=3)
        self.assertAlmostEqual(_end_s(_anim(rig.dev, c.box.ref.v3, "opacity")), 0.300, places=3)
        self.assertAlmostEqual(_end_s(_anim(rig.dev, c.shade.ref.v3, "opacity")), 0.320, places=3)
        bound = {c.box.ptr for c in sc.bound.values()}                           # free cards are invisible
        stack = [v for v in rig.dev.obj(sc.cards_box.ptr)["children"] if v in bound]
        self.assertEqual(stack[-1], sc.bound[(sc.set_id, 5)].box.ptr)              # the focus on top
        self.assertNotEqual(sc.label_shown, label_before)
        v, op = sc.labels[sc.label_front]
        self.assertAlmostEqual(_end_s(_anim(rig.dev, v.ref.v3, "opacity")), 0.160, places=3)
        self.assertAlmostEqual(_end_s(_anim(rig.dev, sc.marker_v.ptr, "offset_x")), 0.420, places=3)
        self.assertEqual(rig.dev.violations, [])

    def test_l0_crossfades_across_d_1_and_2(self):
        rig, p = self.open(index=4)
        rig.advance(800, 100)
        sc = rig.scene
        rig.presenter.explorer_highlight({"index": 5, "control_id": 1, "bump": 0})
        rig.settle()
        old = sc.bound[(sc.set_id, 3)]                            # a 1 -> 2: L0 fades out on the turn curve
        a = _anim(rig.dev, old.l0.ref.v3, "opacity")
        self.assertAlmostEqual(_end_s(a), 0.420, places=3)
        self.assertEqual(a["end"][1], 0.0)

    def test_end_bump_is_two_160_ms_legs(self):
        rig, p = self.open(index=0)
        rig.presenter.explorer_highlight({"index": 0, "control_id": 1, "bump": -1})
        rig.settle()
        a = _anim(rig.dev, rig.scene.cards_box.ptr, "offset_x")
        self.assertAlmostEqual(_end_s(a), 0.320, places=3)
        self.assertAlmostEqual(a["end"][1], 0.0)
        vals = [s[1] for s in a["segs"]]
        self.assertAlmostEqual(max(vals), 28.0, delta=0.5)        # −14 · k · dir with dir −1

    def test_source_switch_is_anchored_to_t0_and_discards_old_positions(self):
        T = _payloads()
        rig, p = self.open(index=3)
        rig.advance(600, 100)
        sc = rig.scene
        fav = T.explorer_payload(rig.now(), source="favourites", index=1)
        sw = {k: fav[k] for k in ("t0", "source", "state", "index", "count", "items", "items_first")}
        sw["items_rev"] = 5
        old_cards = [c for c in sc.bound.values() if c.set == sc.set_id and c.o.target > 0]
        rig.presenter.explorer_source(sw)
        rig.presenter.position(1, 7)                               # the old control's position: discarded
        rig.settle()
        self.assertTrue(sc.swapping(rig.clk.t))
        self.assertEqual(sc.source, "favourites")
        self.assertEqual(sc.focus, 1)
        for c in old_cards:                                        # exit: 170 ms IN at t0
            a = _anim(rig.dev, c.box.ref.v3, "opacity")
            self.assertAlmostEqual(_end_s(a), 0.170, delta=0.002)
        new = sc.bound[(sc.set_id, 1)]
        a = _anim(rig.dev, new.box.ref.v3, "opacity")
        self.assertAlmostEqual(_lead_hold_s(a), 0.190, delta=0.005)                # enters at t0 + 190
        op, sx = sc.tabs["favourites"]
        self.assertAlmostEqual(_end_s(_anim(rig.dev, sx.fset[0][1], "scale_x")), 0.320, delta=0.002)
        self.assertGreaterEqual(rig.engine.counters["positions_discarded"], 1)
        rig.advance(400, 100)
        self.assertFalse(sc.swapping(rig.clk.t))
        self.assertEqual(rig.dev.violations, [])

    def test_state_change_into_and_out_of_a_block(self):
        rig, p = self.open(source="favourites", index=0)
        rig.advance(500, 100)
        sc = rig.scene
        t_change = rig.clk.t
        rig.presenter.explorer_highlight({"index": 0, "control_id": 1, "bump": 0, "state": "empty", "count": 0,
                                          "items": [], "items_first": 0, "items_rev": 9})
        rig.land()                                                # S1: the block's static lands a frame later
        self.assertEqual(sc.block_shown, ("empty", "favourites"))
        v, op = sc.blocks[sc.block_front]
        a = _anim(rig.dev, v.ref.v3, "opacity")
        start = a["begin"] + _lead_hold_s(a) * rig.clk.freq        # still fades in at t + 190 (its anchor)
        self.assertAlmostEqual((start - t_change) / rig.clk.freq, 0.190, delta=0.0065)
        self.assertIsNone(sc.hit_rect())
        rig.advance(600, 100)
        self.assertEqual([c for c in sc.bound.values() if c.set == sc.set_id], [])
        T = _payloads()
        back = T.explorer_payload(rig.now(), source="favourites", index=0)
        rig.presenter.explorer_highlight({"index": 0, "control_id": 1, "bump": 0, "state": "ready",
                                          "count": back["count"], "items": back["items"], "items_first": 0,
                                          "items_rev": 10})
        rig.settle()
        self.assertIsNone(sc.block_shown)
        self.assertTrue([c for c in sc.bound.values() if c.set == sc.set_id])
        self.assertEqual(rig.dev.violations, [])

    def test_loading_list_shows_neutral_cards_then_the_items(self):
        T = _payloads()
        rig, p = self.open(index=0, state="loading")
        sc = rig.scene
        self.assertEqual(sorted(i for (_s, i) in sc.bound), list(range(0, 9)))       # S5-11: ≥ 0 when unknown
        self.assertTrue(all(c.plan is None for c in sc.bound.values()))
        self.assertIsNone(sc.label_shown)
        full = T.explorer_payload(rig.now(), index=0)
        rig.presenter.explorer_highlight({"index": 0, "control_id": 1, "bump": 0, "state": "ready",
                                          "count": full["count"], "items": full["items"], "items_first": 0,
                                          "items_rev": 2})
        rig.land()                                                # S1: the label lands a frame after its upload
        self.assertTrue(all(c.plan is not None for c in sc.bound.values() if c.set == sc.set_id))
        self.assertIsNotNone(sc.label_shown)

    def test_thin_list_has_neighbours_on_the_right_only(self):
        rig, p = self.open(source="favourites", index=0)
        sc = rig.scene
        self.assertEqual(sorted(i for (_s, i) in sc.bound), [0, 1])
        self.assertEqual(sc.dots_shown, (2, False, False))

    def test_play_grows_the_centre_and_closes_at_380(self):
        rig, p = self.open(index=4)
        rig.advance(800, 100)
        rig.events()
        sc = rig.scene
        t0 = rig.now()
        rig.presenter.explorer_close({"t0": t0, "reason": "play", "close_at_ms": 380})
        rig.settle()
        c = sc.bound[(sc.set_id, 4)]
        a = _anim(rig.dev, c.e.fset[0][1], "scale_x")
        self.assertAlmostEqual(a["end"][1], 1.12, places=4)
        self.assertAlmostEqual(_end_s(a), 0.380, delta=0.005)
        other = sc.bound[(sc.set_id, 5)]
        self.assertEqual(_anim(rig.dev, other.box.ref.v3, "opacity")["end"][1], 0.0)
        self.assertTrue(sc.swapping(rig.clk.t))
        root = _anim(rig.dev, rig.engine.root.ref.v3, "opacity")
        self.assertAlmostEqual(_lead_hold_s(root), 0.380, delta=0.005)
        rig.advance(900, 100)
        self.assertEqual(rig.events(), [("closed", {"surface": "explorer", "reason": "play"})])

    def test_reduced_motion(self):
        rig, p = self.open(index=4, reduced_motion=True)
        sc = rig.scene
        c = sc.bound[(sc.set_id, 6)]
        self.assertIsNone(_anim(rig.dev, c.box.ptr, "offset_y"))            # no rise
        self.assertAlmostEqual(_end_s(_anim(rig.dev, c.box.ref.v3, "opacity")), 0.200, places=3)
        rig.advance(600, 100)
        rig.presenter.explorer_highlight({"index": 5, "control_id": 1, "bump": 1})
        rig.settle()
        self.assertIsNone(_anim(rig.dev, sc.cards_box.ptr, "offset_x"))     # no bump
        self.assertIsNone(_anim(rig.dev, c.box.ptr, "offset_x"))            # cards jump
        rig.presenter.explorer_close({"t0": rig.now(), "reason": "play", "close_at_ms": 380})
        rig.settle()
        self.assertIsNone(_anim(rig.dev, sc.bound[(sc.set_id, 5)].e.fset[0][1], "scale_x"))   # no Play grow

    def test_ambient_crossfades_200_ms_after_the_last_detent(self):
        rig, p = self.open(index=4)
        rig.advance(800, 100)
        sc = rig.scene
        for idx in (5, 6, 7):
            rig.presenter.explorer_highlight({"index": idx, "control_id": 1, "bump": 0})
            rig.settle()
            rig.advance(50)
        gen_before = sc.ambient.gen
        self.assertEqual(sc.ambient.shown, sc.plan_of(4).key)       # a fast spin builds nothing
        rig.advance(250, 50)
        self.assertEqual(sc.ambient.shown, sc.plan_of(7).key)
        v, op, key = sc.ambient.layers[sc.ambient.front]
        a = _anim(rig.dev, v.ref.v3, "opacity")
        self.assertAlmostEqual(_end_s(a), 0.600, places=3)
        self.assertAlmostEqual(a["end"][1], 0.50)
        self.assertGreater(sc.ambient.gen, gen_before - 1)

    def test_16x9_uses_its_table_and_a_long_spin_recycles_cards(self):
        rig, p = self.open(monitor="16:9", index=2, recent="many")
        sc = rig.scene
        self.assertEqual(sc.a_max, 4)
        first = 0
        from control_center.stage.scenes import bench as B
        items = [dict(i) for i in p["items"]]
        for idx in range(3, 40):
            rig.presenter.explorer_highlight({"index": idx, "control_id": 1, "bump": 0})
            rig.settle()
            rig.clk.advance(0.05)
        self.assertEqual(sc.focus, min(39, p["count"] - 1))
        self.assertGreater(sc.counters["recycled"], 20)
        self.assertLessEqual(len([c for c in sc.bound.values() if c.set == sc.set_id]), 2 * 4 + 1 + 12)
        self.assertEqual(rig.dev.violations, [])

    def test_simulated_loading_art_keeps_the_loading_tile(self):
        rig, p = self.open(index=2, art="loading")
        rig.land()
        sc = rig.scene
        c = sc.bound[(sc.set_id, 2)]
        self.assertEqual(c.plan.kind, "never")
        self.assertIsNone(c.bound[0])
        self.assertIsNotNone(c.bound[2])

    def test_block_states_open_on_the_block(self):
        for state, title in (("signin", "Apple Music sign-in expired"), ("error", "Library not loaded")):
            rig, p = self.open(index=0, state=state)
            sc = rig.scene
            self.assertEqual(sc.block_shown, (state, "recent"))
            self.assertEqual(sc.bound, {})
            self.assertIsNone(sc.hit_rect())

    def test_every_turn_stays_within_a_detent_call_budget(self):
        """G1-4: only what changed; a detent on the 32:9 table stays in the probe's range."""
        rig, p = self.open(index=40, recent="many")
        rig.advance(800, 100)
        sc = rig.scene
        for idx in range(41, 51):
            rig.presenter.explorer_highlight({"index": idx, "control_id": 1, "bump": 0})
            rig.settle()
            rig.clk.advance(0.05)
        self.assertLess(max(sc.stats["turn_calls"]), 600)


class UpNextSceneTests(unittest.TestCase):
    def open(self, monitor="32:9", **kw):
        T = _payloads()
        rig = _rig(monitor)
        p = T.upnext_payload(rig.now(), **kw)
        rig.presenter.upnext_open(p)
        rig.settle()
        return rig, p

    def test_open(self):
        rig, p = self.open(kind="album", now=4, liked=(3,))
        self.assertEqual(rig.events(), [("opened", {"surface": "upnext"})])
        sc = rig.scene
        self.assertEqual(sorted(i for (_s, i) in sc.bound), list(range(0, 9)))
        r = sc.bound[(sc.set_id, 4)]
        self.assertEqual(r.spec[1], "number")
        self.assertEqual(r.spec[5][0], "overlay.upnext.tag_now")
        self.assertEqual(sc.bound[(sc.set_id, 5)].spec[5][0], "overlay.upnext.tag_next")
        self.assertEqual(sc.bound[(sc.set_id, 3)].spec[6], "liked")
        self.assertEqual(sc.bound[(sc.set_id, 2)].spec[6], "not_liked")
        self.assertAlmostEqual(_end_s(_anim(rig.dev, sc.left.ptr, "offset_y")), 0.460, places=3)
        self.assertAlmostEqual(_end_s(_anim(rig.dev, sc.plate.ref.v3, "opacity")), 0.320, places=3)
        a = _anim(rig.dev, sc.bound[(sc.set_id, 6)].box.ref.v3, "opacity")
        self.assertAlmostEqual(_lead_hold_s(a), 0.080, places=3)                    # 40 ms × a
        self.assertEqual(rig.engine.input.hit_rect, (2480, 552, 3600, 728))
        self.assertEqual(sc.hints_shown, (False, False))
        self.assertEqual(rig.dev.violations, [])

    def test_heart_states_are_wp6s(self):
        """The scene's rule is WP6's ``apple_music.heart_state`` once likes are known ([r2.2])."""
        from control_center import apple_music
        for catalog in (True, None, False):
            for liked in (True, False, None):
                self.assertEqual(SM.heart_state({"catalog": catalog, "liked": liked}, True),
                                 apple_music.heart_state(catalog=catalog, liked=liked), (catalog, liked))

    def test_hearts_rest_forms(self):
        rig, p = self.open(kind="album", now=4, liked=(3,))
        sc = rig.scene
        t = rig.clk.t
        liked, plain = sc.bound[(sc.set_id, 3)], sc.bound[(sc.set_id, 2)]
        self.assertEqual((liked.out_o.value(t), liked.dash_o.value(t), liked.fill_o.value(t)), (0.0, 0.0, 1.0))
        self.assertEqual((plain.out_o.value(t), plain.dash_o.value(t), plain.fill_o.value(t)), (0.45, 0.0, 0.0))
        rig2, p2 = self.open(kind="album", now=4, likes="unknown")
        sc2 = rig2.scene
        r = sc2.bound[(sc2.set_id, 2)]
        self.assertEqual((r.out_o.value(rig2.clk.t), r.dash_o.value(rig2.clk.t)), (0.0, 0.30))
        rig3, p3 = self.open(kind="playlist", foreign=True, now=4)
        sc3 = rig3.scene
        r = sc3.bound[(sc3.set_id, 5)]                                              # row 6: every third
        self.assertEqual(r.spec[6], "not_catalog")
        self.assertEqual(r.out_o.value(rig3.clk.t), 0.15)
        self.assertTrue(r.spec[4].endswith(" · not in Apple Music"))

    def test_a_likes_patch_pops_the_heart(self):
        rig, p = self.open(kind="album", now=4)
        rig.advance(800, 100)
        sc = rig.scene
        rig.presenter.upnext_rows({"t0": rig.now(), "reason": "likes", "rows": [{"row": 5, "liked": True}], "now": 4,
                                   "focus": 4, "count": p["count"], "card": None, "shuffle": "off",
                                   "likes_known": True})
        rig.settle()
        r = sc.bound[(sc.set_id, 4)]
        scale = _anim(rig.dev, r.fill_s.fset[0][1], "scale_x")
        self.assertAlmostEqual(scale["segs"][0][1], 0.4, places=5)
        self.assertAlmostEqual(_end_s(scale), 0.800, places=3)                      # 380 + hold + 380 (S5-31)
        self.assertAlmostEqual(_end_s(_anim(rig.dev, r.hfill_box.ref.v3, "opacity")), 0.200, places=3)
        self.assertEqual(sc.hints_shown, (False, True))                              # [3] Liked

    def test_a_data_patch_sets_hearts_without_a_pop(self):
        rig, p = self.open(kind="album", now=4, likes="unknown")
        rig.advance(800, 100)
        sc = rig.scene
        rows = [dict(r, liked=(r["row"] == 6)) for r in p["rows"]]
        rig.presenter.upnext_rows({"t0": rig.now(), "reason": "data", "rows": rows, "now": 4, "focus": 4,
                                   "count": p["count"], "card": None, "shuffle": "off", "likes_known": True})
        rig.settle()
        r = sc.bound[(sc.set_id, 5)]
        self.assertIsNone(_anim(rig.dev, r.fill_s.fset[0][1], "scale_x"))          # no pop
        self.assertAlmostEqual(_end_s(_anim(rig.dev, r.hfill_box.ref.v3, "opacity")), 0.200, places=3)
        self.assertEqual(sc.bound[(sc.set_id, 3)].out_o.value(rig.clk.t), 0.45)

    def test_turn_and_the_playlist_cover_debounce(self):
        rig, p = self.open(kind="playlist", now=4)
        rig.advance(800, 100)
        sc = rig.scene
        cover_before = sc.cover_key
        rig.presenter.upnext_highlight({"index": 5, "control_id": 1, "bump": 0})
        rig.settle()
        r = sc.bound[(sc.set_id, 6)]
        self.assertAlmostEqual(_end_s(_anim(rig.dev, r.box.ptr, "offset_y")), 0.420, places=3)
        self.assertEqual(sc.cover_key, cover_before)
        rig.advance(60)
        self.assertEqual(sc.cover_key, cover_before)                               # still inside the 120 ms
        rig.advance(120, 20)
        self.assertNotEqual(sc.cover_key, cover_before)
        v, op, key = sc.covers[sc.cover_front]
        self.assertAlmostEqual(_end_s(_anim(rig.dev, v.ref.v3, "opacity")), 0.420, places=3)

    def test_album_cover_stays_still(self):
        rig, p = self.open(kind="album", now=4)
        rig.advance(600, 100)
        sc = rig.scene
        key = sc.cover_key
        for idx in (5, 6, 7):
            rig.presenter.upnext_highlight({"index": idx, "control_id": 1, "bump": 0})
            rig.settle()
        rig.advance(400, 50)
        self.assertEqual(sc.cover_key, key)

    def test_shuffle_fades_out_at_t0_and_reenters_at_200(self):
        rig, p = self.open(kind="playlist", now=4)
        rig.advance(800, 100)
        sc = rig.scene
        old = [r for r in sc.bound.values() if r.set == sc.set_id and r.o.target > 0]
        rows = [dict(r, row=j + 1) for j, r in enumerate(p["rows"][:5] + list(reversed(p["rows"][5:])))]
        rig.presenter.upnext_rows({"t0": rig.now(), "reason": "shuffle", "rows": rows, "now": 4, "focus": 5,
                                   "count": p["count"], "card": None, "shuffle": "companion", "likes_known": True})
        rig.settle()
        for r in old:
            a = _anim(rig.dev, r.box.ref.v3, "opacity")
            self.assertAlmostEqual(_end_s(a), 0.160, delta=0.002)
        new = sc.bound[(sc.set_id, 5)]
        a = _anim(rig.dev, new.box.ref.v3, "opacity")
        self.assertAlmostEqual(_lead_hold_s(a), 0.200, delta=0.005)
        self.assertTrue(sc.swapping(rig.clk.t))
        v, op = sc.shuffles[sc.shuffle_front]
        a = _anim(rig.dev, v.ref.v3, "opacity")
        self.assertAlmostEqual(_lead_hold_s(a), 0.200, delta=0.005)
        self.assertAlmostEqual(_end_s(a), 0.440, delta=0.005)
        rig.advance(300, 50)
        self.assertFalse(sc.swapping(rig.clk.t))
        self.assertEqual(sc.hints_shown, (True, False))

    def test_loading_rows_fill_in_with_a_160_ms_fade(self):
        rig, p = self.open(kind="playlist", now=4, loaded=False)
        sc = rig.scene
        self.assertEqual(sc.bound[(sc.set_id, 5)].spec[0], "placeholder")
        T = _payloads()
        full = T.upnext_payload(rig.now(), kind="playlist", now=4)
        rig.advance(600, 100)
        rig.presenter.upnext_rows({"t0": rig.now(), "reason": "data", "rows": full["rows"], "now": 4, "focus": 4,
                                   "count": full["count"], "card": None, "shuffle": "off", "likes_known": True})
        rig.land()                                                # S1: the row sprite lands a frame later
        r = sc.bound[(sc.set_id, 5)]
        self.assertEqual(r.spec[0], "row")
        self.assertAlmostEqual(_end_s(_anim(rig.dev, r.box.ref.v3, "opacity")), 0.160, places=3)

    def test_sonos_card(self):
        rig, p = self.open(kind="playlist", now=4, card={"n": 85}, shuffle="sonos")
        sc = rig.scene
        r = sc.bound[(sc.set_id, 5)]
        self.assertEqual(r.spec[0], "card")
        self.assertEqual(r.spec[3], "Sonos is shuffling the rest")
        self.assertEqual(r.spec[6], "none")
        self.assertEqual(sc.shuffle_shown, ("Shuffle on · Sonos picks the order", True))

    def test_play(self):
        rig, p = self.open(kind="album", now=4)
        rig.advance(600, 100)
        sc = rig.scene
        rig.presenter.upnext_close({"t0": rig.now(), "reason": "play", "close_at_ms": 380})
        rig.settle()
        r = sc.bound[(sc.set_id, 4)]
        a = _anim(rig.dev, r.S.fset[0][1], "scale_x")
        self.assertAlmostEqual(a["end"][1], 1.06, places=4)
        self.assertAlmostEqual(_end_s(a), 0.420, delta=0.005)
        self.assertAlmostEqual(_end_s(_anim(rig.dev, sc.plate.ref.v3, "opacity")), 0.320, delta=0.005)
        self.assertIsNone(sc.hit_rect())

    def test_reduced_motion(self):
        rig, p = self.open(kind="album", now=4, reduced_motion=True)
        sc = rig.scene
        r = sc.bound[(sc.set_id, 6)]
        self.assertAlmostEqual(_end_s(_anim(rig.dev, r.box.ref.v3, "opacity")), 0.200, places=3)
        self.assertIsNone(_anim(rig.dev, r.box.ptr, "offset_x"))
        rig.advance(600, 100)
        rig.presenter.upnext_highlight({"index": 5, "control_id": 1, "bump": 1})
        rig.settle()
        self.assertIsNone(_anim(rig.dev, sc.rows_box.ptr, "offset_y"))

    def test_sharpen_pass_at_rest_and_discard_on_the_first_turn(self):
        """§8.6 (AR-17, S5-27): 150 ms after the rows settle, rows with a != 0 get exact-scale text
        sprites crossfaded in over 120 ms OUT; the first turn discards them."""
        rig, p = self.open(kind="album", now=4)
        sc = rig.scene
        rig.advance(1000, 50)
        sharp = [r for r in sc.bound.values() if r.sharp_key is not None]
        self.assertEqual(sorted(r.index for r in sharp), [1, 2, 3, 5, 6, 7])        # a = 1..3, not the focus
        r = sc.bound[(sc.set_id, 5)]
        self.assertEqual(r.sharp_key[2], round(2.0 * 0.78, 4))                     # drawn at k × S
        self.assertAlmostEqual(_end_s(_anim(rig.dev, r.sharp.ref.v3, "opacity")), 0.120, places=3)
        self.assertEqual(rig.dev.obj(r.sharp.ptr)["props"]["transform"][1][0], round(1 / 0.78, 4))
        rig.presenter.upnext_highlight({"index": 5, "control_id": 1, "bump": 0})
        rig.settle()
        self.assertEqual([x for x in sc.bound.values() if x.sharp_key is not None], [])
        self.assertEqual(r.sharp_o.value(rig.clk.t), 0.0)
        self.assertEqual(r.text_o.value(rig.clk.t), 1.0)
        rig.advance(1000, 50)
        self.assertTrue([x for x in sc.bound.values() if x.sharp_key is not None])

    def test_a_spin_schedules_no_sharpen_work(self):
        rig, p = self.open(kind="playlist", now=40, rows=90)
        rig.advance(800, 100)
        sc = rig.scene
        jobs = rig.art.stats["jobs"]
        for idx in range(41, 49):
            rig.presenter.upnext_highlight({"index": idx, "control_id": 1, "bump": 0})
            rig.settle()
            rig.advance(50)
        self.assertEqual([x for x in sc.bound.values() if x.sharp_key is not None], [])
        self.assertTrue(all(not isinstance(tag, tuple) or tag[0] != "sharpen" or tag[1] == sc.sharp_gen
                            for tag in sc.tick_tags.values()))

    def test_turn_budget(self):
        rig, p = self.open(kind="playlist", now=40, rows=90)
        rig.advance(800, 100)
        sc = rig.scene
        for idx in range(41, 51):
            rig.presenter.upnext_highlight({"index": idx, "control_id": 1, "bump": 0})
            rig.settle()
            rig.clk.advance(0.05)
        self.assertLess(max(sc.stats["turn_calls"]), 300)
        self.assertEqual(rig.dev.violations, [])


# =========================================================================== review fixes (WP8-R1 ... R11)
def _alive_surfaces(dev):
    """{key kind: (count, bytes)} of every surface still alive on the fake device."""
    out = {}
    for o in dev.objects.values():
        if o["kind"] != "surface" or o["released"]:
            continue
        name = o.get("name", "")
        kind = name.split("'")[1] if name.startswith("(") and "'" in name else name.split("(")[0]
        w, h = o["size"]
        n, b = out.get(kind, (0, 0))
        out[kind] = (n + 1, b + w * h * 4)
    return out


def _jpeg(edge):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (int(edge), int(edge)), (40, 60, 90)).save(buf, "JPEG", quality=80)
    return buf.getvalue()


class _RecordingStore:
    """A fake ``artwork.CoverStore``: records (template, rung, has cancelled) and returns a JPEG of
    the rung's size; nothing is fetched."""

    def __init__(self):
        self.calls = []

    def fetch(self, template=None, rung=None, *, sonos_url=None, speaker_host=None, cancelled=None):
        self.calls.append((template or sonos_url, rung, cancelled is not None))
        return _jpeg(rung or 400)


class _BlockingStore:
    """A fake ``CoverStore`` whose fetch blocks (a slow CDN) until ``release`` is set, polling
    ``cancelled`` like ``artwork._fetch`` does per chunk."""

    def __init__(self):
        import threading
        self.release = threading.Event()
        self.started = threading.Semaphore(0)
        self.calls = []

    def fetch(self, template=None, rung=None, *, sonos_url=None, speaker_host=None, cancelled=None):
        from control_center.artwork import ArtworkCancelled
        self.calls.append((template or sonos_url, rung, cancelled is not None))
        self.started.release()
        while not self.release.wait(0.005):
            if cancelled is not None and cancelled():
                raise ArtworkCancelled("Artwork selection changed.")
        return _jpeg(rung or 400)


class _Landings:
    """An upload target recording when each key was posted (perf seconds); thread-safe."""

    def __init__(self):
        import threading
        self.lock = threading.Lock()
        self.at = {}

    def put(self, key, w, h, data, *, opaque=False, done=None, priority=0, tick=False):
        import time
        with self.lock:
            self.at[key] = time.perf_counter()

    def wait_for(self, key, timeout):
        import time
        end = time.perf_counter() + timeout
        while time.perf_counter() < end:
            with self.lock:
                if key in self.at:
                    return self.at[key]
            time.sleep(0.002)
        return None


def _cover(n, art_max=1200):
    return SM.cover_plan({"title": f"Album {n}", "artist": "A",
                          "art_template": f"https://is1-ssl.mzstatic.com/image/thumb/a{n}/{{w}}x{{h}}bb.jpg",
                          "art_max": art_max, "art_bg": 0x203040, "art_ink": 0xF0F0F0})


class ArtLaneTests(unittest.TestCase):
    """WP8-R1: ticks and text never wait behind a cover fetch; running fetches are cancelled."""

    def service(self, store):
        from control_center.stage.scenes.art import ArtService
        svc = ArtService(cover_store=store, workers=2)
        self.addCleanup(svc.close, 1.0)
        self.addCleanup(store.release.set)
        return svc

    def test_ticks_and_labels_land_on_time_while_both_art_workers_fetch(self):
        import time
        from control_center import render_music as RM
        from control_center.stage.scenes.art import Job, LANE_ART, _PRIO_FOCUS, _PRIO_NEAR, _PRIO_TICK
        store = _BlockingStore()
        svc = self.service(store)
        up = _Landings()
        for n in range(4):
            plan = _cover(n)
            svc.add(Job(("art", plan.key, "card", 340), (_PRIO_NEAR, n, 0, 3),
                        (lambda plan=plan: svc.element(plan, 340, units=340, need0=680, src_need=340)),
                        uploads=up, owner="o", lane=LANE_ART))
        for _ in range(2):                                       # both art workers are inside a fetch
            self.assertTrue(store.started.acquire(timeout=5.0))
        t0 = time.perf_counter()
        svc.add(Job(("tick", "o", 1), _PRIO_TICK, lambda: RM.Sprite.new(1, 1), uploads=up, owner="o",
                    not_before=t0 + 0.15))
        svc.add(Job(("label", "x", 2.0), (_PRIO_FOCUS, 0, 0, 0), lambda: RM.Sprite.new(8, 8), uploads=up, owner="o"))
        t_label = up.wait_for(("label", "x", 2.0), 2.0)
        t_tick = up.wait_for(("tick", "o", 1), 2.0)
        self.assertIsNotNone(t_label)
        self.assertIsNotNone(t_tick)
        self.assertLess(t_label - t0, 0.10)                      # not behind a fetch (was +1.5 s)
        self.assertGreaterEqual(t_tick - t0, 0.15 - 0.002)
        self.assertLess(t_tick - t0, 0.15 + 0.10)                # the +190 / +120 / +200 legs keep their time
        self.assertFalse(store.release.is_set())
        self.assertFalse([k for k in up.at if k[0] == "art"])     # the fetches were still running
        self.assertTrue(all(c[2] for c in store.calls))          # CoverStore.fetch(cancelled=...)

    def test_a_running_fetch_stops_when_the_plan_drops_it_and_is_no_failure(self):
        import time
        from control_center.stage.scenes.art import Job, LANE_ART
        store = _BlockingStore()
        svc = self.service(store)
        up = _Landings()
        plan = _cover(7)
        key = ("art", plan.key, "card", 340)

        def planner(service, snap):
            return [Job(key, (2, 0), (lambda: svc.element(plan, 340, units=340, need0=680, src_need=340)),
                        uploads=up, lane=LANE_ART)] if snap else []
        svc.plan("o", planner, True)
        self.assertTrue(store.started.acquire(timeout=5.0))
        svc.plan("o", planner, False)                            # the item left the window (§13.4 item 1)
        end = time.perf_counter() + 2.0
        while time.perf_counter() < end and svc.stats["cancelled"] < 1:
            time.sleep(0.005)
        self.assertEqual(svc.stats["cancelled"], 1)
        self.assertEqual(svc.stats["failures"], 0)
        self.assertFalse(svc.failed_recently(plan.key))           # no 30 s back-off for a cancel
        self.assertNotIn(key, up.at)

    def test_a_closed_scene_cancels_its_running_fetches(self):
        import time
        from control_center.stage.scenes.art import Job, LANE_ART
        store = _BlockingStore()
        svc = self.service(store)
        plan = _cover(8)
        svc.add(Job(("art", plan.key, "cover", 760), (1, 0), (lambda: svc.element(plan, 760, units=380, need0=760)),
                    owner="scene#1", lane=LANE_ART))
        self.assertTrue(store.started.acquire(timeout=5.0))
        svc.forget("scene#1")
        end = time.perf_counter() + 2.0
        while time.perf_counter() < end and svc.stats["cancelled"] < 1:
            time.sleep(0.005)
        self.assertEqual(svc.stats["cancelled"], 1)

    def test_two_jobs_compute_at_once_and_a_tick_needs_no_slot(self):
        """The third thread adds no GIL traffic: at most ``workers`` jobs hold a CPU slot; a tick
        takes none, so it lands on time while both slots are busy."""
        import threading
        import time
        from control_center import render_music as RM
        from control_center.stage.scenes.art import Job, _PRIO_TICK
        store = _BlockingStore()
        svc = self.service(store)
        up = _Landings()
        lock = threading.Lock()
        state = {"now": 0, "max": 0}

        def busy():
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            time.sleep(0.12)                                     # holds its slot (not the GIL)
            with lock:
                state["now"] -= 1
            return RM.Sprite.new(2, 2)
        for n in range(5):
            svc.add(Job(("label", n, 2.0), (1, n), busy, uploads=up))
        t0 = time.perf_counter()
        svc.add(Job(("tick", "o", 9), _PRIO_TICK, lambda: RM.Sprite.new(1, 1), uploads=up, not_before=t0 + 0.05))
        t_tick = up.wait_for(("tick", "o", 9), 2.0)
        for n in range(5):
            self.assertIsNotNone(up.wait_for(("label", n, 2.0), 3.0))
        self.assertIsNotNone(t_tick)
        self.assertLess(t_tick - t0, 0.05 + 0.06)
        self.assertEqual(state["max"], 2)

    def test_the_planners_put_only_art_elements_on_the_fetch_lane(self):
        from control_center.stage.scenes import explorer as EX, upnext as UP
        from control_center.stage.scenes.art import ArtService, LANE_ART, LANE_FAST
        art = ArtService(sync=True, cover_store=_RecordingStore())
        up = _Landings()
        a, b = _cover(1), _cover(2)
        snap = (10, 1, [10, 15], {10: a, 15: b}, frozenset({10}), [(10, ("A", "B", "C"))], set(),
                (340, 680, 2.0), (up, None), SM.CARD_UNITS)
        lanes = {job.key[0]: set() for job in EX.explorer_planner(art, snap)}
        for job in EX.explorer_planner(art, snap):
            lanes[job.key[0]].add(job.lane)
        self.assertEqual(lanes, {"load": {LANE_FAST}, "art": {LANE_ART}, "label": {LANE_FAST}})
        T = _payloads()
        p = T.upnext_payload(0.0, kind="playlist", now=4)
        rows = SM.rows_by_index(p["rows"])
        specs = [(i, UP.row_spec(i, rows, 4, p["count"], None, p["context"], True)) for i in (4, 5)]
        jobs = UP.upnext_planner(art, (4, specs, [SM.big_cover_plan(rows[4])], set(), (2.0, 112, 760), (up, None)))
        kinds = {(job.key[0], job.lane) for job in jobs}
        self.assertEqual(kinds, {("row", LANE_FAST), ("art", LANE_ART), ("load", LANE_FAST)})


class ArtRungTests(unittest.TestCase):
    """WP8-R3: §7.7 / §13.1 rungs per job kind (L1 600, L0 1200, big cover 1200, row lead 240)."""

    def test_rung_per_job_kind(self):
        from control_center.stage.scenes import explorer as EX, upnext as UP
        from control_center.stage.scenes.art import ArtService
        store = _RecordingStore()
        art = ArtService(sync=True, cover_store=store)
        up = _Landings()
        l0, l1 = _cover(1), _cover(2)
        snap = (10, 0, [10, 15], {10: l0, 15: l1}, frozenset({10}), [], set(), (340, 680, 2.0), (up, None),
                SM.CARD_UNITS)
        rungs = {}
        for job in EX.explorer_planner(art, snap):
            if job.key[0] != "art":
                continue
            before = len(store.calls)
            job.fn()
            rungs[job.key[1]] = [c[1] for c in store.calls[before:]]
        self.assertEqual(rungs[l1.key], [600])                   # L1 only: its own need, 340 -> 600
        self.assertEqual(rungs[l0.key], [1200])                  # L0 (+ L1 from the same decode)
        self.assertIn(("art", l0.key, "card", 340), up.at)
        before = len(store.calls)
        big = art.element(_cover(3), 760, units=SM.U_COVER, need0=760, variant="cover")
        self.assertEqual([c[1] for c in store.calls[before:]], [1200])
        self.assertEqual(big.size, (760, 760))
        before = len(store.calls)
        UP._row_art(art, _cover(4), 112)()
        self.assertEqual([c[1] for c in store.calls[before:]], [240])

    def test_the_l1_rung_keeps_the_extended_decision_of_the_item(self):
        """§13.5 is per item (need0 = L0's 680): a 1200 source is art.full from the 600 rung; a
        400 source is art.extended at L1 exactly as at L0."""
        from control_center.stage.scenes.art import ArtService
        from control_center import render_music as RM
        art = ArtService(sync=True, cover_store=_RecordingStore())
        full = art.element(_cover(5, 1200), 340, units=340, need0=680, src_need=340)
        small = art.element(_cover(6, 400), 340, units=340, need0=680, src_need=340)
        self.assertEqual(full.getpixel((2, 2)), full.getpixel((170, 170)))          # the flat cover, edge to edge
        ground = RM.radial_ground(340, art.dominant(_cover(6, 400).key))
        for got, want in zip(small.getpixel((2, 2)), ground.getpixel((2, 2))):     # the sleeve's ground
            self.assertLessEqual(abs(got - want), 3)


class ResidencyTests(unittest.TestCase):
    """WP8-R2: §4.5 / §4.9 / §14: bytes, not entries; labels, loading tiles, ambient layers and the
    column text are released at close; card and row surfaces and statics stay."""

    def test_close_releases_everything_but_cards_rows_and_statics(self):
        from control_center.stage.scenes import common as CM
        T = _payloads()
        rig = _rig()
        p = T.explorer_payload(rig.now(), index=0, recent="many")
        rig.presenter.explorer_open(p)
        rig.settle()
        am, _c = T.sim_apple(art="full", recent="many")
        items = [{k: v for k, v in it.items() if not k.startswith("_")} for it in am._library()]
        sc = rig.scene
        peak = 0
        for idx in range(1, 41):
            first = max(0, idx - 12)
            rig.presenter.explorer_highlight({"index": idx, "control_id": 1, "bump": 0, "items": items[first:idx + 17],
                                              "items_first": first, "items_rev": 1})
            rig.settle()
            rig.advance(250, 250)
            self.assertLessEqual(sc.lru.bytes_of(sc.lru.aux), CM.AUX_BYTES)
            peak = max(peak, sc.lru.total_bytes())
            amb = _alive_surfaces(rig.dev).get("ambient", (0, 0))[0]
            self.assertLessEqual(amb, 2)                         # the two layers, never a pile of old builds
        self.assertLessEqual(peak, CM.SCENE_VRAM_BYTES)
        rig.presenter.explorer_close({"t0": rig.now(), "reason": "back", "close_at_ms": 0})
        rig.settle()
        rig.advance(1000, 100)
        self.assertIsNone(rig.engine.scene)
        alive = _alive_surfaces(rig.dev)
        for kind in CM.RELEASE_AT_CLOSE:
            self.assertNotIn(kind, alive, kind)
        total = sum(b for _n, b in alive.values())
        self.assertLessEqual(total, 256 * CM.MB)                  # §14's stage-VRAM guard with nothing open
        self.assertEqual(rig.dev.violations, [])

    def test_up_next_close_releases_its_column_text_and_tiles(self):
        from control_center.stage.scenes import common as CM
        T = _payloads()
        rig = _rig()
        rig.presenter.upnext_open(T.upnext_payload(rig.now(), kind="playlist", now=4))
        rig.settle()
        for idx in range(5, 12):
            rig.presenter.upnext_highlight({"index": idx, "control_id": 1, "bump": 0})
            rig.settle()
            rig.advance(300, 100)
        rig.presenter.upnext_close({"t0": rig.now(), "reason": "back", "close_at_ms": 0})
        rig.settle()
        rig.advance(1000, 100)
        alive = _alive_surfaces(rig.dev)
        for kind in CM.RELEASE_AT_CLOSE:
            self.assertNotIn(kind, alive, kind)
        self.assertIn("row", alive)                              # row surfaces stay (§4.9)
        self.assertEqual(rig.dev.violations, [])

    def test_the_second_lru_is_bounded_by_bytes_and_keeps_its_pins(self):
        from control_center.stage import fake as F
        from control_center.stage.scenes.common import AUX_BYTES, MB, MusicLRU, SCENE_VRAM_BYTES
        from control_center.stage.surfaces import SurfaceLRU
        dev = F.FakeDevice(F.FakeClock())
        covers = SurfaceLRU(dev, capacity=128)
        lru = MusicLRU(covers, dev)
        pinned = ("label", "pinned", 2.0)
        lru.put(pinned, dev.create_surface(1800, 176, False), 1800 * 176 * 4)
        lru.pin({pinned})
        for n in range(120):                                     # 120 x 1.85 MB loading tiles
            lru.put(("load", n, 680), dev.create_surface(680, 680, True), 680 * 680 * 4)
            self.assertLessEqual(lru.bytes_of(lru.aux), AUX_BYTES)
        self.assertIn(pinned, lru)
        self.assertIn(("load", 119, 680), lru)
        for n in range(100):                                     # 100 Up next big covers, 2.31 MB each
            lru.put(("art", f"c{n}", "cover", 760), dev.create_surface(760, 760, True), 760 * 760 * 4)
        self.assertLessEqual(lru.total_bytes(), SCENE_VRAM_BYTES)
        self.assertGreater(lru.total_bytes(), SCENE_VRAM_BYTES - 8 * MB)
        live = sum(o["size"][0] * o["size"][1] * 4 for o in dev.objects.values()
                   if o["kind"] == "surface" and not o["released"])
        self.assertEqual(live, lru.total_bytes())                # evicted means released

    def test_a_replaced_ambient_layer_is_released(self):
        rig, p = ExplorerSceneTests().open(index=4)
        rig.advance(800, 100)
        sc = rig.scene
        for idx in (5, 6, 7, 8):
            rig.presenter.explorer_highlight({"index": idx, "control_id": 1, "bump": 0})
            rig.settle()
            rig.advance(700, 100)                                # every debounce fires and lands
        self.assertGreaterEqual(sc.ambient.gen, 4)
        amb = _alive_surfaces(rig.dev).get("ambient", (0, 0))[0]
        self.assertEqual(amb, 2)
        self.assertEqual(rig.dev.violations, [])


class ExplorerFixTests(unittest.TestCase):
    META = ("count", "mosaic", "art_state", "first_art", "duration_ms")

    def test_data_inside_a_source_switch_is_applied_to_the_entering_set(self):
        """WP8-R5: K3 sends the playlist meta 60 ms into the switch (a new items_rev); only the
        turn waits for +190, the descriptors rebind the entering cards at once."""
        T = _payloads()
        rig, p = ExplorerSceneTests().open(index=3)
        rig.advance(600, 100)
        sc = rig.scene
        full = T.explorer_payload(rig.now(), source="favourites", index=1)
        bare = [{k: v for k, v in it.items() if k not in self.META} for it in full["items"]]
        rig.presenter.explorer_source({"t0": rig.now(), "source": "favourites", "state": "ready", "index": 1,
                                       "count": full["count"], "items": bare, "items_first": full["items_first"],
                                       "items_rev": 10})
        rig.settle()
        rig.advance(60, 20)
        self.assertTrue(sc.swapping(rig.clk.t))
        rig.presenter.explorer_highlight({"index": 1, "control_id": 1, "bump": 0, "items": full["items"],
                                          "items_first": full["items_first"], "items_rev": 11})
        rig.settle()
        new = sc.bound[(sc.set_id, 1)]
        a = _anim(rig.dev, new.box.ref.v3, "opacity")
        self.assertIsNotNone(a)
        rig.advance(1500, 100)
        for i in range(full["count"]):
            c = sc.bound.get((sc.set_id, i))
            self.assertIsNotNone(c)
            self.assertEqual(c.plan, sc.plan_of(i))
            self.assertNotEqual(c.plan.kind, "pending")         # was: stuck on the bare descriptor's plan
            self.assertIsNotNone(c.bound[0])                     # its art, not the loading tile forever
        self.assertEqual(rig.dev.violations, [])

    def test_data_after_a_state_change_inside_its_window(self):
        T = _payloads()
        rig, p = ExplorerSceneTests().open(source="favourites", index=0, state="error")
        rig.advance(500, 100)
        sc = rig.scene
        full = T.explorer_payload(rig.now(), source="favourites", index=0)
        bare = [{k: v for k, v in it.items() if k not in self.META} for it in full["items"]]
        rig.presenter.explorer_highlight({"index": 0, "control_id": 1, "bump": 0, "state": "ready",
                                          "count": full["count"], "items": bare, "items_first": 0, "items_rev": 9})
        rig.settle()
        rig.advance(60, 20)
        rig.presenter.explorer_highlight({"index": 0, "control_id": 1, "bump": 0, "items": full["items"],
                                          "items_first": 0, "items_rev": 10})
        rig.settle()
        rig.advance(1500, 100)
        for i in range(full["count"]):
            c = sc.bound[(sc.set_id, i)]
            self.assertEqual(c.plan, sc.plan_of(i))
            self.assertIsNotNone(c.bound[0])

    def test_a_count_change_inside_the_window_keeps_the_dots_for_190(self):
        from control_center.stage.scenes import common as CM
        T = _payloads()
        rig, p = ExplorerSceneTests().open(index=3)
        rig.advance(600, 100)
        sc = rig.scene
        fav = T.explorer_payload(rig.now(), source="favourites", index=0, favs="many")
        t0 = rig.now()
        rig.presenter.explorer_source({"t0": t0, "source": "favourites", "state": "ready", "index": 0,
                                       "count": fav["count"], "items": fav["items"], "items_first": 0, "items_rev": 3})
        rig.settle()
        rig.advance(50, 50)
        rig.presenter.explorer_highlight({"index": 0, "control_id": 1, "bump": 0, "count": fav["count"] - 1})
        rig.settle()
        self.assertEqual(sc.dots_shown, (fav["count"] - 1, False, False))
        v, xp, _yp, op = sc.dots[sc.dots_front]
        hold, before, after = _step_s(_anim(rig.dev, v.ref.v3, "opacity"))
        self.assertAlmostEqual(hold, 0.190, delta=0.006)             # still swapped in at t0 + 190 (S5-10)
        self.assertEqual((before, after), (0.0, 1.0))
        self.assertEqual(op.value(rig.clk.t), 0.0)
        key = CM.static_key("dots", sc.k, (fav["count"] - 1, False, False))
        rig.land()                                                # S1: the row sprite lands a frame later
        self.assertIs(rig.dev.obj(v.ptr)["props"].get("content"), sc.lru.get(key))
        rig.advance(400, 100)
        self.assertEqual(op.value(rig.clk.t), 1.0)

    def test_a_smaller_count_fades_the_cards_past_it_and_recycles_them(self):
        """WP8-R6: §7.2 / §7.4: no card for an item that does not exist."""
        rig, p = ExplorerSceneTests().open(index=5, recent="many")
        rig.advance(800, 100)
        sc = rig.scene
        rig.presenter.explorer_highlight({"index": 5, "control_id": 1, "bump": 0, "count": 6})
        rig.settle()
        gone = [c for c in sc.bound.values() if c.set == sc.set_id and c.index >= 6]
        self.assertTrue(gone)
        for c in gone:
            a = _anim(rig.dev, c.box.ref.v3, "opacity")
            self.assertEqual(a["end"][1], 0.0)
            self.assertAlmostEqual(_end_s(a), 0.300, places=3)
        self.assertEqual(sc.dots_shown, (6, False, False))
        rig.advance(500, 100)
        rig.presenter.explorer_highlight({"index": 4, "control_id": 1, "bump": 0})
        rig.settle()
        self.assertEqual(sorted(i for (s, i) in sc.bound if s == sc.set_id), list(range(0, 6)))
        t = rig.clk.t
        visible = [c.index for c in sc.bound.values() if c.set == sc.set_id and c.o.value(t + 10 ** 7) > 0]
        self.assertTrue(all(i < 6 for i in visible))
        self.assertEqual(rig.dev.violations, [])

    def test_a_count_that_grows_back_revives_the_fading_cards(self):
        rig, p = ExplorerSceneTests().open(index=5, recent="many")
        rig.advance(800, 100)
        sc = rig.scene
        rig.presenter.explorer_highlight({"index": 5, "control_id": 1, "bump": 0, "count": 6})
        rig.settle()
        rig.advance(100)
        rig.presenter.explorer_highlight({"index": 5, "control_id": 1, "bump": 0, "count": p["count"]})
        rig.settle()
        rig.advance(600, 100)
        t = rig.clk.t
        c = sc.bound[(sc.set_id, 6)]
        self.assertFalse(c.leaving)
        self.assertAlmostEqual(c.o.value(t), SM.explorer_table(True).o[1], places=3)

    def test_the_input_path_creates_no_surface(self):
        """WP8-R10 (§4.5, §4.7.1, G1-5): a block on a switch and a new dot row on a count change
        go through the upload queue and show when they land."""
        from control_center.stage.scenes import common as CM
        CM._STATIC_CPU.clear()
        CM._STATIC_CPU_BYTES[0] = 0
        T = _payloads()
        rig, p = ExplorerSceneTests().open(index=3)
        rig.advance(600, 100)
        sc = rig.scene
        made = _watch_input_creates(rig, sc)
        rig.presenter.explorer_source({"t0": rig.now(), "source": "favourites", "state": "empty", "index": 0,
                                       "count": 0, "items": [], "items_first": 0, "items_rev": 4})
        rig.settle()
        rig.advance(500, 100)
        self.assertEqual(made, [])
        self.assertEqual(sc.block_shown, ("empty", "favourites"))
        v, op = sc.blocks[sc.block_front]
        self.assertEqual(op.value(rig.clk.t), 1.0)
        rig.presenter.explorer_source({"t0": rig.now(), "source": "recent", "state": "ready", "index": 3,
                                       "count": p["count"], "items": p["items"], "items_first": p["items_first"],
                                       "items_rev": 5})
        rig.settle()
        rig.advance(600, 100)
        rig.presenter.explorer_highlight({"index": 3, "control_id": 1, "bump": 0, "count": p["count"] + 1})
        rig.land()                                                # S1: the row sprite lands a frame later
        self.assertEqual(made, [])
        self.assertEqual(sc.dots_shown, (p["count"] + 1, False, False))
        v, xp, _yp, op = sc.dots[sc.dots_front]
        key = CM.static_key("dots", sc.k, (p["count"] + 1, False, False))
        self.assertIs(rig.dev.obj(v.ptr)["props"].get("content"), sc.lru.get(key))
        self.assertGreater(sc.counters["static_async"], 0)
        self.assertEqual(rig.dev.violations, [])


class ExplorerLongListTests(unittest.TestCase):
    def test_a_detent_that_slides_the_dots_window_creates_no_surface(self):
        """WP8-R10: every dot row of the count is resident from the build (S5-9: 82 dots, three
        end-fade rows), so a detent past index 41 only swaps contents."""
        from control_center.stage.scenes import common as CM
        CM._STATIC_CPU.clear()
        CM._STATIC_CPU_BYTES[0] = 0
        T = _payloads()
        rig = _rig()
        items = [{"id": f"a{i}", "kind": "album", "title": f"Album {i}", "artist": "X", "year": 2020,
                  "track_count": 10, "art_template": "", "art_max": 0, "art_bg": 0x333333, "art_ink": 0xFFFFFF}
                 for i in range(200)]
        rig.presenter.explorer_open(T.explorer_payload(rig.now(), index=40, items=items))
        rig.settle()
        rig.advance(600, 100)
        sc = rig.scene
        made = _watch_input_creates(rig, sc)
        for idx in (41, 42, 43, 158, 159):
            first = max(0, idx - 12)
            rig.presenter.explorer_highlight({"index": idx, "control_id": 1, "bump": 0, "items": items[first:idx + 17],
                                              "items_first": first, "items_rev": 1})
            rig.settle()
            rig.advance(100, 50)
        self.assertEqual(made, [])
        self.assertEqual(sc.dots_shown, (82, True, False))
        self.assertEqual(rig.dev.violations, [])


class DetentTrimTests(unittest.TestCase):
    """R-k (the explorer's per-detent COM trim): the batched legs are the builder's own programs,
    a property already showing its value costs no call, the stacking list follows the children,
    and a debounce restart wakes no art worker. The motion itself is the same (the goldens and the
    scene tests above hold)."""

    def _core(self, mode="absolute"):
        from control_center.stage import clock as CK
        from control_center.stage import fake as F
        from control_center.stage.engine import StageCore
        from control_center.stage.tree import Tree
        clk = F.FakeClock()
        dev = F.FakeDevice(clk)
        qpf = dev.time_frequency if mode == "absolute" else dev.time_frequency // 2
        core = StageCore(dev, CK.StageClock(dev.time_frequency, qpf, qpc=clk, perf=clk.perf))
        tree = Tree(dev)
        root = tree.root()
        props = []
        for j in range(4):
            v = tree.visual(f"v{j}", opacity=True)
            tree.add(root, v)
            st = tree.scale_transform(v, 10.0, 10.0)
            props += [tree.offset_x(v, 100.0 * j), tree.opacity(v, 1.0), tree.scale(st, 680.0, 1.0, name=f"s{j}")]
        return clk, dev, core, props

    def _state(self, dev, props, b):
        out = []
        for p in props:
            f = p.func
            twin = (type(f).__name__,) + tuple(getattr(f, k, None) for k in ("begin", "start", "dur", "v0", "v1", "v"))
            anims = []
            for fn, ptr in p.fbind:
                for prop in ("offset_x", "opacity", "scale_x", "scale_y"):
                    a = dev.animation_of(ptr, prop)
                    if a is not None:
                        anims.append((prop, a["begin"], tuple(a["segs"]), a["end"]))
            out.append((twin, getattr(f, "tab", None), tuple(anims)))
        return out, (b.calls, b.anims, b.skipped, b.max_end, b._hr)

    def test_program_legs_is_the_builders_to(self):
        """Same segments, begin, twin, counters and max_end as ``Batch.to`` per leg, from rest,
        from curves in flight (a retarget) and for an equal target (skipped), in both begin modes."""
        from control_center.stage.scenes.common import program_legs
        for mode in ("absolute", "hold"):
            results = []
            for use_legs in (False, True):
                clk, dev, core, props = self._core(mode)
                script = [
                    [(props[0], 420.0, 420), (props[1], 0.5, 300), (props[2], 0.6, 420), (props[3], 250.0, 420)],
                    [(props[0], 90.0, 420), (props[1], 0.92, 300), (props[2], 0.6, 420), (props[4], 0.0, 320),
                     (props[5], 0.42, 420)],
                    [(props[0], 90.0, 420), (props[6], 17.0, 420), (props[7], 0.3, 320), (props[1], 0.0, 300)],
                ]
                snaps = []
                for legs in script:
                    b = core.batch()
                    if use_legs:
                        program_legs(b, legs)
                    else:
                        for prop, target, ms in legs:
                            b.to(prop, target, ms, "OUT")
                    b.commit()
                    snaps.append(self._state(dev, props, b))
                    clk.advance(0.05)
                results.append(snaps)
                self.assertEqual(dev.violations, [])
            self.assertEqual(results[0], results[1], mode)

    def test_set_value_skips_only_a_value_already_shown_for_good(self):
        from control_center.stage.scenes.common import set_value
        clk, dev, core, props = self._core()
        x = props[0]
        b = core.batch()
        b.to(x, 300.0, 100, "OUT")
        b.commit()
        clk.advance(0.05)
        b = core.batch()
        self.assertEqual(set_value(b, x, 300.0), 1)          # still moving at t1: set
        b.commit()
        b = core.batch()
        b.to(x, 500.0, 100, "OUT")
        b.commit()
        clk.advance(0.2)
        b = core.batch()
        self.assertEqual(set_value(b, x, 500.0), 0)          # ended on it: nothing to set
        self.assertEqual(b.calls, 0)
        self.assertEqual(set_value(b, x, 501.0), 1)          # another value: set
        self.assertEqual(set_value(b, x, 501.0), 0)          # a float already there (the builder's own skip)
        b.commit()
        self.assertEqual(dev.violations, [])

    def test_the_stacking_list_follows_the_children_through_spins_counts_and_switches(self):
        T = _payloads()
        rig = _rig()
        full = T.explorer_payload(0.0, recent="many", art="mixed", window=False)["items"]
        rig.presenter.explorer_open(T.explorer_payload(rig.now(), index=40, recent="many", art="mixed"))
        rig.settle()
        rig.advance(600, 100)
        sc = rig.scene

        def check():
            boxes = {c.box for c in sc.bound.values()}
            self.assertEqual([c.box for c in sc._z], [v for v in sc.cards_box.children if v in boxes])
            cur = [c for c in sc._z if c.set == sc.set_id]
            f = sc.focus
            left = [c.index for c in cur if c.index < f]
            right = [c.index for c in cur if c.index > f]
            self.assertEqual(left, sorted(left))
            self.assertEqual(right, sorted(right, reverse=True))
            if any(c.index == f for c in cur):
                self.assertEqual(sc._z[-1].index, f)                 # the focus on top
        idx = 40
        for step in [+1] * 12 + [-1] * 12 + [(+1 if i % 2 == 0 else -1) for i in range(10)]:
            idx += step
            first = max(0, idx - 12)
            rig.presenter.explorer_highlight({"index": idx, "control_id": 1, "bump": 0, "items": full[first:idx + 17],
                                              "items_first": first, "items_rev": 1})
            rig.settle()
            rig.clk.advance(0.05)
            check()
        rig.advance(600, 100)
        check()
        rig.presenter.explorer_highlight({"index": idx, "control_id": 1, "bump": 0, "count": idx + 3})
        rig.settle()
        check()
        rig.advance(500, 100)
        check()
        fav = T.explorer_payload(rig.now(), source="favourites", index=2, favs="many")
        sw = {k: fav[k] for k in ("t0", "source", "state", "index", "count", "items", "items_first")}
        sw.update(items_rev=7, control_id=2)
        rig.presenter.explorer_source(sw)
        rig.settle()
        check()
        rig.advance(800, 100)
        check()
        self.assertEqual(rig.dev.violations, [])

    def test_a_card_entering_the_range_sets_only_what_changed(self):
        """The card recycled at a spin's far end keeps its finished values (opacity 0, scale 0.40,
        shade, the art fade): its placement sets what differs and nothing else (R-k)."""
        from control_center.stage import animation as AN
        T = _payloads()
        rig = _rig()
        full = T.explorer_payload(0.0, recent="many", art="mixed", window=False)["items"]
        rig.presenter.explorer_open(T.explorer_payload(rig.now(), index=40, recent="many", art="mixed"))
        rig.settle()
        rig.advance(600, 100)
        sc = rig.scene
        idx = 40

        def detent(i):
            first = max(0, i - 12)
            rig.presenter.explorer_highlight({"index": i, "control_id": 1, "bump": 0, "items": full[first:i + 17],
                                              "items_first": first, "items_rev": 1})
            rig.settle()
        for _ in range(12):
            idx += 1
            detent(idx)
            rig.clk.advance(0.05)
        rig.advance(1000, 100)                                   # everything at rest
        idx += 1
        detent(idx)                                              # recycles the far left, now at rest
        rig.advance(1000, 100)
        c = sc.free[-1]                                          # the card the next detent binds
        props = (c.x, c.S, c.o, c.sh, c.y, c.e, c.side_o, c.focus_o, c.ready_o, c.l0_o)
        before = {p.name: (p.func.target, p.func.kind) for p in props}
        set_calls = []
        orig = AN.Batch.jump

        def jump(b, prop, value, **kw):
            n = orig(b, prop, value, **kw)
            if n:
                set_calls.append(prop.name)
            return n
        AN.Batch.jump = jump
        try:
            idx += 1
            detent(idx)
        finally:
            AN.Batch.jump = orig
        self.assertIs(sc.bound[(sc.set_id, idx + sc.a_max)], c)
        changed = {p.name for p in props if abs(p.func.target - before[p.name][0]) > 1e-9}
        mine = {n for n in set_calls if n in before}
        self.assertEqual(mine, changed)
        skipped = [n for n in before if n not in changed and before[n][1] != "const"]
        self.assertTrue(skipped, before)                         # finished animations kept, no call
        self.assertEqual(rig.dev.violations, [])

    def test_a_debounce_restart_wakes_no_worker_that_already_waits_for_it(self):
        from control_center.stage.fake import FakeClock
        from control_center.stage.scenes.art import LANE_ART, ArtService, Job
        clk = FakeClock()
        art = ArtService(sync=True, clock=clk.perf)
        woken = []
        orig = art._cond.notify
        art._cond.notify = lambda n=1: (woken.append(n), orig(n))[1]
        now = clk.perf()
        self.assertFalse(art.debounce(Job(("ambient", "o", 1), 0, lambda: None, owner="o", not_before=now + 0.2)))
        self.assertEqual(len(woken), 1)                          # nobody waits yet: wake one
        art._sleepers[1] = (now + 0.2, None)                     # a worker asleep until that deadline
        self.assertTrue(art.debounce(Job(("ambient", "o", 2), 0, lambda: None, owner="o", not_before=now + 0.25),
                                     replace=("ambient", "o", 1)))
        self.assertEqual(len(woken), 1)                          # it wakes first and finds the new job
        self.assertEqual(set(art._jobs), {("ambient", "o", 2)})
        art._sleepers[1] = (now + 0.5, None)                     # asleep past the new deadline: wake one
        art.debounce(Job(("ambient", "o", 3), 0, lambda: None, owner="o", not_before=now + 0.3),
                     replace=("ambient", "o", 2))
        self.assertEqual(len(woken), 2)
        art._sleepers[1] = (now + 0.1, ("fast",))                # only the fast lane: an art-lane job wakes one
        art.debounce(Job(("x", 1), 0, lambda: None, not_before=now + 0.3, lane=LANE_ART))
        self.assertEqual(len(woken), 3)
        art._sleepers.clear()
        ran = []
        art.debounce(Job(("ambient", "o", 4), 0, lambda: ran.append(4), owner="o", not_before=now + 0.3),
                     replace=("ambient", "o", 3))
        clk.advance(0.35)
        art.run_pending()
        self.assertEqual(ran, [4])                               # newest wins, on time

    def test_the_bench_reads_the_gate_over_several_runs(self):
        from control_center.stage.scenes.bench import runs_summary

        def res(p95, p50=1.0, build=None, commit=None, spikes=None):
            r = {"wake_to_commit_ms": {"p95": p95, "p50": p50}, "gate_1_5ms_p95": p95 <= 1.5,
                 "calls_per_detent": {"p50": 494.0}, "anims_per_detent": {"p50": 63.0}}
            if build is not None:
                r.update(build_ms={"p95": build}, commit_ms={"p95": commit}, commits_over_0_25ms=spikes)
            return r
        s = runs_summary([res(1.4), res(1.6), res(1.2), res(1.45), res(1.5)])
        self.assertEqual(s["runs"], 5)
        self.assertEqual(s["median_p95_ms"], 1.45)
        self.assertEqual(s["worst_p95_ms"], 1.6)
        self.assertEqual(s["runs_at_or_under_1_5ms"], 4)
        self.assertEqual(s["calls_per_detent_p50"], [494.0] * 5)
        self.assertEqual(s["build_p95_ms"], [None] * 5)                  # older results: no split

    def test_the_bench_median_of_an_even_run_count_is_the_mean_of_the_middle_two(self):
        """WP8T-2: 4 or 6 runs read the true median (``statistics.median``), not the upper middle
        value, which overstated the gate number at the margin."""
        from control_center.stage.scenes.bench import runs_summary

        def res(p95, build=1.1, commit=0.5, spikes=11):
            return {"wake_to_commit_ms": {"p95": p95, "p50": 1.0}, "gate_1_5ms_p95": p95 <= 1.5,
                    "build_ms": {"p95": build}, "commit_ms": {"p95": commit}, "commits_over_0_25ms": spikes,
                    "calls_per_detent": {"p50": 494.0}, "anims_per_detent": {"p50": 63.0}}
        s = runs_summary([res(1.55), res(1.40), res(1.52), res(1.45)])
        self.assertEqual(s["median_p95_ms"], 1.485)                      # the upper middle (1.52) failed it
        self.assertLessEqual(s["median_p95_ms"], 1.5)
        self.assertEqual(s["worst_p95_ms"], 1.55)
        self.assertEqual(s["runs_at_or_under_1_5ms"], 2)
        s6 = runs_summary([res(x) for x in (1.369, 1.38, 2.014, 1.968, 1.934, 1.692)])
        self.assertEqual(s6["median_p95_ms"], 1.813)                     # bench_runs6.json: was 1.934
        self.assertEqual(s6["build_p95_ms"], [1.1] * 6)                  # the build and Commit apart (R-k)
        self.assertEqual(s6["commit_p95_ms"], [0.5] * 6)
        self.assertEqual(s6["commits_over_0_25ms"], [11] * 6)
        self.assertEqual(runs_summary([res(1.3)])["median_p95_ms"], 1.3)

    def test_the_scene_tools_run_by_path_under_isolated_mode(self):
        """WP8T-4: the documented commands (``python -I <path>``) work from any folder: under -I
        neither the working directory nor the script's folder is on sys.path, so each tool puts
        the project root there itself and runs as part of its package (``--help`` only: nothing
        is measured, created or shown)."""
        import os
        import subprocess
        scenes = ROOT / "control_center" / "stage" / "scenes"
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
        for name in ("bench.py", "selftest.py", "gilbench.py"):
            text = (scenes / name).read_text(encoding="utf-8")
            self.assertNotIn("python -I -m control_center", text, name)  # the -m form cannot work under -I
            self.assertIn(f"-I control_center\\\\stage\\\\scenes\\\\{name}", text, name)
            p = subprocess.run([sys.executable, "-I", str(scenes / name), "--help"], cwd=str(ROOT / "tests"),
                               env=env, capture_output=True, text=True, errors="replace", timeout=120)
            self.assertEqual(p.returncode, 0, (name, p.stderr[-800:]))
            self.assertIn("usage:", p.stdout, name)
        p = subprocess.run([sys.executable, "-I", str(scenes / "bench.py"), "--help"], cwd=str(ROOT / "tests"),
                           env=env, capture_output=True, text=True, errors="replace", timeout=120)
        self.assertIn("--runs", p.stdout)

    def test_a_threaded_debounce_still_runs_on_time(self):
        """Real workers: five restarts 10 ms apart; only the newest runs, at its deadline."""
        import threading
        import time
        from control_center.stage.scenes.art import ArtService, Job
        art = ArtService(workers=1)
        try:
            ran = []
            done = threading.Event()
            key = None
            for n in range(5):
                job = Job(("ambient", "o", n), 0, lambda n=n: (ran.append((n, time.perf_counter())), done.set()),
                          owner="o", not_before=time.perf_counter() + 0.06)
                art.debounce(job, replace=key)
                key = job.key
                last_due = job.not_before
                time.sleep(0.01)
            self.assertTrue(done.wait(2.0))
            time.sleep(0.05)
            self.assertEqual([n for n, _t in ran], [4])
            self.assertGreaterEqual(ran[0][1], last_due - 0.002)
        finally:
            art.close(1.0)


def _music_tours():
    """``tools\\stage_checks\\music_tours.py`` (the S1 tours), loaded by path; None when the work
    folder is not next to the project."""
    import importlib.util
    path = ROOT.parent / "tools" / "stage_checks" / "music_tours.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("music_tours_under_test", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MusicToursProbeTests(unittest.TestCase):
    """The S1 tours' per-detent probe (R-k's on-screen judgement): a detent keeps the phase it was
    posted in when the stage thread picks it up after the driver has moved on (WP8T-3), and the
    pickup verdict carries its rule and the rule's status, accepted with WP8-D10 (lead, 2026-09-26;
    WP8T-1), R-k open until the tours pass on screen. The fake rig only: nothing is shown."""

    @classmethod
    def setUpClass(cls):
        cls.mt = _music_tours()
        if cls.mt is None:
            raise unittest.SkipTest("tools\\stage_checks\\music_tours.py is not next to the project")

    @staticmethod
    def _event(t1=1000):
        from types import SimpleNamespace as NS
        clock = NS(freq=10_000_000, from_perf=lambda s: int(s * 10_000_000))
        core = NS(clock=clock, surface="explorer", period=41_667.0)
        batch = NS(t_done=0.0001, t1=t1, work_ms=1.1, commit_ms=0.05, calls=494, anims=63)
        return core, batch

    def test_a_tour_whose_calls_are_picked_up_late_keeps_every_detent_in_its_phase(self):
        from control_center.stage.scenes import ExplorerScene, UpNextScene
        own = {c: (c.__dict__.get("update"), c.__dict__.get("position")) for c in (ExplorerScene, UpNextScene)}
        ok, split = self.mt.phase_self_check()
        self.assertEqual(split, {"10/s": 20, "20/s": 20, "rev20": 10, "after_switch": 10})   # none in the pause
        self.assertTrue(ok)
        self.assertEqual({c: (c.__dict__.get("update"), c.__dict__.get("position")) for c in own}, own)

    def test_the_probe_joins_a_turn_to_the_newest_post_of_its_call_and_index(self):
        probe = self.mt.DetentProbe()
        core, batch = self._event()
        probe.tour, probe.phase = 3, "10/s"
        probe.posted("explorer_highlight", {"index": 50, "control_id": 1}, "10/s")
        probe.phase = "pause"                                       # the driver moved on before the stage ran
        probe._applying = ("explorer_highlight", 50)                # the stage applies the 10/s detent now
        probe.note(core, batch, "turn")
        probe.posted("explorer_highlight", {"index": 51}, "20/s")
        probe.posted("explorer_highlight", {"index": 52}, "20/s")   # coalesced with 51 in the mailbox
        probe.phase = "rev20"
        probe._applying = ("explorer_highlight", 52)
        probe.note(core, batch, "turn")
        probe.posted("explorer_highlight", {"index": 51}, "rev20")  # an index seen before, in another phase
        probe._applying = ("explorer_highlight", 51)
        probe.note(core, batch, "turn")
        probe._applying = ("position", 9)                           # nothing posted for it: the marked phase
        probe.note(core, batch, "turn")
        probe.phase = "switch"
        probe._applying = ("explorer_source", None)
        probe.note(core, batch, "switch")                           # not a detent: the marked phase
        self.assertEqual([(r["tour"], r["phase"], r["kind"]) for r in probe.rows],
                         [(3, "10/s", "turn"), (3, "20/s", "turn"), (3, "rev20", "turn"), (3, "rev20", "turn"),
                          (3, "switch", "switch")])
        self.assertIsNone(probe._applying)                          # one event, one join

    def test_the_pickup_verdict_carries_its_rule_and_the_rules_status(self):
        mt = self.mt
        ok, ks = mt.report_self_check()
        self.assertTrue(ok, ks)
        empty = mt.detent_report([], [])
        rule = empty["pickup_rule"]
        self.assertEqual((rule["on_time_min"], rule["early_max"]), (0.98, 0))
        self.assertIn("accepted", rule["status"])                   # WP8-D10 is ruled (lead, 2026-09-26)
        self.assertIn("R-k stays open", rule["status"])             # until tours E and U pass on screen
        self.assertIn("WP8-D10", rule["status"])
        from control_center.stage.frames import TargetFrame
        P = 10_000_000 / 240.0
        frames = [TargetFrame(i, int(1e6 + i * P + P), int(1e6 + i * P + P), i, i, start_time=int(1e6 + i * P - P / 2),
                          target_time=int(1e6 + i * P)) for i in range(40)]
        rows = [{"tour": 0, "phase": "20/s", "surface": "explorer", "kind": "turn", "period": P, "freq": 10_000_000,
                 "work_ms": 1.0, "commit_ms": c, "calls": 490, "anims": 63, "t1": frames[i].target_time,
                 "done": int(frames[i].target_time - 0.6 * P)} for i, c in ((5, 0.05), (10, 0.45), (15, 0.06))]
        rep = mt.detent_report(rows, frames)
        self.assertIs(rep["pickup_pass"], True)
        self.assertEqual(rep["pickup_rule"], rule)
        self.assertEqual(rep["commit_ms"]["max"], 0.45)             # the Commit apart from the build
        self.assertEqual(rep["by_phase"]["20/s"]["commit_ms"]["p50"], 0.06)


def _watch_input_creates(rig, sc):
    """Record every surface created, and every upload posted (``UploadQueue.put`` wakes the stage
    with ``SetEvent``, a GIL-releasing call), while the scene handles an input (update / position)."""
    made = []
    flag = {"on": False}
    dev = rig.dev
    orig_cs = dev.create_surface

    def create_surface(*a, **k):
        if flag["on"]:
            made.append(a)
        return orig_cs(*a, **k)
    dev.create_surface = create_surface
    uploads = rig.engine.uploads
    orig_put = uploads.put

    def put(key, *a, **k):
        if flag["on"]:
            made.append(("put", key))
        return orig_put(key, *a, **k)
    uploads.put = put
    for name in ("update", "position"):
        orig = getattr(sc, name)

        def wrapped(*a, _orig=orig, **k):
            flag["on"] = True
            try:
                return _orig(*a, **k)
            finally:
                flag["on"] = False
        setattr(sc, name, wrapped)
    return made


class UpNextFixTests(unittest.TestCase):
    def open(self, **kw):
        return UpNextSceneTests().open(**kw)

    def test_a_cold_album_open_moves_the_ambient_to_the_cover(self):
        """WP8-R4: §12 uses art_bg only while nothing is cached; §8.4 the ambient follows the cover."""
        rig, p = self.open(kind="album", now=4)
        sc = rig.scene
        plan = sc.cover_plan()
        self.assertIsInstance(sc.ambient.first_src, int)          # t = 0: nothing cached, the art_bg layer
        rig.advance(1500, 100)
        self.assertIsNotNone(rig.art.thumb(plan.key))
        self.assertGreaterEqual(sc.ambient.gen, 1)
        key = sc.ambient.layers[sc.ambient.front][2]
        self.assertEqual(key[:2], ("ambient", sc.owner))
        self.assertEqual(sc.ambient.shown, plan.key)
        v, op, _k = sc.ambient.layers[sc.ambient.front]
        self.assertAlmostEqual(op.value(rig.clk.t), 0.45)

    def test_a_warm_reopen_does_not_rebuild_the_ambient(self):
        rig, p = self.open(kind="album", now=4)
        rig.advance(1500, 100)
        rig.presenter.upnext_close({"t0": rig.now(), "reason": "back", "close_at_ms": 0})
        rig.settle()
        rig.advance(800, 100)
        T = _payloads()
        rig.presenter.upnext_open(T.upnext_payload(rig.now(), kind="album", now=4))
        rig.settle()
        sc = rig.scene
        self.assertIs(sc.ambient.first_src, rig.art.thumb(sc.cover_plan().key))
        rig.advance(800, 100)
        self.assertEqual(sc.ambient.gen, 0)

    def test_rows_past_a_smaller_count_fade_out_and_are_recycled(self):
        """WP8-R6: a queue_changed with count 6 (K3 §5.6.8)."""
        rig, p = self.open(kind="album", now=4, rows=24)
        rig.advance(800, 100)
        sc = rig.scene
        rows = [r for r in p["rows"] if r["row"] <= 6]
        for reason in ("queue_changed",):
            rig.presenter.upnext_rows({"t0": rig.now(), "reason": reason, "rows": rows, "now": 4, "focus": 4,
                                       "count": 6, "card": None, "shuffle": "off", "likes_known": True})
            rig.settle()
        self.assertNotIn((sc.set_id, 8), sc.bound)              # a = 4 was invisible: recycled at once
        for i in (6, 7):
            r = sc.bound.get((sc.set_id, i))
            self.assertIsNotNone(r)
            self.assertTrue(r.leaving)
            a = _anim(rig.dev, r.box.ref.v3, "opacity")
            self.assertEqual(a["end"][1], 0.0)
            self.assertAlmostEqual(_end_s(a), 0.300, places=3)
        rig.advance(600, 100)
        rig.presenter.upnext_highlight({"index": 3, "control_id": 1, "bump": 0})
        rig.settle()
        self.assertEqual(sorted(i for (s, i) in sc.bound if s == sc.set_id), list(range(0, 6)))
        self.assertEqual(rig.dev.violations, [])

    def test_a_count_below_the_focus_moves_the_focus(self):
        rig, p = self.open(kind="playlist", now=4, rows=24, focus=10)
        rig.advance(800, 100)
        sc = rig.scene
        rows = [r for r in p["rows"] if r["row"] <= 6]
        rig.presenter.upnext_rows({"t0": rig.now(), "reason": "data", "rows": rows, "now": 4, "focus": 10,
                                   "count": 6, "card": None, "shuffle": "off", "likes_known": True})
        rig.settle()
        self.assertEqual(sc.focus, 5)
        rig.advance(600, 100)
        t = rig.clk.t
        self.assertTrue(all(r.index < 6 for r in sc.bound.values() if r.set == sc.set_id and r.o.value(t) > 0))

    def test_the_shuffle_line_follows_a_queue_changed_patch(self):
        """WP8-R7: a failed shuffle is followed by queue_changed with the true order (K3 §5.6.5)."""
        rig, p = self.open(kind="playlist", now=4)
        rig.advance(800, 100)
        sc = rig.scene
        rows = [dict(r, row=j + 1) for j, r in enumerate(p["rows"][:5] + list(reversed(p["rows"][5:])))]
        rig.presenter.upnext_rows({"t0": rig.now(), "reason": "shuffle", "rows": rows, "now": 4, "focus": 5,
                                   "count": p["count"], "card": None, "shuffle": "companion", "likes_known": True})
        rig.settle()
        rig.advance(600, 100)
        self.assertEqual(sc.shuffle_shown, ("Shuffle on", True))
        rig.presenter.upnext_rows({"t0": rig.now(), "reason": "queue_changed", "rows": p["rows"], "now": 4, "focus": 5,
                                   "count": p["count"], "card": None, "shuffle": "off", "likes_known": True})
        rig.settle()
        self.assertEqual(sc.shuffle_shown, ("In order", False))
        self.assertEqual(sc.hints_shown, (False, False))
        v, op = sc.shuffles[sc.shuffle_front]
        a = _anim(rig.dev, v.ref.v3, "opacity")
        self.assertAlmostEqual(_end_s(a), 0.240, places=3)
        rig.presenter.upnext_rows({"t0": rig.now(), "reason": "data", "rows": p["rows"], "now": 4, "focus": 5,
                                   "count": p["count"], "card": None, "shuffle": "sonos", "likes_known": True})
        rig.settle()
        rig.advance(400, 100)
        self.assertEqual(sc.shuffle_shown, SM.shuffle_line("sonos"))

    def test_the_real_cover_fades_in_over_its_loading_tile_in_240(self):
        """WP8-R8: §7.6 "Art ready", §13.6 art.loading: 240 ms OUT, no 420 ms crossfade, no dip."""
        rig, p = self.open(kind="playlist", now=4)
        rig.land()                                                # S1: the cover lands a frame after its upload
        sc = rig.scene
        self.assertEqual(sc.cover_key[0], "art")
        ends = []
        for v, op, key in sc.covers:
            a = _anim(rig.dev, v.ref.v3, "opacity")
            if a is not None and a.get("end"):
                ends.append((round(_end_s(a), 3), a["end"][1], key[0] if key else None))
        self.assertTrue(ends)
        self.assertNotIn(0.420, [e[0] for e in ends])
        self.assertIn(0.240, [e[0] for e in ends])
        rig.advance(300, 100)
        t = rig.clk.t
        front = sc.covers[sc.cover_front]
        self.assertEqual(front[1].value(t), 1.0)
        self.assertEqual(front[2][0], "art")

    def test_art_ready_above_the_tile_fades_the_cover_and_then_hides_the_tile(self):
        rig, p = self.open(kind="playlist", now=4)
        rig.advance(600, 100)
        sc = rig.scene
        s = sc.surface_for(sc.cover_key)
        sc.cover_front = 0
        batch = rig.engine.core.batch()
        sc._cover_ready(batch, s, sc.cover_key)
        batch.commit()
        up = _anim(rig.dev, sc.covers[1][0].ref.v3, "opacity")
        self.assertAlmostEqual(_end_s(up), 0.240, places=3)
        self.assertEqual(up["end"][1], 1.0)
        hold, before, after = _step_s(_anim(rig.dev, sc.covers[0][0].ref.v3, "opacity"))
        self.assertAlmostEqual(hold, 0.240, places=3)                      # hidden once the cover is opaque
        self.assertEqual((before, after), (1.0, 0.0))

    def test_art_and_placeholder_leads_carry_the_inset_line(self):
        """WP8-R9: §8.2 "inset 1 px at 0.12"; BS:246 ``showArt = ph || own``."""
        rig, p = self.open(kind="playlist", now=4)
        sc = rig.scene
        frame = sc.static("row.lead.frame", None)
        for r in sc.bound.values():
            self.assertEqual(r.spec[1], "art")
            self.assertTrue(r.frame_on)
            self.assertIs(rig.dev.obj(r.frame.ptr)["props"].get("content"), frame)
        rig2, p2 = self.open(kind="album", now=4)
        for r in rig2.scene.bound.values():
            self.assertEqual(r.spec[1], "number")
            self.assertFalse(r.frame_on)
        rig3, p3 = self.open(kind="playlist", now=4, loaded=False)
        sc3 = rig3.scene
        ph = sc3.bound[(sc3.set_id, 6)]
        self.assertEqual(ph.spec[1], "placeholder")
        self.assertTrue(ph.frame_on)
        self.assertIs(rig3.dev.obj(ph.frame.ptr)["props"].get("content"), sc3.static("row.lead.frame", None))

    def test_the_first_liked_row_swaps_the_hints_without_a_surface_on_the_detent(self):
        """WP8-R10: the hint variant is resident or goes through the upload queue."""
        from control_center.stage.scenes import common as CM
        CM._STATIC_CPU.clear()
        CM._STATIC_CPU_BYTES[0] = 0
        rig, p = self.open(kind="album", now=4, liked=(5,))
        rig.advance(600, 100)
        sc = rig.scene
        made = _watch_input_creates(rig, sc)
        rig.presenter.upnext_highlight({"index": 5, "control_id": 1, "bump": 0})
        rig.land()                                                # S1: the variant lands a frame later
        self.assertEqual(made, [])
        self.assertEqual(sc.hints_shown, (False, True))
        rig.presenter.upnext_highlight({"index": 6, "control_id": 1, "bump": 0})
        rig.settle()
        self.assertEqual(sc.hints_shown, (False, False))
        self.assertEqual(made, [])
        self.assertEqual(rig.dev.violations, [])


# =========================================================================== the art service
class ArtServiceTests(unittest.TestCase):
    def service(self):
        from control_center.stage.fake import FakeClock
        from control_center.stage.scenes.art import ArtService
        clk = FakeClock()
        return ArtService(sync=True, clock=clk.perf), clk

    def test_plans_are_newest_wins_and_added_jobs_survive_them(self):
        from control_center.stage.scenes.art import Job
        art, clk = self.service()
        ran = []
        art.add(Job(("tick", 1), 0, lambda: ran.append("tick"), owner="o", not_before=clk.perf() + 0.1))
        art.plan("o", lambda svc, snap: [Job(("a", i), (2, i), lambda i=i: ran.append(i)) for i in snap], [1, 2, 3])
        art.plan("o", lambda svc, snap: [Job(("a", i), (2, i), lambda i=i: ran.append(i)) for i in snap], [3, 4])
        art.run_pending()
        self.assertEqual(ran, [3, 4])
        clk.advance(0.2)
        art.run_pending()
        self.assertEqual(ran, [3, 4, "tick"])

    def test_cancel_and_forget(self):
        from control_center.stage.scenes.art import Job
        art, clk = self.service()
        ran = []
        art.add(Job("x", 0, lambda: ran.append("x"), owner="o"))
        art.add(Job("y", 0, lambda: ran.append("y"), owner="o"))
        self.assertTrue(art.cancel("x"))
        art.forget("o")
        art.run_pending()
        self.assertEqual(ran, [])

    def test_elements_and_the_c2_cache(self):
        art, clk = self.service()
        plan = SM.cover_plan({"title": "Heligoland", "art_template": "simulation://art/a2/{w}x{h}bb.jpg",
                              "art_max": 1200, "art_bg": 0xFF781E, "art_ink": 0xF2F2F2})
        img = art.element(plan, 680, units=340, need0=680)
        self.assertEqual(img.size, (680, 680))
        again = art.element(plan, 680, units=340, need0=680)
        self.assertEqual(art.stats["c2_hits"], 1)
        self.assertEqual(again.size, (680, 680))
        self.assertIsNotNone(art.thumb(plan.key))
        small = SM.cover_plan({"title": "Heligoland", "art_template": "simulation://art/a3/{w}x{h}bb.jpg",
                               "art_max": 400, "art_bg": 0xFF781E})
        ext = art.element(small, 680, units=340, need0=680)
        plain = art.simulated.draw("simulation://art/a3/{w}x{h}bb.jpg", 1200, 400, {"art_bg": 0xFF781E})
        self.assertEqual(plain.size, (400, 400))                 # the source is 400 px: u = 1.7 > 1.5
        band = ext.getpixel((12, 340))                           # inside the 6 % inset: the radial ground
        cover = ext.getpixel((60, 340))
        self.assertNotEqual(band, cover)
        from control_center import render_music as RM
        ground = RM.radial_ground(680, art.dominant(small.key))
        for got, want in zip(ext.getpixel((5, 5)), ground.getpixel((5, 5))):
            self.assertLessEqual(abs(got - want), 3)               # the ground (the shadow's far tail only)

    def test_never_and_generated(self):
        art, clk = self.service()
        self.assertIsNone(art.element(SM.cover_plan({"title": "x", "art_template": "simulation://loading/q/{w}x{h}bb.jpg"}),
                                      340, units=340, need0=680))
        gen = art.element(SM.cover_plan({"title": "Hounds of Love", "artist": "Kate Bush"}), 340, units=340, need0=680)
        self.assertEqual(gen.size, (340, 340))

    def test_real_templates_without_a_cover_store_never_fetch(self):
        from control_center.stage.scenes.art import Never
        art, clk = self.service()
        plan = SM.cover_plan({"title": "x", "art_template": "https://is1.mzstatic.com/a/{w}x{h}bb.jpg", "art_max": 1200})
        with self.assertRaises(Never):
            art.element(plan, 340, units=340, need0=680)


# =========================================================================== the runtime adapter
class _Presenter:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail
        self.events = [("opened", {"surface": "explorer", "t0": 1.0})]

    def __getattr__(self, name):
        if name.startswith(("explorer_", "upnext_")):
            def call(payload):
                if self.fail == name:
                    raise ValueError("bad payload")
                self.calls.append((name, payload))
                return True
            return call
        raise AttributeError(name)

    def take_events(self):
        out, self.events = self.events, []
        return out

    def position(self, cid, p, t):
        self.calls.append(("position", (cid, p, t)))
        return True

    def note_touch(self):
        self.calls.append(("touch", None))

    def set_capture_exclusions(self, hwnds):
        self.calls.append(("exclude", hwnds))

    def metrics(self):
        return {"state": "idle"}

    def close(self, timeout):
        return True


class AdapterTests(unittest.TestCase):
    def test_post_strips_the_runtime_fields(self):
        from control_center.music_overlay import MusicOverlay
        pr = _Presenter()
        mo = MusicOverlay(pr)
        eff = {"kind": "explorer_highlight", "request": 7, "view_id": 3, "control_id": 5, "index": 2, "bump": 0}
        self.assertTrue(mo.post(eff))
        self.assertEqual(pr.calls, [("explorer_highlight", {"control_id": 5, "index": 2, "bump": 0})])
        self.assertFalse(mo.post({"kind": "windows_open"}))
        self.assertEqual(mo.take_events(), [("opened", {"surface": "explorer", "t0": 1.0})])

    def test_no_presenter_or_a_failure_refuses_the_open(self):
        from control_center.music_overlay import MusicOverlay
        mo = MusicOverlay(None)
        self.assertFalse(mo.post({"kind": "upnext_open", "request": 1, "view_id": 1}))
        ev = mo.take_events()
        self.assertEqual(ev[0][0], "refused")
        self.assertEqual({k: v for k, v in ev[0][1].items() if k != "t0"}, {"surface": "upnext", "reason": "device"})
        mo = MusicOverlay(_Presenter(fail="explorer_open"))
        self.assertFalse(mo.explorer_open({"t0": 0}))
        self.assertEqual(mo.take_events()[0][1]["reason"], "device")

    def test_pass_throughs(self):
        from control_center.music_overlay import MusicOverlay
        pr = _Presenter()
        mo = MusicOverlay(pr)
        mo.position(3, 4, 1.5)
        mo.note_touch()
        mo.set_capture_exclusions([1, 2])
        self.assertEqual([c[0] for c in pr.calls], ["position", "touch", "exclude"])
        self.assertEqual(mo.metrics()["stage"], {"state": "idle"})

    def test_the_runtime_path_opens_the_scene(self):
        """K3 §11.1 effect -> MusicOverlay.post -> StagePresenter (validated) -> the stage."""
        from control_center.music_overlay import MusicOverlay
        T = _payloads()
        rig = _rig("16:9")
        mo = MusicOverlay(rig.presenter)
        eff = dict(T.explorer_payload(rig.now(), index=1), kind="explorer_open", request=1, view_id=1)
        self.assertTrue(mo.post(eff))
        rig.settle()
        self.assertEqual([k for k, _p in mo.take_events()], ["opened"])


# =========================================================================== static rules
SCENES = ROOT / "control_center" / "stage" / "scenes"
FRAME_MODULES = ("explorer.py", "upnext.py", "common.py", "__init__.py")


class StaticTests(unittest.TestCase):
    def _code_lines(self, path):
        from control_center.stage.selftest import _strip_strings_and_comments
        in_doc = False
        for ln, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if raw.count('"""') % 2 == 1:
                in_doc = not in_doc
                continue
            if not in_doc:
                yield ln, _strip_strings_and_comments(raw)

    def test_no_timers_in_the_scene_frame_paths(self):
        """H2 / P9 for the scene modules: no after(, SetTimer( or sleep( (the debounces run on
        the art workers)."""
        for name in FRAME_MODULES:
            for ln, code in self._code_lines(SCENES / name):
                for pat in (r"\.after" + r"\(", r"\bSetTim" + r"er\(", r"\bsle" + r"ep\("):
                    self.assertIsNone(re.search(pat, code), f"{name}:{ln}")

    def test_no_forbidden_modes_or_focus_calls(self):
        for p in list(SCENES.glob("*.py")) + [ROOT / "control_center" / n for n in
                                               ("scene_music.py", "render_music.py", "music_overlay.py")]:
            for ln, code in self._code_lines(p):
                for bad in ("NEAREST" + "_NEIGHBOR", "BORDER_MODE" + "_HARD", "SetFore" + "groundWindow",
                            "SW_" + "SHOW", "import " + "tkinter", "import " + "serial"):
                    self.assertNotIn(bad, code, f"{p.name}:{ln}")

    def test_module_dependencies(self):
        """scene_music is pure (no PIL, no stage); render_music, music_overlay and scene_music do not
        import the stage. Outside the stage package only WP10's wiring point (``standalone.py``,
        K4 §4.1: ``start_music_stage``) may import it (WP8-R11; WP7a's own scan is WP7a's)."""
        def imports(path):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            out = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    out.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    out.add(("." * node.level) + (node.module or ""))
            return out
        cc = ROOT / "control_center"
        pure = imports(cc / "scene_music.py")
        self.assertFalse({m for m in pure if m.startswith(("PIL", ".stage", "tkinter"))})
        for name in ("render_music.py", "music_overlay.py", "scene_music.py"):
            text = (cc / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"(control_center\.stage|from \.stage|from \. import stage)", text), name)
        from control_center.stage import selftest
        from control_center.stage.scenes.selftest import WIRING_POINTS
        outside = selftest.static_scan()["outside_importers"]
        self.assertEqual(sorted(set(outside) - set(WIRING_POINTS)), [])
        for name in ("render_music.py", "music_overlay.py", "scene_music.py"):
            self.assertNotIn(name, outside)

    def test_scenes_implement_the_presenter_protocol(self):
        from control_center.stage.presenter import Scene
        from control_center.stage.scenes import ExplorerScene, UpNextScene
        for cls in (ExplorerScene, UpNextScene):
            for name in ("build", "open", "update", "position", "close", "hit_rect", "swapping", "release",
                         "uploads_ready", "ambient_source"):
                self.assertTrue(callable(getattr(cls, name, None)), (cls.__name__, name))
                if name != "uploads_ready":
                    self.assertIsNot(getattr(cls, name), getattr(Scene, name, None), (cls.__name__, name))


if __name__ == "__main__":
    unittest.main()
