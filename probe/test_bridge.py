import json
import re
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import bridge
from test_survival import observation


class ModVersionTests(unittest.TestCase):
    def test_game_report_matches_bridge_version(self):
        mod = Path(__file__).with_name("wilson_p0_probe")
        main = (mod / "modmain.lua").read_text()
        info = (mod / "modinfo.lua").read_text()
        self.assertEqual(re.search(r'mod_version = "([^"]+)"', main).group(1),
                         bridge.MOD_VERSION)
        self.assertEqual(re.search(r'version = "([^"]+)"', info).group(1),
                         bridge.MOD_VERSION)


class BridgeSurvivalTests(unittest.TestCase):
    def setUp(self):
        bridge.last_guid = None
        bridge.last_seq = None
        bridge.last_seen_at = None
        bridge.next_command_id = 0
        bridge.last_action_id = None
        bridge.pending_command = None
        bridge.pending_deadline = None
        bridge.latest_observation = None
        bridge.auto_enabled = False
        bridge.native_benchmark.update(enabled=False, guid=None, running_id=None,
                                       target_guid=None, attempts=[], avoid={}, reason="off")
        bridge.survival = bridge.SurvivalPlanner()
        bridge.autostart_guids.clear()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), bridge.ProbeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else b""
        request = Request(self.url + path, data=data, method="POST")
        with urlopen(request, timeout=2) as response:
            return json.load(response)

    def test_start_deliver_wait_and_advance(self):
        first = {"probe": "wilson-p0", **observation(seq=1)}
        self.assertIsNone(self.request("/probe", first)["command"])
        self.assertTrue(self.request("/survival/start")["enabled"])
        second = {"probe": "wilson-p0", **observation(seq=2)}
        command = self.request("/probe", second)["command"]
        self.assertEqual(command["type"], "MOVE_TO_POINT")
        started = {"probe": "wilson-p0", **observation(seq=3,
            command_ack={"epoch": command["epoch"], "id": command["id"], "status": "started"},
            movement={"epoch": command["epoch"], "id": command["id"], "status": "started"})}
        self.assertIsNone(self.request("/probe", started)["command"])
        arrived = {"probe": "wilson-p0", **observation(seq=4, x=6,
            movement={"epoch": command["epoch"], "id": command["id"], "status": "arrived"})}
        next_command = self.request("/probe", arrived)["command"]
        self.assertEqual(next_command["type"], "MOVE_TO_POINT")
        self.assertNotEqual(next_command["id"], command["id"])
        self.assertEqual(bridge.survival.completed, 1)

    def test_spoken_intent_is_sent_as_utf8(self):
        self.request("/probe", {"probe": "wilson-p0", **observation(seq=1)})
        self.request("/survival/start")
        request = Request(self.url + "/probe",
                          data=json.dumps({"probe": "wilson-p0", **observation(seq=2)}).encode(),
                          method="POST")
        with urlopen(request, timeout=2) as response:
            raw = response.read()
        self.assertIn("附近没找到草".encode("utf-8"), raw)
        self.assertNotIn(b"\\u9644", raw)

    def test_stop_while_idle_reaches_game_mod(self):
        self.request("/probe", {"probe": "wilson-p0", **observation(seq=1)})
        self.request("/survival/start")
        stopped = self.request("/survival/stop")
        self.assertFalse(stopped["enabled"])
        command = self.request("/probe", {"probe": "wilson-p0", **observation(seq=2)})["command"]
        self.assertEqual(command["type"], "STOP")
        self.assertEqual(command["target_id"], -1)

    def test_matching_mod_starts_autonomously_once_per_world(self):
        first = {"probe": "wilson-p0", "mod_version": bridge.MOD_VERSION,
                 **observation(seq=1)}
        command = self.request("/probe", first)["command"]
        self.assertEqual(command["type"], "MOVE_TO_POINT")
        self.assertTrue(bridge.survival.enabled)
        self.request("/survival/stop")
        stopped = {"probe": "wilson-p0", "mod_version": bridge.MOD_VERSION,
                   **observation(seq=2)}
        self.request("/probe", stopped)
        self.assertFalse(bridge.survival.enabled)
        self.request("/probe", {"probe": "wilson-p0",
                                "mod_version": bridge.MOD_VERSION,
                                **observation(seq=4)})

        reopened = {"probe": "wilson-p0", "mod_version": bridge.MOD_VERSION,
                    **observation(seq=1)}
        self.request("/probe", reopened)
        self.assertTrue(bridge.survival.enabled)

    def test_native_benchmark_arms_distant_grass_and_records_terminal(self):
        grass = {"guid": 501, "prefab": "grass", "kind": "harvest",
                 "ready": True, "dx": 9, "dz": 0, "marsh_steps": 0}
        inventory = {"counts": {}, "free_slots": 10, "hand": None}
        self.request("/probe", {"probe": "wilson-p0", **observation(seq=1,
            local_entities=[grass], inventory=inventory)})
        self.assertTrue(self.request("/native-benchmark/start")["enabled"])
        command = self.request("/probe", {"probe": "wilson-p0", **observation(
            seq=2, local_entities=[grass], inventory=inventory)})["command"]
        self.assertEqual(command["type"], "PICK_TARGET")
        self.assertTrue(command["native_probe"])
        self.assertEqual(command["target_guid"], 501)
        self.request("/probe", {"probe": "wilson-p0", **observation(seq=3,
            inventory=inventory, local_entities=[],
            execution={"epoch": command["epoch"], "id": command["id"],
                       "status": "completed", "inventory_delta": 1,
                       "native_action_started_at": 3.0, "terminal_at": 5.0})})
        self.assertEqual(bridge.native_benchmark["attempts"][0]["status"], "completed")
        self.assertEqual(bridge.native_benchmark["attempts"][0]["terminal_at"], 5.0)


if __name__ == "__main__":
    unittest.main()
