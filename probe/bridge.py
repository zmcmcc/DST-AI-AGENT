"""Minimal loopback receiver for the DST P0 probe."""

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from survival import SurvivalPlanner


lock = threading.Lock()
bridge_epoch = uuid.uuid4().hex
MOD_VERSION = "0.20.0"
autostart_guids = set()
last_guid = None
last_seq = None
last_seen_at = None
next_command_id = 0
last_action_id = None
pending_command = None
pending_deadline = None
latest_observation = None
HARVEST_PREFABS = {"grass", "sapling", "berrybush", "berrybush2", "berrybush_juicy"}
AUTO_PICK_LIMIT = 5
auto_enabled = False
auto_guid = None
auto_action_id = None
auto_target_guid = None
auto_completed = 0
auto_failed = 0
auto_avoid_until = {}
auto_reason = "off"
survival = SurvivalPlanner()


def auto_status():
    return {
        "enabled": auto_enabled,
        "guid": auto_guid,
        "completed": auto_completed,
        "failed": auto_failed,
        "limit": AUTO_PICK_LIMIT,
        "action_id": auto_action_id,
        "reason": auto_reason,
    }


def select_auto_target(observation):
    if observation.get("phase") != "day":
        return None, "waiting_for_day"
    vitals = observation.get("vitals") or {}
    health = vitals.get("health") or {}
    hunger = vitals.get("hunger") or {}
    if not isinstance(health.get("current"), (int, float)) or health["current"] < 75:
        return None, "health_low_or_unknown"
    if not isinstance(hunger.get("current"), (int, float)) or hunger["current"] < 75:
        return None, "hunger_low_or_unknown"
    nearby = observation.get("local_entities") or []
    if observation.get("visible_frog_within_8") is not False:
        return None, "frog_nearby_or_unknown"
    now = time.monotonic()
    target = next((entity for entity in nearby
                   if entity.get("prefab") in HARVEST_PREFABS
                   and entity.get("ready") is True
                   and auto_avoid_until.get(entity.get("guid"), 0) <= now
                   and entity["dx"] ** 2 + entity["dz"] ** 2 <= 64), None)
    return (target, "target_found") if target is not None else (None, "no_ready_target")


class ProbeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        if self.path != "/probe":
            super().log_message(format, *args)

    def do_GET(self):
        if self.path == "/survival/status":
            with lock:
                status = survival.status()
            self.send_json(status)
            return
        if self.path == "/auto/status":
            with lock:
                status = auto_status()
            self.send_json(status)
            return
        if self.path != "/latest":
            self.send_error(404)
            return
        with lock:
            observation = latest_observation
            age_seconds = time.monotonic() - last_seen_at if last_seen_at is not None else None
        if observation is None:
            self.send_error(404)
            return
        self.send_json({"age_seconds": age_seconds, "observation": observation})

    def do_POST(self):
        global last_guid, last_seq, last_seen_at, next_command_id, last_action_id
        global pending_command, pending_deadline, latest_observation
        global auto_enabled, auto_guid, auto_action_id, auto_target_guid
        global auto_completed, auto_failed, auto_reason

        if self.path == "/survival/start":
            with lock:
                if (last_guid is None or last_seen_at is None
                        or time.monotonic() - last_seen_at > 5):
                    self.send_error(409, "no recent Wilson observation")
                    return
                if auto_enabled or pending_command is not None or survival.enabled:
                    self.send_error(409, "another mode or command is running")
                    return
                observation = latest_observation or {}
                if ((observation.get("execution") or {}).get("status") == "started"
                        or (observation.get("movement") or {}).get("status") == "started"
                        or (observation.get("utility") or {}).get("status") == "started"):
                    self.send_error(409, "action already running")
                    return
                try:
                    survival.start(observation)
                except ValueError as error:
                    self.send_error(409, str(error))
                    return
                autostart_guids.add(last_guid)
                status = survival.status()
            self.send_json(status)
            print(f"survival started guid={last_guid}", flush=True)
            return

        if self.path == "/survival/stop":
            with lock:
                running_id = survival.action_id if survival.enabled else None
                survival.stop()
                if last_guid is not None:
                    autostart_guids.add(last_guid)
                if (last_guid is not None and last_seen_at is not None
                        and time.monotonic() - last_seen_at <= 5):
                    next_command_id += 1
                    pending_command = {
                        "epoch": bridge_epoch, "id": next_command_id,
                        "type": "STOP", "guid": last_guid,
                        "target_id": running_id if running_id is not None else -1,
                        "say": "先停下来",
                    }
                    pending_deadline = time.monotonic() + 5
                status = survival.status()
            self.send_json(status)
            print("survival stopped", flush=True)
            return

        if self.path == "/auto/start":
            with lock:
                if last_guid is None or last_seen_at is None or time.monotonic() - last_seen_at > 5:
                    self.send_error(409, "no recent Wilson observation")
                    return
                if pending_command is not None or auto_action_id is not None or survival.enabled:
                    self.send_error(409, "action already pending")
                    return
                observation = latest_observation or {}
                if (observation.get("execution") or {}).get("status") == "started" or (observation.get("movement") or {}).get("status") == "started":
                    self.send_error(409, "action already running")
                    return
                auto_enabled = True
                auto_guid = last_guid
                auto_completed = 0
                auto_failed = 0
                auto_avoid_until.clear()
                auto_reason = "waiting_for_next_observation"
                status = auto_status()
            self.send_json(status)
            print(f"auto started guid={auto_guid} limit={AUTO_PICK_LIMIT}", flush=True)
            return

        if self.path == "/auto/stop":
            with lock:
                auto_enabled = False
                auto_reason = "stopped"
                if pending_command is not None and pending_command["id"] == auto_action_id:
                    pending_command = None
                    pending_deadline = None
                    auto_action_id = None
                    auto_target_guid = None
                status = auto_status()
            self.send_json(status)
            print("auto stopped", flush=True)
            return

        if self.path == "/stop":
            with lock:
                if last_guid is None or last_action_id is None or last_seen_at is None or time.monotonic() - last_seen_at > 5:
                    self.send_error(409, "no recent action to stop")
                    return
                next_command_id += 1
                pending_command = {
                    "epoch": bridge_epoch,
                    "id": next_command_id,
                    "type": "STOP",
                    "guid": last_guid,
                    "target_id": last_action_id,
                }
                pending_deadline = time.monotonic() + 5
                armed_command = pending_command.copy()
            self.send_json({"armed": armed_command})
            print(f"armed STOP id={armed_command['id']} target_id={armed_command['target_id']}", flush=True)
            return

        if self.path in ("/arm-move", "/arm-move-long", "/arm-move-target", "/arm-pick"):
            with lock:
                if (last_guid is None or last_seen_at is None
                        or time.monotonic() - last_seen_at > 5
                        or pending_command is not None or survival.enabled):
                    self.send_error(409)
                    return
                observation = latest_observation or {}
                execution = observation.get("execution") or {}
                movement = observation.get("movement") or {}
                if execution.get("status") == "started" or movement.get("status") == "started":
                    self.send_error(409, "action already running")
                    return
                target = None
                if self.path in ("/arm-move-long", "/arm-move-target"):
                    nearby = observation.get("local_entities") or []
                    frogs = (entity for entity in nearby if entity.get("prefab") == "frog")
                    if observation.get("visible_frog_within_8") is not False or any(entity["dx"] ** 2 + entity["dz"] ** 2 <= 64 for entity in frogs):
                        self.send_error(409, "frog nearby")
                        return
                if self.path == "/arm-move-target":
                    nearby = observation.get("local_entities") or []
                    target = next((entity for entity in nearby
                                   if entity.get("prefab") in HARVEST_PREFABS
                                   and entity.get("ready") is True
                                   and 9 < entity["dx"] ** 2 + entity["dz"] ** 2 <= 64), None)
                    if target is None:
                        self.send_error(409, "no ready target between 3 and 8 units")
                        return
                if self.path == "/arm-pick":
                    nearby = observation.get("local_entities") or []
                    frogs = (entity for entity in nearby if entity.get("prefab") == "frog")
                    if any(entity["dx"] ** 2 + entity["dz"] ** 2 <= 36 for entity in frogs):
                        self.send_error(409, "frog nearby")
                        return
                    target = next((entity for entity in nearby
                                   if entity.get("prefab") in HARVEST_PREFABS
                                   and entity.get("ready") is True
                                   and entity["dx"] ** 2 + entity["dz"] ** 2 <= 9), None)
                    if target is None:
                        self.send_error(409, "no ready harvest target within 3 units")
                        return
                next_command_id += 1
                last_action_id = next_command_id
                pending_command = {
                    "epoch": bridge_epoch,
                    "id": next_command_id,
                    "type": ("MOVE_TO_TARGET" if self.path == "/arm-move-target" else
                             "PICK_TARGET" if target is not None else
                             "MOVE_EAST_LONG" if self.path == "/arm-move-long" else
                             "MOVE_EAST_SHORT"),
                    "guid": last_guid,
                }
                if target is not None:
                    pending_command["target_guid"] = target["guid"]
                    pending_command["target_prefab"] = target["prefab"]
                pending_deadline = time.monotonic() + 5
                armed_command = pending_command.copy()
                response_data = {"armed": armed_command}
            self.send_json(response_data)
            print(f"armed {armed_command['type']} id={armed_command['id']} guid={armed_command['guid']}", flush=True)
            return

        if self.path != "/probe":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length > 20000:
            self.send_error(413)
            return

        try:
            message = json.loads(self.rfile.read(length))
            if message.get("probe") != "wilson-p0" or not isinstance(message.get("seq"), int):
                raise ValueError("invalid probe")
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_error(400)
            return

        with lock:
            new_guid = message.get("guid")
            new_session = (last_guid == new_guid and last_seq is not None
                           and last_seq > 3 and message["seq"] <= 3)
            if new_session:
                autostart_guids.discard(new_guid)
            if last_guid != new_guid:
                last_action_id = None
                if pending_command is not None and pending_command["guid"] != new_guid:
                    pending_command = None
                    pending_deadline = None
                if auto_enabled and auto_guid != new_guid:
                    auto_enabled = False
                    auto_action_id = None
                    auto_target_guid = None
                    auto_reason = "player_changed"
            if new_session or last_guid != new_guid:
                survival.__init__()
                if pending_command is not None:
                    pending_command = None
                    pending_deadline = None
            last_guid = new_guid
            last_seq = message["seq"]
            last_seen_at = time.monotonic()
            latest_observation = message
            command_ack = message.get("command_ack")
            if pending_command is not None and time.monotonic() > pending_deadline:
                print(f"command id={pending_command['id']} expired", flush=True)
                survival.command_expired(pending_command["id"])
                if pending_command["id"] == auto_action_id:
                    auto_failed += 1
                    auto_avoid_until[auto_target_guid] = time.monotonic() + 20
                    auto_action_id = None
                    auto_target_guid = None
                pending_command = None
                pending_deadline = None
            if pending_command is not None and command_ack is not None:
                if (command_ack.get("epoch") == pending_command["epoch"]
                        and command_ack.get("id") == pending_command["id"]
                        and last_guid == pending_command["guid"]):
                    print(f"command id={pending_command['id']} status={command_ack.get('status')}", flush=True)
                    pending_command = None
                    pending_deadline = None
            execution = message.get("execution") or {}
            if auto_action_id is not None and execution.get("epoch") == bridge_epoch and execution.get("id") == auto_action_id:
                status = execution.get("status")
                if status == "completed" and execution.get("inventory_delta", 0) > 0:
                    auto_completed += 1
                    print(f"auto pick completed id={auto_action_id} target={auto_target_guid} total={auto_completed}", flush=True)
                    auto_action_id = None
                    auto_target_guid = None
                elif status not in ("received", "started", None):
                    auto_failed += 1
                    auto_avoid_until[auto_target_guid] = time.monotonic() + 20
                    print(f"auto pick failed id={auto_action_id} status={status}", flush=True)
                    auto_action_id = None
                    auto_target_guid = None
            if auto_enabled and auto_completed >= AUTO_PICK_LIMIT:
                auto_enabled = False
                auto_reason = "pick_limit_reached"
            if auto_enabled and pending_command is None and auto_action_id is None:
                if (execution.get("status") == "started"
                        or (message.get("movement") or {}).get("status") == "started"):
                    auto_reason = "action_running"
                else:
                    target, auto_reason = select_auto_target(message)
                    if target is not None:
                        next_command_id += 1
                        last_action_id = next_command_id
                        pending_command = {
                            "epoch": bridge_epoch,
                            "id": next_command_id,
                            "type": "PICK_TARGET",
                            "guid": last_guid,
                            "target_guid": target["guid"],
                            "target_prefab": target["prefab"],
                            "auto": True,
                        }
                        pending_deadline = time.monotonic() + 5
                        auto_action_id = next_command_id
                        auto_target_guid = target["guid"]
                        auto_reason = "picking"
                        print(f"auto pick armed id={auto_action_id} target={target['prefab']}:{auto_target_guid}", flush=True)
                    else:
                        auto_enabled = False
                        print(f"auto ended reason={auto_reason} completed={auto_completed}", flush=True)
            if (message.get("mod_version") == MOD_VERSION
                    and new_guid not in autostart_guids
                    and not survival.enabled and not auto_enabled
                    and pending_command is None
                    and all((message.get(name) or {}).get("status") != "started"
                            for name in ("execution", "movement", "utility"))):
                try:
                    survival.start(message)
                    autostart_guids.add(new_guid)
                    print(f"survival auto-started guid={new_guid}", flush=True)
                except ValueError as error:
                    print(f"survival auto-start unavailable: {error}", flush=True)
            choice = survival.on_observation(message, bridge_epoch)
            if choice is not None and (pending_command is None or choice["type"] == "STOP"):
                next_command_id += 1
                command = {
                    "epoch": bridge_epoch,
                    "id": next_command_id,
                    "guid": last_guid,
                    **choice,
                }
                pending_command = command
                pending_deadline = time.monotonic() + 5
                if choice["type"] != "STOP":
                    last_action_id = next_command_id
                survival.record_command(next_command_id, choice)
                print(f"survival armed id={next_command_id} type={choice['type']} goal={choice['goal']}", flush=True)
            for event in survival.events:
                print(event, flush=True)
            survival.events.clear()
            command = pending_command if pending_command is not None and last_guid == pending_command["guid"] else None

        self.send_json({"probe": "wilson-p0", "seq": message["seq"], "ack": True, "command": command})
        if message["seq"] % 10 == 1:
            inventory = message.get("inventory") or {}
            vitals = message.get("vitals") or {}
            movement = message.get("movement") or {}
            hunger = (vitals.get("hunger") or {}).get("current")
            sensed = {}
            for entity in message.get("local_entities") or []:
                prefab = entity.get("prefab")
                sensed[prefab] = sensed.get(prefab, 0) + 1
            sensed_text = ",".join(f"{key}:{sensed[key]}" for key in sorted(sensed)) or "none"
            print(
                f"seq={message['seq']} prefab={message.get('prefab')} "
                f"guid={last_guid} cycles={message.get('cycles')} "
                f"phase={message.get('phase')} x={message.get('x')} z={message.get('z')} "
                f"hunger={hunger} hand={inventory.get('hand')} "
                f"in_light={message.get('in_light')} goal={survival.goal} "
                f"move_progress={movement.get('progress')} "
                f"sense_radius={message.get('local_radius')} "
                f"sensed={sensed_text} "
                f"truncated={message.get('local_entities_truncated')}",
                flush=True,
            )

    def send_json(self, value):
        response = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8765), ProbeHandler)
    print("DST P0 probe listening on http://127.0.0.1:8765", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
