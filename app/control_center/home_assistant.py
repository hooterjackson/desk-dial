"""Home Assistant bridge for the Lights space (Desk Dial r3, release 1; r3 README section 7; r3.1 area bridge).

One ``HomeAssistantAdapter`` per configured Home Assistant. It drives **every light in one Home
Assistant area** (``ha_area``, e.g. a "Living room"), including lights added to or moved into that area
later, as one aggregate light; a single ``ha_light_entity`` (the release-1 setup) still works when no
area is chosen. It is shaped like ``SonosAdapter``:

* ``read_state()`` never raises: ``online`` False plus a ``reason`` (``not_configured``,
  ``connecting``, ``offline``, ``auth``, ``forbidden`` (HTTP 403: an IP ban), ``unavailable``; ``detail`` says why an area is unavailable:
  ``area_missing``, ``no_lights``, ``no_state``, ``lights_unavailable``, ``registry``) whenever the
  lights cannot be driven. The area's lights are aggregated: ``on`` = any on, ``bri`` = the average of
  the lights that are on, ``kelvin`` = the average of the on lights with a colour temperature,
  ``min_k``/``max_k`` = the range they share (their union when they share none), ``count``.
* A background reader thread holds one WebSocket (``/api/websocket``): ``auth`` with the long-lived
  token; in area mode the area / entity / device registries (``config/*_registry/list``) resolve the
  area's lights (the entity's own area, else its device's area; disabled, hidden, ``entity_category``
  entities and light groups are skipped); ``get_states``; ``subscribe_events`` for ``state_changed``
  and the three ``*_registry_updated`` events (a debounced re-resolve: a light added to the area
  appears with no restart). Every reply is checked. It pings every ``PING_SECONDS``, reconnects
  with a backoff (a fresh socket every time, the old one is never reused; after a rejected token
  60 s doubling up to 1 h) and falls back to REST
  while the WebSocket is down or ``websocket-client`` is missing (the area through
  ``POST /api/template`` ``area_entities`` at most every REGISTRY_POLL_SECONDS, the states through one
  ``GET /api/states``; a small single-light setup reads ``/api/states/<id>``; the poll stretches from
  2 s to 10 s after repeated WebSocket failures).
* Every frame id is allocated and sent under one lock (Home Assistant requires increasing ids).
* Every write goes through ``_guard`` (the allowlist, the idea of ``AppleMusicClient._check_write``):
  only ``light.turn_on`` / ``light.turn_off`` targeted at the configured area (``{"area_id": …}``)
  or light, ``scene.create`` of Desk Dial's own snapshot over exactly the resolved lights,
  ``scene.turn_on`` of that snapshot or of a listed scene, ``script.turn_on`` and
  ``automation.trigger`` of listed ids. The list is the manual ``ha_scenes`` (order and labels) then
  the scenes / scripts / automations assigned to the area and the scenes touching its lights.
  Anything else is refused before any I/O (``HomeAssistantError`` outcome ``not_allowed``).
* Brightness / temperature writes are spaced at least ``WRITE_INTERVAL`` apart (<= 10 Hz); the
  controller coalesces turns and always sends the final value (the volume pattern).

The token comes only from ``CredentialStore`` (key ``ha_token``) and is never logged, never put in a
URL and never returned by ``read_state``. State changes are handed to ``set_listener``'s callback (the
runtime posts them into its results queue); the callback runs on the reader thread.
"""
from __future__ import annotations

import ipaddress
import itertools
import json
import logging
import math
import random
import threading
import time
from urllib.parse import quote, urlsplit, urlunsplit

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())

CREDENTIAL_KEY = "ha_token"
MIN_KELVIN, MAX_KELVIN = 2200, 6500
KELVIN_STEP = 100
WRITE_INTERVAL = 0.25                # <= 4 Hz brightness / temperature writes (each one fades, below)
LIGHT_TRANSITION = 0.4               # s: every knob write fades (HA `transition`), so the ~4 Hz writes overlap
                                     # into one glide while the knob keeps its detents (user, 2026-09-29).
                                     # HA drops it for a light without the TRANSITION feature.
CALL_TIMEOUT = 6.0                   # one call_service result
CONNECT_TIMEOUT = 5.0
RECV_TIMEOUT = 1.0                   # the reader's recv slice (ping and close checks between)
PING_SECONDS = 20.0
PONG_TIMEOUT = 10.0
REST_POLL_SECONDS = 2.0
REST_POLL_STRETCH = 5                # the REST poll after REST_STRETCH_AFTER failed WebSocket attempts: 2 s -> 10 s
REST_STRETCH_AFTER = 3
REST_EACH_MAX = 3                    # single-light setup: up to this many entities are read one by one;
                                     # more (and area mode) read every state with ONE GET /api/states
BACKOFF = (1.0, 2.0, 5.0, 10.0, 30.0)
BACKOFF_JITTER = 0.2                 # each WebSocket back-off wait is spread by +-20 %
AUTH_BACKOFF = 60.0                  # the first wait after a rejected token; doubles each time ...
AUTH_BACKOFF_MAX = 3600.0            # ... up to 1 h (a failed login each minute could get the PC's IP
                                     # banned). A token saved in Settings builds a new adapter: fresh start.
REGISTRY_DEBOUNCE = 1.0              # registry events -> one re-resolve this long after the last
REGISTRY_POLL_SECONDS = 60.0         # re-resolve period when registry events cannot be subscribed
PROBE_TIMEOUT = 8.0                  # Settings' one-shot registry read
FORBIDDEN_MESSAGE = "Home Assistant blocked this PC (403): too many failed logins, or a proxy rule"
AREAS_NEED_ADMIN = ("Connected, but the area list needs the WebSocket or an administrator's token "
                    "(Home Assistant's template API is admin-only)")
SNAPSHOT_ID = "desk_dial_snapshot"  # scene.create scene_id -> entity scene.desk_dial_snapshot
SCENES_MAX = 20
SCENE_TYPES = ("scene", "script", "automation")
STATE_DOMAINS = ("light",) + SCENE_TYPES
REGISTRY_EVENTS = ("entity_registry_updated", "device_registry_updated", "area_registry_updated")
REGISTRY_LISTS = (("areas", "config/area_registry/list"), ("entities", "config/entity_registry/list"),
                  ("devices", "config/device_registry/list"))
_RUN_SERVICE = {"scene": ("scene", "turn_on"), "script": ("script", "turn_on"),
                "automation": ("automation", "trigger")}
_ENTITY_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_.")
_AREA_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")

# REST fallback (POST /api/template, read-only). The area id is a validated slug (valid_area), so it
# is safe inline. The first form skips hidden entities; the plain form is for older Home Assistants.
AREA_TEMPLATE = r"""{%- set a = '@AREA@' -%}{%- set es = area_entities(a) -%}
{{ {"known": area_name(a) is not none, "name": area_name(a) or "",
    "lights": es | select('match', 'light\\.') | reject('is_hidden_entity') | list,
    "extras": es | select('match', '(scene|script|automation)\\.') | reject('is_hidden_entity') | list} | tojson }}"""
AREA_TEMPLATE_PLAIN = r"""{%- set a = '@AREA@' -%}{%- set es = area_entities(a) -%}
{{ {"known": area_name(a) is not none, "name": area_name(a) or "",
    "lights": es | select('match', 'light\\.') | list,
    "extras": es | select('match', '(scene|script|automation)\\.') | list} | tojson }}"""
AREAS_TEMPLATE = r"""{%- set ns = namespace(out=[]) -%}{%- for a in areas() -%}
{%- set es = area_entities(a) -%}
{%- set ns.out = ns.out + [[a, area_name(a), es | select('match', 'light\\.') | list,
    es | select('match', '(scene|script|automation)\\.') | list]] -%}
{%- endfor -%}{{ ns.out | tojson }}"""


class HomeAssistantError(RuntimeError):
    """A Home Assistant failure with a section 9.10-style ``outcome``: ``not_configured``,
    ``offline``, ``auth``, ``forbidden``, ``not_allowed``, ``timeout``, ``unavailable`` or ``failed``."""

    def __init__(self, message, outcome="failed", status=None):
        super().__init__(message)
        self.outcome = outcome
        self.status = status            # the HTTP status of a REST answer, else None


_LAN_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain")


def is_lan_host(host):
    """True for a host on the owner's own network: a private / loopback / link-local IP literal, a
    dotless name (``homeassistant``) or an mDNS / home suffix (``homeassistant.local``). Desk Dial
    talks to such a host directly: a system or ``HTTP(S)_PROXY`` proxy (a corporate laptop, a VPN
    client, a debugging proxy) cannot reach it, so it is bypassed. A public name keeps the proxy."""
    if not isinstance(host, str) or not host.strip():
        return False
    host = host.strip().strip("[]").rstrip(".").lower()
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return host == "localhost" or "." not in host or host.endswith(_LAN_SUFFIXES)
    return (address.is_private or address.is_loopback or address.is_link_local
            or (address.version == 4 and address in _CGNAT))      # a Tailscale-style 100.64/10 address


