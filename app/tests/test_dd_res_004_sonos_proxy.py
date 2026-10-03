"""DD-RES-004: soco's SOAP calls to LAN speakers must not go through a system / env proxy."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import sonos  # noqa: E402

PROXY_ENV = {"HTTP_PROXY": "http://proxy.example.invalid:8080",
             "HTTPS_PROXY": "http://proxy.example.invalid:8080"}


def _clean_env():
    env = {k: v for k, v in os.environ.items() if k.lower() not in ("no_proxy", "http_proxy", "https_proxy", "all_proxy")}
    env.update(PROXY_ENV)
    return env


class _Zone:
    def __init__(self, ip):
        self.ip_address = ip
        self.uid = "RINCON_" + ip.replace(".", "")


class SonosProxyBypassTest(unittest.TestCase):
    def test_speaker_ip_resolves_no_proxy_after_adapter_start(self):
        with mock.patch.dict(os.environ, _clean_env(), clear=True):
            url = "http://192.168.50.21:1400/MediaRenderer/AVTransport/Control"
            self.assertTrue(requests.utils.get_environ_proxies(url))   # proxied before
            adapter = sonos.SonosAdapter("192.168.50.21", soco_factory=lambda host: object())
            adapter._dependencies()
            self.assertEqual(requests.utils.get_environ_proxies(url), {})

    def test_coordinators_added_existing_value_kept_public_hosts_never(self):
        with mock.patch.dict(os.environ, _clean_env(), clear=True):
            os.environ["NO_PROXY"] = "intranet.example"
            sonos.bypass_proxy_for("10.0.0.7", "10.0.0.7", "speaker.example.com", None)
            value = os.environ["NO_PROXY"]
            self.assertIn("intranet.example", value)
            self.assertEqual(value.split(",").count("10.0.0.7"), 1)
            self.assertNotIn("speaker.example.com", value)
            self.assertEqual(requests.utils.get_environ_proxies("http://10.0.0.7:1400/x"), {})
            self.assertTrue(requests.utils.get_environ_proxies("http://speaker.example.com:1400/x"))

    def test_context_bypasses_every_zone(self):
        zones = [_Zone("192.168.50.21"), _Zone("192.168.50.22")]
        speaker = mock.Mock()
        speaker.all_zones = zones
        with mock.patch.dict(os.environ, _clean_env(), clear=True):
            adapter = sonos.SonosAdapter("192.168.50.21", room_uid="missing", soco_factory=lambda host: speaker)
            with self.assertRaises(sonos.SonosError):
                adapter._context()
            self.assertEqual(requests.utils.get_environ_proxies("http://192.168.50.22:1400/x"), {})


if __name__ == "__main__":
    unittest.main()
