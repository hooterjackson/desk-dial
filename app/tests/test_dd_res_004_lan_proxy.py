"""DD-RES-004: the Home Assistant LAN clients ignore a system / environment proxy.

A proxy from HTTP(S)_PROXY (or the Windows registry) cannot reach a Home Assistant on the owner's
own network, so the REST session and the WebSocket bypass it for a LAN host; a public address keeps
the proxy. Offline: no request is sent, no socket is opened (create_connection is a recorder).
"""
import ipaddress
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import home_assistant as ha_module  # noqa: E402
from control_center.home_assistant import HomeAssistantAdapter, is_lan_host  # noqa: E402

PROXY_ENV = {"HTTP_PROXY": "http://proxy.example.com:3128", "HTTPS_PROXY": "http://proxy.example.com:3128",
             "http_proxy": "http://proxy.example.com:3128", "https_proxy": "http://proxy.example.com:3128",
             "NO_PROXY": "", "no_proxy": ""}


def nth(network, index):
    return str(ipaddress.ip_network(network)[index])


class LanHostTests(unittest.TestCase):
    def test_lan_hosts(self):
        for host in ("homeassistant.local", "homeassistant", "localhost", "ha.home.arpa", "ha.lan",
                     nth("10.0.0.0/8", 5), nth("172.16.0.0/12", 9), nth("192.168.0.0/16", 20),
                     nth("169.254.0.0/16", 3), nth("100.64.0.0/10", 7), nth("fe80::/64", 1), "[%s]" % nth("fd00::/8", 2)):
            self.assertTrue(is_lan_host(host), host)
        for host in ("ha.example.com", nth("1.0.0.0/8", 1), "", None):
            self.assertFalse(is_lan_host(host), host)


class LanClientsIgnoreSystemProxy(unittest.TestCase):
    def test_lan_clients_ignore_system_proxy(self):
        url = "http://homeassistant.local:8123"
        with patch.dict(os.environ, PROXY_ENV):
            adapter = HomeAssistantAdapter(url, "t0k", "light.den")
            session = adapter._session()
            self.addCleanup(session.close)
            settings = session.merge_environment_settings(url + "/api/states", {}, None, None, None)
            self.assertEqual(settings["proxies"], {}, "a LAN Home Assistant never goes through the proxy")
            public = ha_module._default_http("https://ha.example.com")
            self.addCleanup(public.close)
            settings = public.merge_environment_settings("https://ha.example.com/api/", {}, None, None, None)
            self.assertIn("https", settings["proxies"], "a public address keeps the system proxy")

    def test_the_websocket_bypasses_the_proxy_for_a_lan_host(self):
        import websocket
        from websocket import _url
        calls = []
        with patch.object(websocket, "create_connection", lambda url, **kw: calls.append((url, kw)) or "ws"), \
                patch.dict(os.environ, PROXY_ENV):
            factory = ha_module._default_ws_factory()
            self.assertEqual(factory("ws://homeassistant.local:8123/api/websocket", 5.0), "ws")
            factory("wss://ha.example.com/api/websocket", 5.0)
            lan, public = calls
            self.assertEqual(lan[1]["http_no_proxy"], ["homeassistant.local"])
            self.assertEqual(_url.get_proxy_info("homeassistant.local", False, no_proxy=lan[1]["http_no_proxy"]),
                             (None, 0, None))
            self.assertNotIn("http_no_proxy", public[1])
            self.assertEqual(public[1]["timeout"], 5.0)


if __name__ == "__main__":
    unittest.main()