_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def reconnect_delay(attempt):
    """The wait before WebSocket attempt ``attempt`` + 1 (0-based count of failed attempts in a row):
    BACKOFF's step, spread by +-BACKOFF_JITTER so many PCs do not reconnect in lockstep."""
    base = BACKOFF[min(max(int(attempt), 0), len(BACKOFF) - 1)]
    return base * random.uniform(1.0 - BACKOFF_JITTER, 1.0 + BACKOFF_JITTER)


def auth_backoff(refusals):
    """The wait after the ``refusals``-th rejected token in a row (0-based): AUTH_BACKOFF doubled
    each time, at most AUTH_BACKOFF_MAX."""
    return min(AUTH_BACKOFF * 2 ** min(max(int(refusals), 0), 32), AUTH_BACKOFF_MAX)


def _default_ws_factory():
    """``websocket-client``'s create_connection, or None when the library is missing. A LAN host
    never goes through an ``http(s)_proxy`` from the environment (the auth frame stays on the LAN)."""
    try:
        import websocket  # websocket-client
    except ImportError:
        return None

    def connect(url, timeout):
        host = urlsplit(url).hostname
        options = {"http_no_proxy": [host]} if is_lan_host(host) else {}
        return websocket.create_connection(url, timeout=timeout, **options)
    return connect


def is_network_error(exc):
    """True for a dropped / refused / timed-out socket or a garbled frame (OSError, websocket-client's
    WebSocket* exceptions, a frame that is not JSON); False for anything else, which is a bug in the
    session's own code (KeyError, TypeError, ...)."""
    if isinstance(exc, (OSError, json.JSONDecodeError)):
        return True
    return any(cls.__name__.startswith("WebSocket") for cls in type(exc).__mro__)


def _default_http(base_url=""):
    """A requests session; for a LAN Home Assistant it ignores the system / environment proxy
    (``trust_env`` off, as the artwork fetcher does)."""
    import requests
    session = requests.Session()
    if is_lan_host(urlsplit(base_url or "").hostname):
        session.trust_env = False
    return session


# ------------------------------------------------------------------ config helpers (pure)
def valid_entity(entity_id, domains=None):
    """``domain.object_id`` in Home Assistant's lower-case charset, optionally of ``domains``."""
    if not isinstance(entity_id, str) or not 3 <= len(entity_id) <= 255 or entity_id.count(".") != 1:
        return False
    if not set(entity_id) <= _ENTITY_CHARS:
        return False
    domain, object_id = entity_id.split(".")
    if not domain or not object_id:
        return False
    return domains is None or domain in domains


def valid_area(area_id):
    """A Home Assistant area id: a lower-case slug (``office``, ``living_room``, or an older hex id)."""
    return isinstance(area_id, str) and 1 <= len(area_id) <= 100 and set(area_id) <= _AREA_CHARS


def normalize_base_url(value):
    """``http(s)://host[:port][/path]`` without a trailing slash, query or fragment; ValueError else.
    Never carries credentials (a ``user:pass@`` part is refused)."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Enter the Home Assistant address, e.g. http://homeassistant.local:8123")
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("The Home Assistant address must start with http:// or https://")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Enter only the Home Assistant address (no user, query or #)")
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def websocket_url(base_url):
    parts = urlsplit(normalize_base_url(base_url))
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, parts.path + "/api/websocket", "", ""))


def normalize_scenes(raw):
    """settings.json ``ha_scenes`` as an ordered list of {entity_id, type, label[, bri, kelvin]};
    invalid entries and duplicates are dropped. ``type`` defaults to the entity's domain."""
    out, seen = [], set()
    for entry in raw if isinstance(raw, (list, tuple)) else ():
        if isinstance(entry, str):
            entry = {"entity_id": entry}
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id")
        if not valid_entity(entity_id, SCENE_TYPES) or entity_id in seen:
            continue
        domain = entity_id.split(".")[0]
        kind = entry.get("type") if entry.get("type") in SCENE_TYPES else domain
        if kind != domain:
            continue   # the service must match the entity's own domain
        label = entry.get("label")
        label = label.strip()[:40] if isinstance(label, str) and label.strip() else ""
        scene = {"entity_id": entity_id, "type": kind, "label": label}
        bri, kelvin = entry.get("bri"), entry.get("kelvin")
        if type(bri) is int and 1 <= bri <= 100:
            scene["bri"] = bri
        if type(kelvin) is int and MIN_KELVIN <= kelvin <= MAX_KELVIN:
            scene["kelvin"] = kelvin
        seen.add(entity_id)
        out.append(scene)
    return out[:SCENES_MAX]


def clamp_kelvin(value, low=MIN_KELVIN, high=MAX_KELVIN):
    return max(low, min(high, int(value)))


def kelvin_bounds(attributes):
    """The group's reported colour temperature range clamped into 2200..6500 (100 K steps)."""
    attributes = attributes if isinstance(attributes, dict) else {}
    low = attributes.get("min_color_temp_kelvin")
    high = attributes.get("max_color_temp_kelvin")
    if not isinstance(low, (int, float)) and isinstance(attributes.get("max_mireds"), (int, float)) \
            and attributes["max_mireds"] > 0:
        low = 1000000 / attributes["max_mireds"]
    if not isinstance(high, (int, float)) and isinstance(attributes.get("min_mireds"), (int, float)) \
            and attributes["min_mireds"] > 0:
        high = 1000000 / attributes["min_mireds"]
    low = MIN_KELVIN if not isinstance(low, (int, float)) or isinstance(low, bool) else low
    high = MAX_KELVIN if not isinstance(high, (int, float)) or isinstance(high, bool) else high
    low = int(math.ceil(clamp_kelvin(low) / KELVIN_STEP) * KELVIN_STEP)
    high = int(math.floor(clamp_kelvin(high) / KELVIN_STEP) * KELVIN_STEP)
    if high < low:
        return MIN_KELVIN, MAX_KELVIN
    return low, high


def light_facts(state):
    """{available, on, bri, kelvin, min_k, max_k, supports_ct, name} of a light state object."""
    state = state if isinstance(state, dict) else {}
    attributes = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
    value = state.get("state")
    on = value == "on"
    brightness = attributes.get("brightness")
    bri = 0
    if on and isinstance(brightness, (int, float)) and not isinstance(brightness, bool):
        bri = max(1, min(100, int(round(brightness * 100 / 255))))
    elif on:
        bri = 100
    kelvin = attributes.get("color_temp_kelvin")
    if not isinstance(kelvin, (int, float)) or isinstance(kelvin, bool):
        mireds = attributes.get("color_temp")
        kelvin = 1000000 / mireds if isinstance(mireds, (int, float)) and mireds > 0 else None
    low, high = kelvin_bounds(attributes)
    modes = attributes.get("supported_color_modes")
    supports_ct = not isinstance(modes, list) or any(mode in ("color_temp", "rgbww", "rgbw", "rgb", "hs", "xy")
                                                     for mode in modes)
    facts = {"available": value not in (None, "unavailable", "unknown"), "on": on, "bri": bri,
             "kelvin": None if kelvin is None else max(low, min(high, int(round(kelvin / KELVIN_STEP) * KELVIN_STEP))),
             "min_k": low, "max_k": high, "supports_ct": bool(supports_ct),
             "name": attributes.get("friendly_name") if isinstance(attributes.get("friendly_name"), str) else ""}
    return facts


def is_light_group(state):
    """A light group (Home Assistant ``group`` platform, Hue / deCONZ rooms): its state lists members."""
    attributes = state.get("attributes") if isinstance(state, dict) and isinstance(state.get("attributes"), dict) else {}
    members = attributes.get("entity_id")
    return (isinstance(members, (list, tuple)) and bool(members)) or attributes.get("is_hue_group") is True \
        or attributes.get("is_deconz_group") is True


def aggregate_facts(facts):
    """Several lights' ``light_facts`` as one light (the area): {available, on, on_count, bri, kelvin,
    min_k, max_k, supports_ct}. ``bri`` averages the lights that are on (0 when all are off);
    ``kelvin`` averages the on lights that report a colour temperature (None when none does);
    ``min_k``/``max_k`` is the range the colour lights share, else their union, else 2200..6500."""
    facts = [f for f in facts if isinstance(f, dict)]
    live = [f for f in facts if f.get("available")]
    on = [f for f in live if f.get("on")]
    capable = [f for f in (live or facts) if f.get("supports_ct")]
    bri = max(1, min(100, int(round(sum(int(f.get("bri") or 0) for f in on) / len(on))))) if on else 0
    ranges = [(int(f["min_k"]), int(f["max_k"])) for f in capable
              if type(f.get("min_k")) is int and type(f.get("max_k")) is int]
    if ranges:
        low, high = max(r[0] for r in ranges), min(r[1] for r in ranges)
        if low > high:
            low, high = min(r[0] for r in ranges), max(r[1] for r in ranges)
    else:
        low, high = MIN_KELVIN, MAX_KELVIN
    kelvins = [f["kelvin"] for f in on if f.get("supports_ct") and type(f.get("kelvin")) is int]
    kelvin = None
    if kelvins:
        kelvin = max(low, min(high, int(round(sum(kelvins) / len(kelvins) / KELVIN_STEP) * KELVIN_STEP)))
    return {"available": bool(live), "on": bool(on), "on_count": len(on), "bri": bri, "kelvin": kelvin,
            "min_k": low, "max_k": high, "supports_ct": bool(capable)}


