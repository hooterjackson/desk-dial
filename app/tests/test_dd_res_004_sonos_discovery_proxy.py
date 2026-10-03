"""DD-RES-004 follow-up: Sonos discovery's in-call topology SOAP query must bypass a system / env proxy."""
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


class SonosDiscoveryProxyTest(unittest.TestCase):
    def test_discovery_soap_to_unknown_lan_speaker_is_not_proxied(self):
        seen = {}

        def fake_discover(timeout, include_invisible):
            # soco.discover queries the answering speaker's topology here, before returning any IP
            seen["proxies"] = requests.utils.get_environ_proxies("http://172.20.3.9:1400/ZoneGroupTopology/Control")
            return []

        with mock.patch.dict(os.environ, _clean_env(), clear=True):
            os.environ["NO_PROXY"] = "intranet.example"
            adapter = sonos.SonosAdapter("192.168.50.21", soco_factory=lambda host: object(), discover_fn=fake_discover)
            self.assertEqual(adapter.discover(), [])
            self.assertEqual(seen["proxies"], {})
            self.assertIn("intranet.example", os.environ["NO_PROXY"])
            # public hosts keep the proxy
            self.assertTrue(requests.utils.get_environ_proxies("http://8.8.8.8/x"))
            self.assertTrue(requests.utils.get_environ_proxies("https://api.music.apple.com/v1"))

    def test_lan_ranges_added_once(self):
        with mock.patch.dict(os.environ, _clean_env(), clear=True):
            sonos.bypass_proxy_for_lan_ranges()
            sonos.bypass_proxy_for_lan_ranges()
            self.assertEqual(os.environ["NO_PROXY"].split(",").count("192.168.0.0/16"), 1)
            self.assertEqual(os.environ["NO_PROXY"], os.environ["no_proxy"])


if __name__ == "__main__":
    unittest.main()