def _entry_area(entry, devices):
    """The area of one entity-registry entry (its own, else its device's) or None; ``False`` when the
    entry must be skipped (disabled, hidden, an entity_category entity, a disabled device)."""
    if entry.get("disabled_by") or entry.get("hidden_by") or entry.get("entity_category"):
        return False
    area = entry.get("area_id")
    if area:
        return area
    device = devices.get(entry.get("device_id")) if entry.get("device_id") else None
    if device is None:
        return None
    if device.get("disabled_by"):
        return False
    return device.get("area_id") or None


def resolve_area(area_id, entities, devices, snapshot_entity="scene." + SNAPSHOT_ID):
    """The area's members from the entity / device registry lists (``config/*_registry/list``):
    (lights, extras, scene_areas). ``lights``: sorted light ids (``group`` platform lights skipped;
    state-based groups are skipped where the states are known); ``extras``: the sorted scene / script
    / automation ids assigned to the area (Desk Dial's snapshot excluded); ``scene_areas``: {scene id:
    its area or None} for every scene in the registry (the "scenes touching the area's lights" rule)."""
    devices = {d.get("id"): d for d in devices if isinstance(d, dict) and d.get("id")} \
        if isinstance(devices, (list, tuple)) else {}
    lights, extras, scene_areas = [], [], {}
    for entry in entities if isinstance(entities, (list, tuple)) else ():
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id")
        if not valid_entity(entity_id, STATE_DOMAINS) or entity_id == snapshot_entity:
            continue
        area = _entry_area(entry, devices)
        domain = entity_id.split(".")[0]
        if domain == "scene":
            scene_areas[entity_id] = False if area is False else (area or None)   # False: hidden / disabled
        if area is False or area != area_id:
            continue
        if domain == "light":
            if entry.get("platform") != "group":
                lights.append(entity_id)
        else:
            extras.append(entity_id)
    return sorted(set(lights)), sorted(set(extras)), scene_areas


def area_light_counts(areas, entities, devices, states=None):
    """Settings' area list: sorted [(area_id, name, light count)] (light groups not counted)."""
    states = {s.get("entity_id"): s for s in states if isinstance(s, dict)} if isinstance(states, list) else {}
    out = []
    for area in areas if isinstance(areas, (list, tuple)) else ():
        area_id = area.get("area_id") if isinstance(area, dict) else None
        if not valid_area(area_id):
            continue
        name = area.get("name") if isinstance(area.get("name"), str) and area.get("name").strip() else area_id
        lights = resolve_area(area_id, entities, devices)[0]
        count = len([entity for entity in lights if not is_light_group(states.get(entity))])
        out.append((area_id, name.strip()[:60], count))
    out.sort(key=lambda row: row[1].casefold())
    return out


def _friendly(entity_id, state):
    attributes = state.get("attributes") if isinstance(state, dict) and isinstance(state.get("attributes"), dict) else {}
    name = attributes.get("friendly_name")
    return (name.strip() if isinstance(name, str) and name.strip() else entity_id.split(".", 1)[-1])[:60]


def light_row(entity_id, state):
    """One light as Settings and ``read_state()["lights"]`` show it: {entity_id, name, on, bri,
    kelvin, available}; a light with no state yet is unavailable. ``bri`` is 0 and ``kelvin`` None
    while off."""
    if not isinstance(state, dict):
        return {"entity_id": entity_id, "name": _friendly(entity_id, None), "on": False, "bri": 0, "kelvin": None,
                "available": False}
    facts = light_facts(state)
    on = bool(facts["on"] and facts["available"])
    return {"entity_id": entity_id, "name": _friendly(entity_id, state), "on": on, "bri": facts["bri"] if on else 0,
            "kelvin": facts["kelvin"] if on and facts["supports_ct"] else None, "available": facts["available"]}


def sort_rows(rows):
    return sorted(rows, key=lambda row: (row["name"].casefold(), row["entity_id"]))


def scene_preview(state):
    """(bri %, kelvin) a scene reports in its attributes (e.g. Hue scenes' ``brightness``), else
    (None, None). Scripts and automations never have one."""
    attributes = state.get("attributes") if isinstance(state, dict) and isinstance(state.get("attributes"), dict) else {}
    bri = kelvin = None
    number = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)  # noqa: E731
    if number(attributes.get("brightness_pct")):
        bri = attributes["brightness_pct"]
    elif number(attributes.get("brightness")):
        value = attributes["brightness"]
        bri = value * 100 / 255 if value > 100 else value   # 0..255 (a light's scale) or already percent
    if bri is not None:
        bri = max(1, min(100, int(round(bri)))) if bri > 0 else None
    if number(attributes.get("color_temp_kelvin")):
        kelvin = attributes["color_temp_kelvin"]
    elif number(attributes.get("color_temp")) and attributes["color_temp"] > 0:
        kelvin = 1000000 / attributes["color_temp"]
    if kelvin is not None:
        kelvin = clamp_kelvin(int(round(kelvin / KELVIN_STEP) * KELVIN_STEP))
    return bri, kelvin


def area_scene_ids(area_id, lights, extras, scene_areas, states, exclude=()):
    """The area's automatic Scenes list (ids, by name): the scenes / scripts / automations assigned
    to it and the scenes touching its lights that belong to no other area."""
    states = states if isinstance(states, dict) else {}
    lights = set(lights)
    chosen = set(extras)
    for entity, state in states.items():
        if not isinstance(entity, str) or not entity.startswith("scene.") or entity in chosen:
            continue
        if scene_areas.get(entity) not in (None, area_id):
            continue     # a scene assigned to another area (or hidden / disabled)
        attributes = state.get("attributes") if isinstance(state, dict) and isinstance(state.get("attributes"), dict) \
            else {}
        members = attributes.get("entity_id")
        if isinstance(members, (list, tuple)) and lights.intersection(members):
            chosen.add(entity)
    chosen -= set(exclude) | {"scene." + SNAPSHOT_ID}
    ranked = [(_friendly(entity, states.get(entity)).casefold(), entity) for entity in chosen
              if valid_entity(entity, SCENE_TYPES)]
    return [entity for _key, entity in sorted(ranked)]


def area_details(area_id, lights, extras, scene_areas, states):
    """Settings' live lists for one area: {"lights": rows sorted by name (light groups skipped),
    "scenes": [{entity_id, name, type}]}."""
    states = states if isinstance(states, dict) else {}
    rows = [light_row(entity, states.get(entity)) for entity in lights if not is_light_group(states.get(entity))]
    scenes = [{"entity_id": entity, "name": _friendly(entity, states.get(entity)), "type": entity.split(".")[0]}
              for entity in area_scene_ids(area_id, lights, extras, scene_areas, states)]
    return {"lights": sort_rows(rows), "scenes": scenes}


def default_area(areas, current=""):
    """The area the dialog preselects: the configured one, else the first. No area name is preferred."""
    ids = [row[0] for row in areas or ()]
    if current and current in ids:
        return current
    return ids[0] if ids else ""


def _parse_json_text(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


# ------------------------------------------------------------------ the adapter
class HomeAssistantAdapter:
    def __init__(self, base_url, token, light_entity="", scenes=(), *, area_id="", ws_factory=None, http=None,
                 clock=None, sleep=None, snapshot_id=SNAPSHOT_ID, rest_poll=REST_POLL_SECONDS):
        self.base_url = normalize_base_url(base_url) if base_url else ""
        self._token = token if isinstance(token, str) and token.strip() else ""
        self.area_id = area_id if valid_area(area_id) else ""
        # The area wins; a single light is the release-1 setup (kept when no area is chosen).
        self.light_entity = "" if self.area_id else (light_entity if valid_entity(light_entity, ("light",)) else "")
        self.scenes = normalize_scenes(scenes)
        self.snapshot_id = snapshot_id
        self.snapshot_entity = "scene." + snapshot_id
        self._ws_factory = ws_factory
        self._http = http
        self._clock = clock or time.monotonic
        self._wait = sleep                      # tests: a sleep that advances their clock
        self.rest_poll = rest_poll
        self._lock = threading.RLock()          # state, pending calls
        self._send_lock = threading.Lock()      # id allocation + one frame on the socket at a time
        self._states = {}                       # entity_id -> state object
        self._online = False
        self._reason = "not_configured" if not self.configured else "connecting"
        self._transport = ""                    # "ws" | "rest" | ""
        self._ws = None
        self._ids = itertools.count(1)
        self._pending = {}                      # id -> {"event", "result"}
        self._last_write = -10.0
        self._last_message = 0.0
        self._ping_sent = None
        self._revision = 0
        self._listener = None
        self._stop = threading.Event()
        self._thread = None
        self._snapshot = False                  # Desk Dial's own snapshot exists in HA
        self._snapshot_members = None           # the lights it holds (None: unknown)
        self._session_bugs = set()              # exception types a session raised, logged with traceback once
        self._write_lock = threading.Lock()     # writes (throttle) one at a time
        # The area (area mode only).
        self._resolved_once = False             # the registry (or the REST template) was read
        self._area_known = None                 # True / False (deleted) / None (registry unreadable)
        self._area_name = ""
        self._resolved = []                     # the area's lights from the registry (groups filtered on use)
        self._extras = []                       # scenes / scripts / automations assigned to the area
        self._scene_areas = {}                  # scene id -> its registry area (None: none)
        self._registry_due = None               # the reader's debounced re-resolve time
        self._template_at = None                # the last area resolution (REST template or registry)
        self._last_level = (0, None)            # (bri, kelvin) while any light was last on (r3.1)
        self._level_hold = False                # All off in progress: keep the level taken before it

    # ------------------------------------------------------------------ lifecycle
    @property
    def configured(self):
        return bool(self.base_url and self._token and (self.area_id or self.light_entity))

    def set_listener(self, callback):
        self._listener = callback

    def start(self):
        """Start the reader thread (idempotent). Nothing connects before this call."""
        if not self.configured or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="nanod-ha-reader", daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        with self._lock:
            for pending in self._pending.values():
                pending["event"].set()

    # ------------------------------------------------------------------ plumbing
    def _now(self):
        return self._clock()

    def _sleep(self, seconds):
        if seconds <= 0:
            return
        if self._wait is not None:
            self._wait(seconds)
        else:
            self._stop.wait(seconds)

    def _headers(self):
        return {"Authorization": "Bearer " + self._token, "Content-Type": "application/json"}

    def _session(self):
        if self._http is None:
            self._http = _default_http(self.base_url)
        return self._http

    def _rest(self, method, path, body=None):
        """One REST call (redirects off, bounded timeout). Raises HomeAssistantError."""
        if not self.base_url or not self._token:
            raise HomeAssistantError("Home Assistant is not set up", "not_configured")
        url = self.base_url + path
        try:
            session = self._session()
            if method == "GET":
                response = session.get(url, headers=self._headers(), timeout=CONNECT_TIMEOUT, allow_redirects=False)
            else:
                response = session.post(url, headers=self._headers(), data=json.dumps(body or {}),
                                        timeout=CONNECT_TIMEOUT, allow_redirects=False)
        except Exception as exc:
            raise HomeAssistantError(f"Home Assistant unreachable ({type(exc).__name__})", "offline") from None
        status = getattr(response, "status_code", 0)
        if status == 401:
            raise HomeAssistantError("Home Assistant refused the token", "auth")
        if status == 403:
            raise HomeAssistantError(FORBIDDEN_MESSAGE, "forbidden")
        if status == 404:
            raise HomeAssistantError("Home Assistant entity not found", "unavailable", 404)
        if not 200 <= status < 300:
            raise HomeAssistantError(f"Home Assistant answered {status}", "failed", status)
        try:
            return response.json()
        except Exception:
            raise HomeAssistantError("Home Assistant sent an unreadable answer", "failed") from None

    def _send_frame(self, ws, message, pending=None):
        """Allocate the next id and send one frame under ``_send_lock`` (ids reach Home Assistant in
        increasing order: the r3.1 id-race fix). ``pending`` is registered before the frame leaves."""
        with self._send_lock:
            ident = next(self._ids)
            if pending is not None:
                with self._lock:
                    self._pending[ident] = pending
            try:
                ws.send(json.dumps({"id": ident, **message}))
            except Exception:
                if pending is not None:
                    with self._lock:
                        self._pending.pop(ident, None)
                raise
        return ident

    def _target(self):
        """(key, value) the light services are aimed at: the area, else the single light."""
        return ("area_id", self.area_id) if self.area_id else ("entity_id", self.light_entity)

    def _lights(self):
        """The lights Desk Dial drives now (area mode: the resolved area minus light groups)."""
        if not self.area_id:
            return [self.light_entity] if self.light_entity else []
        with self._lock:
            return [entity for entity in self._resolved if not is_light_group(self._states.get(entity))]

    def _effective_scenes(self):
        """The manual ``ha_scenes`` (their order and labels) then, in area mode, the scenes / scripts /
        automations assigned to the area and the scenes touching its lights (by name; never Desk
        Dial's snapshot), at most SCENES_MAX."""
        scenes = [dict(scene) for scene in self.scenes]
        if not self.area_id:
            return scenes
        with self._lock:
            seen = {scene["entity_id"] for scene in scenes}
            auto = area_scene_ids(self.area_id, self._lights(), self._extras, self._scene_areas, self._states,
                                  exclude=seen | {self.snapshot_entity})
        for entity in auto:
            scenes.append({"entity_id": entity, "type": entity.split(".")[0], "label": "", "auto": True})
        return scenes[:SCENES_MAX]

    def _watched(self):
        ids = self._lights() + [self.snapshot_entity] + [scene["entity_id"] for scene in self._effective_scenes()]
        return [entity for entity in ids if entity]

    def _set_status(self, online, reason, transport=None):
        with self._lock:
            changed = online != self._online or reason != self._reason
            self._online, self._reason = online, reason
            if transport is not None:
                self._transport = transport
            if changed:
                self._revision += 1
        if changed:
            self._notify()

    def _store(self, state):
        """Keep one state object; True when it belongs to what Desk Dial shows (a listener update).
        Area mode keeps every light / scene / script / automation (a light that joins the area later
        is known at once); the single-light setup keeps only its own entities."""
        entity = state.get("entity_id") if isinstance(state, dict) else None
        if not valid_entity(entity):
            return False
        if self.area_id:
            if entity.split(".")[0] not in STATE_DOMAINS:
                return False
        elif entity not in self._watched():
            return False
        with self._lock:
            if self._states.get(entity) == state:
                return False
            self._states[entity] = state
            if entity == self.snapshot_entity:
                self._snapshot = state.get("state") not in (None, "unavailable")
                attributes = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
                members = attributes.get("entity_id")
                if isinstance(members, (list, tuple)):
                    self._snapshot_members = sorted(str(member) for member in members)
            watched = entity in self._watched()
            if watched:
                self._revision += 1
        return watched

    def _drop(self, entity):
        """An entity was removed (``state_changed`` with no new state)."""
        with self._lock:
            watched = entity in self._watched()
            self._states.pop(entity, None)
            if entity == self.snapshot_entity:
                self._snapshot, self._snapshot_members = False, None
            if watched:
                self._revision += 1
        return watched

    def _replace_states(self, states):
        """A full state list (WebSocket ``get_states`` after a (re)connect): keep it and forget every
        stored entity it no longer holds. Removals made while the socket was down (a deleted scene,
        Desk Dial's ``scene.create`` snapshot lost to a Home Assistant restart) send no event, so a
        merge would keep them forever; an absent snapshot reads as no snapshot. True when what Desk
        Dial shows changed."""
        changed, seen = False, set()
        for state in states:
            if isinstance(state, dict):
                seen.add(state.get("entity_id"))
                changed |= self._store(state)
        with self._lock:
            gone = [entity for entity in self._states if entity not in seen]
            if self.snapshot_entity not in seen and (self._snapshot or self._snapshot_members is not None):
                gone.append(self.snapshot_entity)
        for entity in gone:
            changed |= self._drop(entity)
        return changed

    def _notify(self):
        callback = self._listener
        if callback is None:
            return
        try:
            callback(self.read_state())
        except Exception as exc:  # a listener failure never stops the reader
            _log.warning("Lights state listener failed (%s)", type(exc).__name__)

    # ------------------------------------------------------------------ the area
    def _set_resolution(self, known, name, lights, extras, scene_areas):
        """Install one area resolution (registry or REST template); notifies on a change."""
        with self._lock:
            self._template_at = self._now()
            before = (self._resolved_once, self._area_known, self._area_name, self._resolved, self._extras,
                      self._scene_areas)
            self._resolved_once, self._area_known, self._area_name = True, known, name if isinstance(name, str) else ""
            self._resolved, self._extras, self._scene_areas = list(lights), list(extras), dict(scene_areas)
            after = (self._resolved_once, self._area_known, self._area_name, self._resolved, self._extras,
                     self._scene_areas)
            changed = before != after
            if changed:
                self._revision += 1
        if changed:
            if known is False:
                _log.warning("Home Assistant area %s not found (deleted or renamed?)", self.area_id)
            elif known is None:
                _log.warning("Home Assistant area %s could not be read", self.area_id)
            else:
                _log.info("Home Assistant area %s: %d light(s), %d scene(s) / script(s) / automation(s)",
                          self.area_id, len(lights), len(extras))
            self._notify()
        return changed

    def _apply_registry(self, lists):
        """The three registry lists of one fetch; any refused list -> the REST template instead."""
        if any(not isinstance(lists.get(name), list) for name, _ in REGISTRY_LISTS):
            _log.warning("Home Assistant registry not readable over the WebSocket; using the REST template")
            try:
                if self._resolve_rest():
                    return True
            except HomeAssistantError:
                pass
            self._resolution_failed()
            return False
        areas = {area.get("area_id"): area.get("name") for area in lists["areas"] if isinstance(area, dict)}
        lights, extras, scene_areas = resolve_area(self.area_id, lists["entities"], lists["devices"],
                                                   self.snapshot_entity)
        self._set_resolution(self.area_id in areas, areas.get(self.area_id) or "", lights, extras, scene_areas)
        return True

    def _resolution_failed(self):
        """The area could not be read: keep a previous good resolution, else report ``registry``."""
        with self._lock:
            keep = self._resolved_once and self._area_known is not None
        if not keep:
            self._set_resolution(None, "", [], [], {})

    def _resolve_rest(self):
        """The area through ``POST /api/template`` (``area_entities``). Raises offline errors; False
        when neither template renders. The template API is admin-only in Home Assistant: a 401 / 403
        here is a non-admin user, not a refused token (only ``/api/`` or ``/api/states`` says that),
        so it reads as "template unavailable" and the caller keeps the previous resolution."""
        last = None
        for template in (AREA_TEMPLATE, AREA_TEMPLATE_PLAIN):
            try:
                rendered = self._rest("POST", "/api/template", {"template": template.replace("@AREA@", self.area_id)})
            except HomeAssistantError as exc:
                if exc.outcome in ("offline", "forbidden"):
                    raise
                if isinstance(exc.status, int) and exc.status >= 500:
                    # A proxy in front of a restarting Home Assistant (502 / 503): not reachable.
                    raise HomeAssistantError(f"Home Assistant answered {exc.status}", "offline", exc.status) from None
                if exc.outcome == "auth":
                    _log.info("Home Assistant area template refused (admin-only); keeping the area as last read")
                    return False
                last = exc
                continue
            data = _parse_json_text(rendered)
            if not isinstance(data, dict):
                continue
            lights = [e for e in data.get("lights") or () if valid_entity(e, ("light",))]
            extras = [e for e in data.get("extras") or () if valid_entity(e, SCENE_TYPES) and e != self.snapshot_entity]
            self._set_resolution(bool(data.get("known")), data.get("name") or "", sorted(set(lights)),
                                 sorted(set(extras)), {})
            return True
        if last is not None:
            _log.warning("Home Assistant area template refused (%s)", last.outcome)
        return False

    # ------------------------------------------------------------------ state (never raises)
    def read_state(self):
        try:
            with self._lock:
                online, reason = self._online, self._reason
                lights = self._lights()
                facts = [light_facts(self._states[entity]) for entity in lights if entity in self._states]
                rows = sort_rows([light_row(entity, self._states.get(entity)) for entity in lights])
                scenes = []
                for scene in self._effective_scenes():
                    state = self._states.get(scene["entity_id"]) or {}
                    attributes = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
                    name = scene["label"] or attributes.get("friendly_name") or scene["entity_id"].split(".")[1]
                    # r3.1: a brightness / temperature preview where one is known (a manual ha_scenes
                    # value, else the scene's own attributes); scripts and automations have none.
                    preview = scene_preview(state) if scene["type"] == "scene" else (None, None)
                    entry = {"entity_id": scene["entity_id"], "type": scene["type"], "label": str(name)[:40],
                             "running": scene["type"] == "script" and state.get("state") == "on",
                             "last": state.get("state") if scene["type"] == "scene" else None,
                             "bri": scene.get("bri", preview[0]), "kelvin": scene.get("kelvin", preview[1])}
                    scenes.append(entry)
                result = {"configured": self.configured, "online": bool(online), "reason": reason, "detail": "",
                          "transport": self._transport, "revision": self._revision, "scenes": scenes,
                          "snapshot": self._snapshot, "entity": self.light_entity, "area_id": self.area_id,
                          "count": len(lights) if self.area_id else None, "entities": list(lights),
                          "lights": rows, "unavailable_count": sum(1 for row in rows if not row["available"])}
                resolved, known, area_name = self._resolved_once, self._area_known, self._area_name
                aggregate = aggregate_facts(facts) if facts else None
                if aggregate is not None and aggregate["on"] and not self._level_hold:
                    self._last_level = (aggregate["bri"], aggregate["kelvin"] if aggregate["kelvin"] is not None
                                        else self._last_level[1])
                elif aggregate is not None and not aggregate["on"]:
                    self._level_hold = False     # the All off landed: later levels count again
                last_bri, last_kelvin = self._last_level
            if self.area_id:
                result["name"] = area_name or ""
            detail = ""
            if self.area_id and not resolved:
                detail = "connecting"
            elif self.area_id and known is None:
                detail = "registry"
            elif self.area_id and known is False:
                detail = "area_missing"
            elif not lights:
                detail = "no_lights"
            elif aggregate is None:
                detail = "no_state"
            elif not aggregate["available"]:
                detail = "lights_unavailable"
            if aggregate is not None:
                result.update(on=aggregate["on"], on_count=aggregate["on_count"], bri=aggregate["bri"],
                              kelvin=aggregate["kelvin"], min_k=aggregate["min_k"], max_k=aggregate["max_k"],
                              supports_ct=aggregate["supports_ct"], available=aggregate["available"])
                if not aggregate["on"]:
                    # r3.1: everything off keeps reporting the last known level (``on`` says it is off).
                    result.update(bri=last_bri, kelvin=last_kelvin)
                if not self.area_id:
                    result["name"] = facts[0]["name"]
            else:
                result["available"] = False
            if result["online"] and detail:
                result["online"] = False
                result["reason"] = "connecting" if detail == "connecting" else "unavailable"
                result["detail"] = detail
            if result["online"]:
                result["reason"] = ""
            return result
        except Exception as exc:  # never raises
            return {"configured": self.configured, "online": False, "reason": "failed",
                    "error": type(exc).__name__, "scenes": [], "revision": -1}

    # ------------------------------------------------------------------ the allowlist
    def _scene_entry(self, entity_id):
        for scene in self._effective_scenes():
            if scene["entity_id"] == entity_id:
                return scene
        return None

    def _guard(self, domain, service, data):
        """Refuse every call outside the allowlist, before any I/O."""
        data = data if isinstance(data, dict) else {}
        key, target = self._target()
        entity = data.get("entity_id")
        ok = False
        if domain == "light" and service in ("turn_on", "turn_off"):
            # The area (or the single light), or — area mode, r3.1 — a list of the area's own lights
            # (a turn changes only the lights that are on).
            if data.get(key) == target:
                aim = key
            elif self.area_id and "entity_id" in data and self._light_subset(data["entity_id"]):
                aim = "entity_id"
            else:
                aim = None
            values = {"brightness_pct", "color_temp_kelvin", "transition"} if service == "turn_on" else {"transition"}
            ok = (aim is not None and set(data) <= {aim} | values
                  and ("brightness_pct" not in data or (type(data["brightness_pct"]) is int
                                                         and 1 <= data["brightness_pct"] <= 100))
                  and ("color_temp_kelvin" not in data or (type(data["color_temp_kelvin"]) is int
                                                            and MIN_KELVIN <= data["color_temp_kelvin"] <= MAX_KELVIN))
                  and ("transition" not in data or (type(data["transition"]) in (int, float)
                                                     and 0 <= data["transition"] <= 5)))
        elif domain == "scene" and service == "create":
            lights = self._lights()
            ok = (set(data) == {"scene_id", "snapshot_entities"} and data["scene_id"] == self.snapshot_id
                  and bool(lights) and data["snapshot_entities"] == lights)
        elif domain == "scene" and service == "turn_on":
            scene = self._scene_entry(entity)
            ok = set(data) == {"entity_id"} and (entity == self.snapshot_entity
                                                 or (scene is not None and scene["type"] == "scene"))
        elif domain == "script" and service == "turn_on":
            scene = self._scene_entry(entity)
            ok = set(data) == {"entity_id"} and scene is not None and scene["type"] == "script"
        elif domain == "automation" and service == "trigger":
            scene = self._scene_entry(entity)
            ok = set(data) == {"entity_id"} and scene is not None and scene["type"] == "automation"
        if not ok or not target:
            raise HomeAssistantError("This Home Assistant change is not allowed", "not_allowed")

    def _light_subset(self, value):
        """A non-empty list (or one id) of lights all in the resolved area."""
        ids = [value] if isinstance(value, str) else value
        if not isinstance(ids, list) or not ids or not all(isinstance(entity, str) for entity in ids):
            return False
        return len(set(ids)) == len(ids) and set(ids) <= set(self._lights())

    def call_service(self, domain, service, data):
        """One guarded service call over the WebSocket, else REST. Raises HomeAssistantError."""
        self._guard(domain, service, data)
        if not self.configured:
            raise HomeAssistantError("Home Assistant is not set up", "not_configured")
        with self._lock:
            online, reason = self._online, self._reason
        if not online and reason in ("auth", "forbidden"):
            raise HomeAssistantError("Home Assistant refused the token" if reason == "auth" else FORBIDDEN_MESSAGE,
                                     reason)
        ws = self._ws if self._transport == "ws" else None
        if ws is not None:
            target = {key: data[key] for key in ("entity_id", "area_id") if key in data}
            return self._ws_call({"type": "call_service", "domain": domain, "service": service,
                                  "service_data": {k: v for k, v in data.items() if k not in target},
                                  **({"target": target} if target else {})})
        result = self._rest("POST", f"/api/services/{quote(domain)}/{quote(service)}", data)
        for state in result if isinstance(result, list) else ():
            self._store(state)
        self._notify()
        return result

    def _ws_call(self, message):
        ws = self._ws
        if ws is None:
            raise HomeAssistantError("Home Assistant connection lost", "offline")
        pending = {"event": threading.Event(), "result": None}
        try:
            ident = self._send_frame(ws, message, pending)
        except Exception as exc:
            raise HomeAssistantError(f"Home Assistant connection lost ({type(exc).__name__})", "offline") from None
        if not pending["event"].wait(CALL_TIMEOUT):
            with self._lock:
                self._pending.pop(ident, None)
            raise HomeAssistantError("Home Assistant did not answer in time", "timeout")
        result = pending["result"]
        if not isinstance(result, dict):
            raise HomeAssistantError("Home Assistant connection lost", "offline")
        if not result.get("success"):
            error = result.get("error") if isinstance(result.get("error"), dict) else {}
            code = error.get("code") if isinstance(error.get("code"), str) else "failed"
            raise HomeAssistantError(f"Home Assistant refused the call ({code[:32]})",
                                     "unavailable" if code in ("not_found", "service_not_found") else "failed")
        return result.get("result")

    # ------------------------------------------------------------------ operations (lane jobs)
    def _throttle(self):
        wait = self._last_write + WRITE_INTERVAL - self._now()
        if wait > 0:
            self._sleep(wait)
        self._last_write = self._now()

    def turn_targets(self):
        """r3.1 turn semantics (area mode): the available lights that are on; when none is on, every
        available light (a turn from all off switches them all on). Sorted ids."""
        with self._lock:
            rows = [light_row(entity, self._states.get(entity)) for entity in self._lights()]
        live = [row["entity_id"] for row in rows if row["available"]]
        on = [row["entity_id"] for row in rows if row["available"] and row["on"]]
        return sorted(on or live)

    def set_light(self, bri=None, kelvin=None, on_bri=None, targets=None, transition=None):
        """Brightness 1..100 and/or colour temperature (clamped to the lights' shared range, 100 K
        steps), every target set to the same value. Area mode (r3.1): ``targets`` is the list of
        lights to change (a subset of the area; the controller sends the lights that are on); by
        default the lights that are on, or every available light when all are off. The single-light
        setup aims at its light. ``on_bri`` is the level used when a temperature change turns the
        lights on."""
        state = self.read_state()
        if self.area_id:
            aim = sorted(targets) if isinstance(targets, (list, tuple)) and targets else self.turn_targets()
            if not aim:
                raise HomeAssistantError("No Home Assistant light is available", "unavailable")
            data = {"entity_id": aim}
        else:
            key, target = self._target()
            data = {key: target}
        low, high = state.get("min_k", MIN_KELVIN), state.get("max_k", MAX_KELVIN)
        if bri is not None:
            data["brightness_pct"] = max(1, min(100, int(bri)))
        if kelvin is not None:
            data["color_temp_kelvin"] = max(low, min(high, int(round(int(kelvin) / KELVIN_STEP) * KELVIN_STEP)))
            if bri is None and not state.get("on") and type(on_bri) is int and 1 <= on_bri <= 100:
                data["brightness_pct"] = on_bri
        if len(data) == 1:
            return state
        data["transition"] = LIGHT_TRANSITION if transition is None else transition
        with self._write_lock:
            self._throttle()
            self._level_hold = False
            self.call_service("light", "turn_on", data)
        result = self.read_state()
        applied = {k: data[k] for k in ("brightness_pct", "color_temp_kelvin") if k in data}
        result = {**result, "_applied": {"bri": applied.get("brightness_pct"), "kelvin": applied.get("color_temp_kelvin")}}
        if self.area_id:
            result["_targets"] = list(data["entity_id"])       # the lights this write changed
        return result

    def power(self, on):
        """All off: snapshot (``scene.create`` over the resolved lights) then ``light.turn_off`` on the
        area. Turn on: the snapshot (``scene.turn_on``) when Desk Dial has one holding exactly the
        area's lights now, else ``light.turn_on`` on the area (HA's last state)."""
        key, target = self._target()
        with self._write_lock:
            self._throttle()
            if on:
                with self._lock:
                    self._level_hold = False
                    snapshot, members = self._snapshot, self._snapshot_members
                if snapshot and (members is None or set(members) == set(self._lights())):
                    self.call_service("scene", "turn_on", {"entity_id": self.snapshot_entity})
                else:
                    self.call_service("light", "turn_on", {key: target})
            else:
                # The level before the lights go off one by one (their events would leave the
                # last light's level behind): kept as the last known level while off.
                before = self.read_state()
                with self._lock:
                    if before.get("on") and type(before.get("bri")) is int:
                        self._last_level = (before["bri"], before.get("kelvin") if type(before.get("kelvin")) is int
                                            else self._last_level[1])
                        self._level_hold = True
                lights = self._lights()
                snapshot = False
                if lights:
                    try:
                        self.call_service("scene", "create", {"scene_id": self.snapshot_id,
                                                              "snapshot_entities": lights})
                        snapshot = True
                    except HomeAssistantError as exc:
                        if exc.outcome in ("auth", "forbidden", "not_allowed"):
                            raise
                        _log.warning("Lights snapshot not taken (%s); turning off anyway", exc.outcome)
                with self._lock:
                    if snapshot:
                        self._snapshot, self._snapshot_members = True, sorted(lights)
                    else:
                        # An older snapshot holds levels from before this All off: Turn on must not
                        # replay it, so it reads as none until the next snapshot is taken.
                        self._snapshot, self._snapshot_members = False, None
                self.call_service("light", "turn_off", {key: target})
        return self.read_state()

    def run_scene(self, entity_id):
        scene = self._scene_entry(entity_id)
        if scene is None:
            raise HomeAssistantError("This Home Assistant change is not allowed", "not_allowed")
        domain, service = _RUN_SERVICE[scene["type"]]
        with self._write_lock:
            self._throttle()
            self._level_hold = False
            self.call_service(domain, service, {"entity_id": entity_id})
        return self.read_state()

    # ------------------------------------------------------------------ Settings (read-only)
    def test_connection(self):
        """Settings' "Test connection" (read-only): REST ``/api/``, ``/api/config`` (the version) and
        ``/api/states``, then the areas (``config/area_registry/list`` + the entity / device
        registries over a one-shot WebSocket, else the ``areas()`` REST template). Returns {ok,
        outcome, message, version, entities: {light, scene, script, automation: [(id, name)]}, areas:
        [(area_id, name, light count)], area_details: {area_id: {lights: [light rows], scenes:
        [{entity_id, name, type}]}}, default_area}; never raises and never writes."""
        empty = {"entities": {}, "areas": [], "area_details": {}, "default_area": "", "version": ""}
        if not self.base_url or not self._token:
            return {"ok": False, "outcome": "not_configured", "message": "Enter the address and a token first",
                    **empty}
        try:
            self._rest("GET", "/api/")
            states = self._rest("GET", "/api/states")
        except HomeAssistantError as exc:
            message = {"auth": "Home Assistant refused the token", "forbidden": FORBIDDEN_MESSAGE,
                       "offline": "Can’t reach Home Assistant"}.get(
                exc.outcome, "Home Assistant answered with an error")
            return {"ok": False, "outcome": exc.outcome, "message": message, **empty}
        version = ""
        try:
            config = self._rest("GET", "/api/config")
            version = config.get("version") if isinstance(config, dict) and isinstance(config.get("version"), str) \
                else ""
        except HomeAssistantError:
            pass
        areas, details, probe_version, note = self._probe_areas(states)
        return {"ok": True, "outcome": "ok", "message": "Connected to Home Assistant", "version": version or probe_version,
                "entities": entity_lists(states), "areas": areas, "area_details": details,
                "default_area": default_area(areas, self.area_id), "areas_note": note}

    def _probe_areas(self, states):
        """(areas, area_details, version from the WebSocket hello, note) for Settings. ``note`` is
        AREAS_NEED_ADMIN when neither the registry (WebSocket) nor the admin-only template could be
        read, else ""."""
        by_id = {s.get("entity_id"): s for s in states if isinstance(s, dict)} if isinstance(states, list) else {}
        try:
            lists = self._registry_probe()
        except Exception as exc:
            _log.info("Home Assistant registry probe failed (%s)", type(exc).__name__)
            lists = None
        if lists is not None:
            areas = area_light_counts(lists["areas"], lists["entities"], lists["devices"], states)
            details = {}
            for area_id, _name, _count in areas:
                lights, extras, scene_areas = resolve_area(area_id, lists["entities"], lists["devices"])
                details[area_id] = area_details(area_id, lights, extras, scene_areas, by_id)
            return areas, details, lists.get("version", ""), ""
        try:
            rows = _parse_json_text(self._rest("POST", "/api/template", {"template": AREAS_TEMPLATE}))
        except HomeAssistantError as exc:
            return [], {}, "", AREAS_NEED_ADMIN if exc.outcome == "auth" else ""
        areas, details = [], {}
        for row in rows if isinstance(rows, list) else ():
            if not isinstance(row, (list, tuple)) or len(row) not in (3, 4) or not valid_area(row[0]):
                continue
            name = row[1] if isinstance(row[1], str) and row[1].strip() else row[0]
            if isinstance(row[2], list):
                lights = sorted({e for e in row[2] if valid_entity(e, ("light",))})
                extras = sorted({e for e in (row[3] if len(row) == 4 and isinstance(row[3], list) else ())
                                 if valid_entity(e, SCENE_TYPES)})
                details[row[0]] = area_details(row[0], lights, extras, {}, by_id)
                count = len(details[row[0]]["lights"])
            else:
                count = row[2] if type(row[2]) is int else 0
            areas.append((row[0], name.strip()[:60], count))
        areas.sort(key=lambda r: r[1].casefold())
        return areas, details, "", ""

    def _registry_probe(self):
        """One short WebSocket session reading the three registries (read-only); None when the
        WebSocket is unavailable or any list is refused. ``version`` is the hello's ``ha_version``."""
        factory = self._ws_factory or _default_ws_factory()
        if factory is None:
            return None
        ws = factory(websocket_url(self.base_url), CONNECT_TIMEOUT)
        if ws is None:
            return None
        try:
            hello = self._recv_json(ws)
            if hello.get("type") != "auth_required":
                return None
            ws.send(json.dumps({"type": "auth", "access_token": self._token}))
            if self._recv_json(ws).get("type") != "auth_ok":
                return None
            ids = {}
            for number, (name, kind) in enumerate(REGISTRY_LISTS, start=1):
                ids[number] = name
                ws.send(json.dumps({"id": number, "type": kind}))
            lists = {}
            deadline = time.monotonic() + PROBE_TIMEOUT
            while len(lists) < len(ids) and time.monotonic() < deadline:
                message = self._recv_json(ws)
                name = ids.get(message.get("id")) if message.get("type") == "result" else None
                if name is None:
                    continue
                if not message.get("success") or not isinstance(message.get("result"), list):
                    return None
                lists[name] = message["result"]
            if len(lists) != len(ids):
                return None
            version = hello.get("ha_version")
            lists["version"] = version if isinstance(version, str) else ""
            return lists
        finally:
            try:
                ws.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ the reader thread
    def _run(self):
        attempt = 0
        refusals = 0                            # rejected tokens in a row (WebSocket auth_invalid, REST 401 / 403)
        while not self._stop.is_set():
            outcome = self._session_ws()
            if self._stop.is_set():
                break
            if outcome == "auth":
                self._set_status(False, "auth", "")
                self._stop.wait(auth_backoff(refusals))
                refusals += 1
                continue
            if outcome == "ok":
                # A session that worked (the drop came after its first states): start the back-off
                # over, so a nightly sleep or a Home Assistant restart reconnects in about a second.
                refusals = 0
                attempt = 0
            delay = reconnect_delay(attempt)
            attempt += 1
            poll = self._rest_poll_for(attempt)
            # REST fallback until the next WebSocket attempt; a refused token there backs off too.
            deadline = self._now() + delay
            refused = False
            while not self._stop.is_set() and self._now() < deadline:
                self._rest_refresh()
                with self._lock:
                    refused = not self._online and self._reason in ("auth", "forbidden")
                if refused:
                    break
                self._stop.wait(min(poll, max(0.05, deadline - self._now())))
            if refused and not self._stop.is_set():
                self._stop.wait(auth_backoff(refusals))
                refusals += 1

    def _rest_poll_for(self, attempt):
        """The REST poll period in a WebSocket back-off window: ``rest_poll``, stretched by
        REST_POLL_STRETCH once REST_STRETCH_AFTER WebSocket attempts in a row have failed."""
        return self.rest_poll * (REST_POLL_STRETCH if attempt >= REST_STRETCH_AFTER else 1)

    def _template_due(self):
        with self._lock:
            last = self._template_at
        return last is None or self._now() - last >= REGISTRY_POLL_SECONDS

    def _rest_refresh(self):
        """One REST poll while the WebSocket is down: the area template at most every
        REGISTRY_POLL_SECONDS, then the states. Area mode, or more than REST_EACH_MAX entities, reads
        them all with one GET /api/states (the request count does not grow with the area); a small
        single-light setup reads its few entities one by one."""
        try:
            if self.area_id and self._template_due():
                # Stamped only once the template answered (a resolution stamps it too): an offline
                # attempt (HA unreachable, a 5xx) raises before this, so the next poll tries again.
                resolved = self._resolve_rest()
                with self._lock:
                    self._template_at = self._now()
                if not resolved:
                    self._resolution_failed()
            changed = False
            watched = self._watched()
            if self.area_id or len(watched) > REST_EACH_MAX:
                states = self._rest("GET", "/api/states")
                if not isinstance(states, list):
                    raise HomeAssistantError("Home Assistant sent an unreadable answer", "failed")
                seen = set()
                for state in states:
                    if isinstance(state, dict):
                        seen.add(state.get("entity_id"))
                        changed |= self._store(state)
                with self._lock:
                    gone = [entity for entity in watched if entity not in seen and entity in self._states]
                    if self.snapshot_entity not in seen and self._snapshot:
                        gone.append(self.snapshot_entity)    # created here, lost to a restart
                for entity in set(gone):
                    changed |= self._drop(entity)
            else:
                read = missing = 0
                not_found = []
                for entity in watched:
                    try:
                        changed |= self._store(self._rest("GET", "/api/states/" + quote(entity)))
                        read += 1
                    except HomeAssistantError as exc:
                        if exc.outcome in ("auth", "forbidden", "offline"):
                            raise
                        missing += exc.outcome == "unavailable"
                        if exc.status == 404:
                            not_found.append(entity)
                if read:
                    # Home Assistant answers, so a 404 means the entity is gone (the snapshot scene
                    # after a restart): forget it. With nothing read it may still be loading.
                    for entity in not_found:
                        changed |= self._drop(entity)
                if watched and not read:
                    # Not one state came back (502 / 503 from a proxy, or 404 while Home Assistant
                    # is still loading): the lights cannot be driven, so they are not online.
                    reason = "unavailable" if missing == len(watched) else "offline"
                    self._set_status(False, reason, "")
                    return False
            self._set_status(True, "", "rest")
            if changed:
                self._notify()
            return True
        except HomeAssistantError as exc:
            self._set_status(False, exc.outcome if exc.outcome in ("auth", "forbidden", "offline") else "offline", "")
            return False

    def _connect(self):
        if self._ws_factory is None:
            self._ws_factory = _default_ws_factory()
            if self._ws_factory is None:
                return None
        return self._ws_factory(websocket_url(self.base_url), CONNECT_TIMEOUT)

    @staticmethod
    def _recv_json(ws):
        raw = ws.recv()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        if not raw:
            raise ConnectionError("closed")
        return json.loads(raw)

    def _session_ws(self):
        """One WebSocket session: 'auth', 'no_ws' (library missing), 'error' or 'ok' (closed after
        working). A fresh socket each time; the old one is closed and dropped."""
        ws = None
        initial = False                         # the first states arrived (the session worked)
        try:
            ws = self._connect()
            if ws is None:
                return "no_ws"
            hello = self._recv_json(ws)
            if hello.get("type") != "auth_required":
                return "error"
            with self._send_lock:
                ws.send(json.dumps({"type": "auth", "access_token": self._token}))
            reply = self._recv_json(ws)
            if reply.get("type") == "auth_invalid":
                return "auth"
            if reply.get("type") != "auth_ok":
                return "error"
            try:
                ws.settimeout(RECV_TIMEOUT)
            except Exception:
                pass
            requests = {}                       # id -> what it asked (only this thread touches it)

            def ask(purpose, message):
                requests[self._send_frame(ws, message)] = purpose

            def ask_registry():
                for name, kind in REGISTRY_LISTS:
                    ask("reg:" + name, {"type": kind})
            if self.area_id:
                ask_registry()
            ask("states", {"type": "get_states"})
            ask("sub:state_changed", {"type": "subscribe_events", "event_type": "state_changed"})
            if self.area_id:
                for event_type in REGISTRY_EVENTS:
                    ask("sub:" + event_type, {"type": "subscribe_events", "event_type": event_type})
            self._ws = ws
            self._transport = "ws"
            self._last_message = self._now()
            self._ping_sent = None
            self._registry_due = None
            registry = {}                       # the registry fetch in flight: name -> list | None
            poll_registry = False               # registry events refused: re-resolve on a timer
            initial = went_online = False
            while not self._stop.is_set():
                try:
                    message = self._recv_json(ws)
                except Exception as exc:
                    if type(exc).__name__ not in ("WebSocketTimeoutException", "timeout", "TimeoutError"):
                        raise
                    if not self._keepalive(ws):
                        return "ok" if initial else "error"
                    message = None
                if message is not None:
                    self._last_message = self._now()
                    self._ping_sent = None
                    kind = message.get("type")
                    ident = message.get("id")
                    if kind == "result" and ident in requests:
                        purpose = requests.pop(ident)
                        success = bool(message.get("success"))
                        code = self._error_code(message)
                        if purpose == "states":
                            if not success or not isinstance(message.get("result"), list):
                                _log.warning("Home Assistant refused get_states (%s)", code)
                                return "error"
                            if self._replace_states(message["result"]) and went_online:
                                self._notify()
                            initial = True
                        elif purpose == "sub:state_changed":
                            if not success:
                                _log.warning("Home Assistant refused the state_changed subscription (%s)", code)
                                return "error"
                        elif purpose.startswith("sub:"):
                            if not success and not poll_registry:
                                _log.warning("Home Assistant refused the %s subscription (%s); re-reading the "
                                             "area every %d s", purpose[4:], code, int(REGISTRY_POLL_SECONDS))
                                poll_registry = True
                                self._registry_due = self._now() + REGISTRY_POLL_SECONDS
                        elif purpose.startswith("reg:"):
                            if not success:
                                _log.warning("Home Assistant refused %s (%s)", purpose[4:], code)
                            result = message.get("result")
                            registry[purpose[4:]] = result if success and isinstance(result, list) else None
                            if len(registry) == len(REGISTRY_LISTS):
                                if not self._apply_registry(registry) and self._registry_due is None:
                                    self._registry_due = self._now() + REGISTRY_POLL_SECONDS
                                registry = {}
                        if initial and not went_online and (not self.area_id or self._resolved_once):
                            went_online = True
                            self._set_status(True, "", "ws")
                            self._notify()
                    elif kind == "event":
                        event = message.get("event") or {}
                        if event.get("event_type") in REGISTRY_EVENTS:
                            self._registry_due = self._now() + REGISTRY_DEBOUNCE     # debounced re-resolve
                        else:
                            data = event.get("data") or {}
                            new = data.get("new_state")
                            if isinstance(new, dict):
                                if self._store(new):
                                    self._notify()
                            elif new is None and valid_entity(data.get("entity_id")):
                                if self._drop(data["entity_id"]):
                                    self._notify()
                    elif kind in ("result", "pong"):
                        with self._lock:
                            pending = self._pending.pop(ident, None)
                        if pending is not None:
                            pending["result"] = message if kind == "result" else {"success": True}
                            pending["event"].set()
                due = self._registry_due
                if (self.area_id and due is not None and self._now() >= due
                        and not any(p.startswith("reg:") for p in requests.values())):
                    self._registry_due = self._now() + REGISTRY_POLL_SECONDS if poll_registry else None
                    ask_registry()
            return "ok" if initial else "error"
        except Exception as exc:
            network = is_network_error(exc)
            if not self._stop.is_set():
                name = type(exc).__name__
                if network or name in self._session_bugs:
                    _log.info("Home Assistant connection dropped (%s)", name)
                else:
                    # Not the network: a bug in the session (another Home Assistant's data shape),
                    # logged with its traceback once per type so the log can tell it from a drop.
                    self._session_bugs.add(name)
                    _log.warning("Home Assistant session failed (%s); reconnecting", name, exc_info=True)
            # Only a real drop of a healthy session starts the back-off over; a bug that fires after
            # the first states (it would fire again on every reconnect) keeps backing off.
            return "ok" if initial and network else "error"
        finally:
            if self._ws is ws:
                self._ws = None
            self._transport = "" if self._transport == "ws" else self._transport
            with self._lock:
                for pending in self._pending.values():
                    pending["event"].set()
                self._pending.clear()
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
            if not self._stop.is_set():
                with self._lock:
                    was = self._online
                if was:
                    self._set_status(False, "offline", "")

    @staticmethod
    def _error_code(message):
        error = message.get("error") if isinstance(message.get("error"), dict) else {}
        code = error.get("code")
        return code[:32] if isinstance(code, str) else "no code"

    def _keepalive(self, ws):
        """Between recv slices: a ping after PING_SECONDS of silence; False when its pong is late."""
        now = self._now()
        if self._ping_sent is not None:
            return now - self._ping_sent < PONG_TIMEOUT
        if now - self._last_message >= PING_SECONDS:
            try:
                self._send_frame(ws, {"type": "ping"})
            except Exception:
                return False
            self._ping_sent = now
        return True


def entity_lists(states):
    """{light, scene, script, automation: sorted [(entity_id, friendly name)]} from /api/states."""
    lists = {"light": [], "scene": [], "script": [], "automation": []}
    for state in states if isinstance(states, list) else ():
        entity = state.get("entity_id") if isinstance(state, dict) else None
        if not valid_entity(entity):
            continue
        domain = entity.split(".")[0]
        if domain not in lists or entity == "scene." + SNAPSHOT_ID:
            continue
        attributes = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
        name = attributes.get("friendly_name") if isinstance(attributes.get("friendly_name"), str) else ""
        lists[domain].append((entity, name[:60] or entity))
    for values in lists.values():
        values.sort(key=lambda pair: pair[1].casefold())
    return lists


def load_token(store):
    """The HA token from a CredentialStore (``ha_token``), or "" (never raises, never logged)."""
    try:
        value = (store.load() or {}).get(CREDENTIAL_KEY)
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def save_token(store, token):
    """Merge ``ha_token`` into the store, keeping every other credential (MusicKit). A real
    CredentialStore merges through its atomic ``update`` (one read-modify-write under STORE_LOCK,
    DD-RES-001); a plain load/save store (test stand-ins) falls back to load + save. The file need
    not be readable: ``update`` first sets an unreadable credentials.bin aside
    (``set_aside_if_unreadable``, DD-BUG-001), so the token is saved into a fresh file."""
    def change(current):
        current = dict(current or {})
        if token:
            current[CREDENTIAL_KEY] = token
        else:
            current.pop(CREDENTIAL_KEY, None)
        return current
    update = getattr(store, "update", None)
    if callable(update):
        update(change)
        return
    store.save(change(store.load()))


def build_adapter(config, store, **kwargs):
    """The live adapter from settings.json + the credential store, or None when not set up (the
    reason is logged, never a secret). The area (``ha_area``) wins over ``ha_light_entity``."""
    config = config if isinstance(config, dict) else {}
    url = config.get("ha_base_url") or ""
    area = config.get("ha_area") or ""
    light = config.get("ha_light_entity") or ""
    if not url:
        _log.info("Home Assistant lights not set up: no address in Settings")
        return None
    if not area and not light:
        _log.info("Home Assistant lights not set up: no area chosen in Settings")
        return None
    token = load_token(store)
    if not token:
        _log.info("Home Assistant lights not set up: no access token saved")
        return None
    try:
        adapter = HomeAssistantAdapter(url, token, light, config.get("ha_scenes") or (), area_id=area, **kwargs)
    except ValueError:
        _log.warning("Home Assistant lights not set up: the address in Settings is not valid")
        return None
    if not adapter.configured:
        _log.warning("Home Assistant lights not set up: the area / light id in Settings is not valid")
        return None
    _log.info("Home Assistant lights: %s", f"area {adapter.area_id}" if adapter.area_id
              else f"single light {adapter.light_entity}")
    return adapter


STATUS_KEYS = ("configured", "online", "reason", "detail", "transport", "area_id", "name", "count", "entities",
               "available", "unavailable_count", "on", "on_count", "bri", "kelvin", "min_k", "max_k", "supports_ct",
               "snapshot", "revision", "lights")


def lights_status(ha):
    """status.json ``lights``: the adapter's view (plain JSON, never the token or the address)."""
    if ha is None:
        return {"configured": False, "online": False, "reason": "not_configured"}
    try:
        state = ha.read_state()
    except Exception as exc:
        return {"configured": True, "online": False, "reason": "failed", "error": type(exc).__name__}
    state = state if isinstance(state, dict) else {}
    out = {key: state[key] for key in STATUS_KEYS if key in state}
    out["scenes"] = [scene.get("entity_id") for scene in state.get("scenes") or () if isinstance(scene, dict)]
    return out
