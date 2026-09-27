"""Rule-based first-night work package for the Wilson bridge.

The planner only chooses from the latest observed inventory, visible resources,
and short walkable frontier points. The game still validates every command.
"""

import time

from item_catalog import ITEM_CATALOG, loose_item_offer


TERMINAL_SUCCESS = {
    "PICK_TARGET": {"completed"},
    "PICKUP_TARGET": {"completed"},
    "LOOT_CLUSTER": {"completed"},
    "GATHER_PATCH": {"completed"},
    "COLLECT_AREA": {"completed"},
    "FELL_TREE": {"completed"},
    "MOVE_TO_TARGET": {"arrived"},
    "MOVE_TO_POINT": {"arrived"},
    "EAT_BERRIES": {"completed"},
    "EAT_FOOD": {"completed"},
    "CRAFT_TORCH": {"completed"},
    "CRAFT_AXE": {"completed"},
    "BUILD_CAMPFIRE": {"completed"},
    "COOK_AT": {"completed"},
    "ADD_FUEL": {"completed"},
    "EQUIP_TORCH": {"completed"},
    "EQUIP_AXE": {"completed"},
    "UNEQUIP_TORCH": {"completed"},
}
RESOURCE_NAMES = {"grass": "草", "sapling": "树枝", "food": "食物",
                  "flint": "燧石", "morsel": "小肉", "wood": "木头",
                  "stone": "石头", "gold": "金块"}
RESOURCE_PREFABS = {
    "grass": {"grass", "cutgrass"},
    "sapling": {"sapling", "twigs"},
    "food": {"berrybush", "berrybush2", "berrybush_juicy", "berries", "berries_juicy",
             "carrot_planted", "carrot", "seeds"},
    "flint": {"flint"},
    "morsel": {"smallmeat"},
    "wood": {"log", "evergreen", "evergreen_sparse", "deciduoustree"},
    "stone": {"rocks"},
    "gold": {"goldnugget"},
}
HARVEST_PREFABS = {"grass", "sapling", "berrybush", "berrybush2", "berrybush_juicy",
                   "carrot_planted"}
CHOP_PREFABS = {"evergreen", "evergreen_sparse", "deciduoustree"}
FOOD_HUNGER_FALLBACK = {"berries": 9.375, "berries_juicy": 12.5,
                        "carrot": 12.5, "seeds": 4.6875,
                        "berries_cooked": 12.5,
                        "berries_juicy_cooked": 18.75,
                        "carrot_cooked": 12.5,
                        "cookedsmallmeat": 12.5}
TORCH_SECONDS_FALLBACK = 75
LIGHT_MARGIN_SECONDS = 30
EQUIP_LEAD_SECONDS = 5
REPLACE_MARGIN_SECONDS = 10


class SurvivalPlanner:
    def __init__(self):
        self.enabled = False
        self.guid = None
        self.reason = "off"
        self.goal = None
        self.action_id = None
        self.action_type = None
        self.action_target = None
        self.action_point = None
        self.action_escape = False
        self.action_started_at = None
        self.stop_requested = False
        self.completed = 0
        self.failed = 0
        self.picked_items = 0
        self.saw_night = False
        self.night_light_samples = 0
        self.night_dark_samples = 0
        self.first_night_result = None
        self.visits = {}
        self.seen_cells = set()
        self.blocked_cells = set()
        self.seen_resources = set()
        self.avoid_targets = {}
        self.hazard_zones = {}
        self.retry_after = {}
        self.heading = None
        self.last_position = None
        self.last_cell = None
        self.eating_batch = False
        self.food_refill_active = False
        self.material_refill = {"grass": False, "sapling": False}
        self.events = []
        self.decision_seq = 0
        self.behavior_seq = 0
        self.collect_area = None
        self.action_behavior_id = None
        self.safety_mode = "NORMAL"
        self.safety_clear_since = None
        self.last_health = None
        self.recent_hit_until = 0

    def status(self):
        return {
            "enabled": self.enabled,
            "guid": self.guid,
            "goal": self.goal,
            "reason": self.reason,
            "safety_mode": self.safety_mode,
            "action_id": self.action_id,
            "action_type": self.action_type,
            "behavior_id": self.action_behavior_id or (self.collect_area or {}).get("id"),
            "collect_area": self.collect_area,
            "completed": self.completed,
            "failed": self.failed,
            "picked_items": self.picked_items,
            "explored_cells": len(self.visits),
            "observed_cells": len(self.seen_cells),
            "resources_discovered": len(self.seen_resources),
            "night_light_samples": self.night_light_samples,
            "night_dark_samples": self.night_dark_samples,
            "first_night_result": self.first_night_result,
        }

    def start(self, observation):
        if (not isinstance(observation.get("inventory"), dict)
                or not isinstance(observation.get("frontier"), list)
                or not isinstance(observation.get("visible_threat_within_8"), bool)):
            raise ValueError("game mod has not loaded the survival observation fields")
        self.__init__()
        self.enabled = True
        self.guid = observation["guid"]
        self.reason = "started"
        self._remember(observation)
        self._record_milestone(observation)

    def stop(self):
        self.enabled = False
        self.reason = "stopped"
        self._end_area("STOPPED")

    def command_expired(self, command_id):
        if self.action_id == command_id:
            self._finish(False, "command_expired")

    def record_command(self, command_id, choice):
        if choice["type"] == "STOP":
            self.stop_requested = True
            return
        choice.setdefault("chosen_at", time.time())
        self.action_id = command_id
        self.action_type = choice["type"]
        self.action_target = choice.get("target_guid")
        self.action_point = (choice["x"], choice["z"]) if choice["type"] == "MOVE_TO_POINT" else None
        self.action_escape = choice.get("escape") is True
        self.action_behavior_id = choice.get("behavior_id")
        self.action_started_at = time.monotonic()
        self.stop_requested = False
        self.goal = choice["goal"]
        self.reason = "action_running"
        self.events.append(f"goal={self.goal} action={self.action_type} id={command_id} say={choice['say']}")

    def on_observation(self, observation, epoch):
        if not self.enabled:
            return None
        if observation.get("guid") != self.guid:
            self.enabled = False
            self.reason = "player_changed"
            self.events.append("survival ended: player changed")
            return None
        self._remember(observation)
        self._record_milestone(observation)
        if not self.enabled:
            return None

        if self.action_id is not None:
            report_name = ("movement" if self.action_type.startswith("MOVE_") else
                           "execution" if self.action_type in ("PICK_TARGET", "PICKUP_TARGET",
                                                               "FELL_TREE", "LOOT_CLUSTER",
                                                               "GATHER_PATCH", "COLLECT_AREA") else "utility")
            report = observation.get(report_name) or {}
            ack = observation.get("command_ack") or {}
            status = None
            if report.get("epoch") == epoch and report.get("id") == self.action_id:
                status = report.get("status")
            elif ack.get("epoch") == epoch and ack.get("id") == self.action_id:
                status = ack.get("status")
            if status not in (None, "received", "started"):
                success = status in TERMINAL_SUCCESS[self.action_type]
                if self.action_type in ("CRAFT_TORCH", "CRAFT_AXE") and status == "uncertain":
                    inventory = observation.get("inventory") or {}
                    prefab = "torch" if self.action_type == "CRAFT_TORCH" else "axe"
                    success = (inventory.get("hand") == prefab
                               or (inventory.get("counts") or {}).get(prefab, 0) > 0)
                if self.action_type in ("PICK_TARGET", "PICKUP_TARGET") and report.get("inventory_delta", 0) <= 0:
                    success = False
                if self.action_type == "FELL_TREE" and (
                        report.get("work_delta", 0) <= 0 or report.get("tree_felled") is not True):
                    success = False
                if self.action_type == "FELL_TREE":
                    self.events.append(f"fell_tree target={self.action_target} "
                                       f"work_delta={report.get('work_delta')} "
                                       f"tree_felled={report.get('tree_felled')}")
                if self.action_type in ("LOOT_CLUSTER", "GATHER_PATCH", "COLLECT_AREA"):
                    picked = report.get("picked_count", 0)
                    success = success and isinstance(picked, int) and picked > 0
                    self.events.append(f"{self.action_type.lower()} result id={self.action_id} "
                                       f"picked={picked} delta={report.get('inventory_delta')} "
                                       f"end={report.get('cluster_end_reason')}")
                    if isinstance(picked, int) and picked > 0:
                        self.picked_items += picked
                        if self.action_type == "COLLECT_AREA" and self.collect_area is not None:
                            self.collect_area["collected"] += picked
                    if self.action_type == "COLLECT_AREA":
                        self._end_area(report.get("cluster_end_reason") or "UNKNOWN")
                self._finish(success, status)
            elif (self.action_started_at is not None
                  and time.monotonic() - self.action_started_at > (
                      50 if self.action_type in ("LOOT_CLUSTER", "GATHER_PATCH", "COLLECT_AREA") else
                      35 if self.action_type == "FELL_TREE" else 12)):
                self._finish(False, "lost_action_report")
            else:
                threat = observation.get("visible_threat_within_8")
                if (threat is True and not self.action_escape
                        and self.action_type in ("PICK_TARGET", "PICKUP_TARGET",
                                                 "FELL_TREE", "LOOT_CLUSTER", "GATHER_PATCH",
                                                 "COLLECT_AREA",
                                                 "MOVE_TO_TARGET",
                                                 "MOVE_TO_POINT", "BUILD_CAMPFIRE",
                                                 "COOK_AT", "ADD_FUEL")):
                    if not self.stop_requested:
                        self.reason = "interrupting_for_threat"
                        return {"type": "STOP", "target_id": self.action_id,
                                "goal": "avoid_threat", "say": "附近有危险，我先停下"}
                inventory = observation.get("inventory") or {}
                seconds_to_night = observation.get("seconds_until_night")
                light_deadline = (observation.get("phase") == "night"
                                  and observation.get("in_light") is not True)
                light_deadline = light_deadline or (
                    observation.get("phase") == "dusk"
                    and isinstance(seconds_to_night, (int, float))
                    and seconds_to_night <= EQUIP_LEAD_SECONDS)
                if (light_deadline and inventory.get("hand") != "torch"
                        and (inventory.get("counts") or {}).get("torch", 0) > 0
                        and self.action_type in ("PICK_TARGET", "PICKUP_TARGET",
                                                 "FELL_TREE", "LOOT_CLUSTER", "GATHER_PATCH",
                                                 "COLLECT_AREA",
                                                 "MOVE_TO_TARGET",
                                                 "MOVE_TO_POINT", "BUILD_CAMPFIRE",
                                                 "COOK_AT", "ADD_FUEL")
                        and not self.stop_requested):
                    self.reason = "interrupting_for_light"
                    return {"type": "STOP", "target_id": self.action_id,
                            "goal": "light", "say": "快入夜了，先准备照明"}
                if (self.action_type == "MOVE_TO_POINT" and not self.action_escape
                        and not self.stop_requested):
                    counts = inventory.get("counts") or {}
                    free_slots = inventory.get("free_slots", 15)
                    for target in observation.get("local_entities") or []:
                        kind = target.get("kind")
                        if kind not in ("pickup", "harvest") or target.get("ready") is not True:
                            continue
                        prefab = target.get("prefab")
                        if (prefab in ("flint", "rocks", "goldnugget", "smallmeat")
                                and observation.get("phase") == "night"):
                            continue
                        if (prefab in ("berries", "berries_juicy", "carrot", "seeds")
                                and inventory.get("food_ready_hunger", 0) >= 125):
                            continue
                        distance = (target.get("dx", 99) ** 2 + target.get("dz", 99) ** 2) ** 0.5
                        harvest_useful = False
                        if kind == "harvest" and prefab in HARVEST_PREFABS and free_slots > 0:
                            if prefab == "grass":
                                harvest_useful = counts.get("cutgrass", 0) < 12
                            elif prefab == "sapling":
                                harvest_useful = counts.get("twigs", 0) < 12
                            else:
                                harvest_useful = inventory.get("food_ready_hunger", 0) < 75
                        pickup_useful = (kind == "pickup" and loose_item_offer(
                            prefab, counts.get(prefab, 0), free_slots, distance) is not None)
                        if (distance <= (4 if harvest_useful else 2.5)
                                and (harvest_useful or pickup_useful)
                                and self.avoid_targets.get(target.get("guid"), 0) <= time.monotonic()
                                and not self._route_near_hazard(observation, target)
                                and (observation.get("cycles", 0) >= 2
                                     or target.get("marsh_steps", 0) == 0)):
                            self.reason = "passing_loot"
                            return {"type": "STOP", "target_id": self.action_id,
                                    "goal": "stockpile", "say": "路边有资源，我顺手收集"}
                return None

        local_move = observation.get("movement") or {}
        if local_move.get("epoch") == "local" and local_move.get("status") == "started":
            self.reason = "local_escape_running"
            return None

        return self._choose(observation)

    def _finish(self, success, status):
        if success:
            self.completed += 1
            if self.action_type == "MOVE_TO_POINT" and self.action_point is not None:
                self._mark_visit(*self.action_point)
        elif status not in ("stopped", "interrupted_threat", "interrupted_light",
                            "interrupted_marsh"):
            self.failed += 1
            if self.action_type in ("EAT_FOOD", "CRAFT_TORCH", "CRAFT_AXE",
                                    "BUILD_CAMPFIRE", "COOK_AT", "ADD_FUEL",
                                    "EQUIP_TORCH", "EQUIP_AXE", "UNEQUIP_TORCH"):
                self.retry_after[self.action_type] = time.monotonic() + (
                    60 if self.action_type == "BUILD_CAMPFIRE" else 5)
            if self.action_target is not None:
                self.avoid_targets[self.action_target] = time.monotonic() + (
                    3 if status in ("failed_approach", "failed_native_start",
                                    "failed_or_interrupted") else 20)
            if (self.action_type == "MOVE_TO_POINT" and self.action_point is not None
                    and status in ("blocked", "timed_out", "blocked_or_timed_out",
                                   "rejected_point")):
                self._mark_visit(*self.action_point, amount=4)
                self.blocked_cells.add(self._cell(*self.action_point))
                if self.last_position is not None:
                    px, pz = self.last_position
                    dx, dz = self.action_point[0] - px, self.action_point[1] - pz
                    length = (dx * dx + dz * dz) ** 0.5
                    if length > 0:
                        self.blocked_cells.add(self._cell(px + 5 * dx / length,
                                                          pz + 5 * dz / length))
        if status == "interrupted_threat" and self.action_target is not None:
            self.avoid_targets[self.action_target] = time.monotonic() + 20
        if status in ("interrupted_threat", "interrupted_light", "interrupted_marsh",
                      "stopped") and self.collect_area:
            self._end_area("SAFETY_INTERRUPT")
        if self.action_type == "COLLECT_AREA" and self.collect_area is not None:
            self._end_area(status.upper())
        if (self.action_type == "MOVE_TO_TARGET" and not success
                and self.collect_area is not None):
            self._end_area(status.upper())
        self.events.append(f"action id={self.action_id} behavior={self.action_behavior_id} "
                           f"status={status} success={success}")
        self.reason = status
        self.action_id = None
        self.action_type = None
        self.action_target = None
        self.action_point = None
        self.action_escape = False
        self.action_started_at = None
        self.action_behavior_id = None
        self.stop_requested = False

    def _end_area(self, reason):
        if self.collect_area is not None:
            self.events.append(f"collect_area id={self.collect_area['id']} end={reason} "
                               f"collected={self.collect_area['collected']}")
            self.collect_area = None

    def _continue_area(self, observation, free_slots, now):
        area = self.collect_area
        if area is None:
            return None
        if free_slots <= 0:
            self._end_area("INVENTORY_LIMIT")
            return None
        if now - area["started_at"] >= 60:
            self._end_area("TASK_BUDGET_REACHED")
            return None
        visible = {item.get("guid"): item for item in observation.get("local_entities") or []
                   if item.get("ready") is True}
        available = []
        for entry in area["items"]:
            item = visible.get(entry["guid"])
            if (item is not None and item.get("prefab") == entry["prefab"]
                    and item.get("kind") == entry["kind"]
                    and self.avoid_targets.get(entry["guid"], 0) <= now
                    and not self._route_near_hazard(observation, item)):
                available.append(item)
        if not available:
            self._end_area("AREA_EXHAUSTED")
            return None
        ordered = []
        point = (0, 0)
        while available and len(ordered) < 12:
            item = min(available, key=lambda current:
                       ((current["dx"] - point[0]) ** 2
                        + (current["dz"] - point[1]) ** 2, current["guid"]))
            ordered.append(item)
            available.remove(item)
            point = (item["dx"], item["dz"])
        first = ordered[0]
        items = [{"guid": item["guid"], "prefab": item["prefab"],
                  "kind": item["kind"]} for item in ordered]
        self.events.append(f"collect_area id={area['id']} batch=["
                           + ",".join(f"{item['prefab']}:{item['guid']}" for item in items)
                           + "]")
        return {"type": "COLLECT_AREA", "items": items,
                "target_guid": first["guid"], "behavior_id": area["id"],
                "goal": area["goal"], "say": "这一片有用的东西，我一起收集"}

    @staticmethod
    def _cell(x, z):
        return (round(x / 4), round(z / 4))

    @staticmethod
    def _hazard_radius(prefab):
        return 4.5 if prefab == "frog" else 10 if prefab == "tentacle" else 8

    def _route_near_hazard(self, observation, target):
        dx, dz = target.get("dx"), target.get("dz")
        if not isinstance(dx, (int, float)) or not isinstance(dz, (int, float)):
            return False
        length_sq = dx * dx + dz * dz
        x, z = observation.get("x"), observation.get("z")
        hazards = [(item.get("dx"), item.get("dz"),
                    self._hazard_radius(item.get("prefab")))
                   for item in observation.get("visible_hazards") or []]
        if isinstance(x, (int, float)) and isinstance(z, (int, float)):
            hazards.extend((world_x - x, world_z - z, radius)
                           for world_x, world_z, radius, expiry in self.hazard_zones.values()
                           if expiry > time.monotonic())
        for hx, hz, radius in hazards:
            if not isinstance(hx, (int, float)) or not isinstance(hz, (int, float)):
                continue
            progress = max(0, min(1, (hx * dx + hz * dz) / max(length_sq, 0.01)))
            start_sq = hx * hx + hz * hz
            end_sq = (hx - dx) ** 2 + (hz - dz) ** 2
            if (start_sq < radius * radius and end_sq > radius * radius
                    and hx * dx + hz * dz <= 0):
                continue
            if (hx - progress * dx) ** 2 + (hz - progress * dz) ** 2 < radius * radius:
                return True
        return False

    def _leave_marsh(self, observation):
        x, z = observation.get("x"), observation.get("z")
        if not isinstance(x, (int, float)) or not isinstance(z, (int, float)):
            return None
        exits = []
        for point in observation.get("frontier") or []:
            dx, dz = point.get("dx"), point.get("dz")
            if (point.get("passable") is True
                    and point.get("endpoint_marsh") is False
                    and isinstance(dx, (int, float))
                    and isinstance(dz, (int, float))
                    and self._cell(x + dx, z + dz) not in self.blocked_cells
                    and not self._route_near_hazard(observation, point)):
                exits.append((point.get("marsh_steps", 0), dx * dx + dz * dz,
                              x + dx, z + dz, dx, dz))
        if not exits:
            return None
        _, _, goal_x, goal_z, dx, dz = min(exits)
        self.heading = (dx, dz)
        self.events.append(f"leave_marsh destination=({goal_x:.1f},{goal_z:.1f})")
        return {"type": "MOVE_TO_POINT", "x": goal_x, "z": goal_z,
                "goal": "avoid_threat", "say": "这片沼泽太危险，我先离开"}

    def _mark_visit(self, x, z, amount=1):
        if isinstance(x, (int, float)) and isinstance(z, (int, float)):
            cell = self._cell(x, z)
            self.visits[cell] = self.visits.get(cell, 0) + amount

    def _update_safety_mode(self, observation):
        now = time.monotonic()
        health = ((observation.get("vitals") or {}).get("health") or {}).get("current")
        if isinstance(health, (int, float)):
            if self.last_health is not None and health < self.last_health:
                self.recent_hit_until = now + 2
            self.last_health = health
        hazards = observation.get("visible_hazards") or []
        threat = (observation.get("visible_threat_within_8") is True
                  or any(item.get("targeting_player") is True for item in hazards)
                  or now < self.recent_hit_until)
        if threat:
            if self.safety_mode != "EVADE":
                self.events.append(f"safety {self.safety_mode}->EVADE")
            self.safety_mode = "EVADE"
            self.safety_clear_since = None
            return
        if observation.get("on_marsh") is True and observation.get("cycles", 0) < 2:
            if self.safety_mode == "NORMAL":
                self.events.append("safety NORMAL->RECOVER marsh")
            self.safety_mode = "RECOVER"
            self.safety_clear_since = None
            return
        if self.safety_mode == "EVADE":
            self.safety_mode = "RECOVER"
            self.safety_clear_since = now
            self.events.append("safety EVADE->RECOVER")
        if self.safety_mode == "RECOVER":
            safely_clear = observation.get("on_marsh") is not True and all(
                item.get("distance_sq", 0) >= (self._hazard_radius(item.get("prefab")) + 2) ** 2
                for item in hazards)
            if not safely_clear:
                self.safety_clear_since = None
            elif self.safety_clear_since is None:
                self.safety_clear_since = now
            elif now - self.safety_clear_since >= 2:
                self.safety_mode = "NORMAL"
                self.safety_clear_since = None
                self.events.append("safety RECOVER->NORMAL")

    def _remember(self, observation):
        self._update_safety_mode(observation)
        x, z = observation.get("x"), observation.get("z")
        if not isinstance(x, (int, float)) or not isinstance(z, (int, float)):
            return
        self.last_position = (x, z)
        cell = self._cell(x, z)
        if cell != self.last_cell:
            self._mark_visit(x, z)
            self.last_cell = cell
        now = time.monotonic()
        self.hazard_zones = {cell: zone for cell, zone in self.hazard_zones.items()
                             if zone[3] > now}
        for hazard in observation.get("visible_hazards") or []:
            dx, dz = hazard.get("dx"), hazard.get("dz")
            if (isinstance(dx, (int, float))
                    and isinstance(dz, (int, float))):
                world_x, world_z = x + dx, z + dz
                prefab = hazard.get("prefab")
                self.hazard_zones[(prefab, self._cell(world_x, world_z))] = (
                    world_x, world_z, self._hazard_radius(prefab),
                    now + (120 if prefab == "tentacle" else 35))
        self._mark_visible_cells(x, z)
        for entity in observation.get("local_entities") or []:
            if entity.get("ready") is True and isinstance(entity.get("guid"), int):
                self.seen_resources.add(entity["guid"])

    def _cells_visible_from(self, x, z):
        center_x, center_z = self._cell(x, z)
        return {(center_x + dx, center_z + dz)
                for dx in range(-10, 11) for dz in range(-10, 11)
                if (center_x * 4 + dx * 4 - x) ** 2
                + (center_z * 4 + dz * 4 - z) ** 2 <= 1600}

    def _mark_visible_cells(self, x, z):
        self.seen_cells.update(self._cells_visible_from(x, z))

    def _record_milestone(self, observation):
        health = ((observation.get("vitals") or {}).get("health") or {}).get("current")
        if isinstance(health, (int, float)) and health <= 0:
            if self.first_night_result is None:
                self.first_night_result = "died"
                self.events.append("first night result=died")
            else:
                self.events.append("player died after first night")
            self.enabled = False
            self.reason = "player_died"
            return
        if self.first_night_result is not None:
            return
        phase = observation.get("phase")
        if phase == "night":
            self.saw_night = True
            if observation.get("in_light") is True:
                self.night_light_samples += 1
            elif observation.get("in_light") is False:
                self.night_dark_samples += 1
        elif phase == "day" and self.saw_night:
            self.first_night_result = ("survived_with_light"
                                       if self.night_dark_samples == 0
                                       else "survived_with_darkness")
            self.events.append(f"first night result={self.first_night_result} "
                               f"light={self.night_light_samples} "
                               f"dark={self.night_dark_samples}")

    def _choose(self, observation):
        if observation.get("on_marsh") is True and observation.get("cycles", 0) < 2:
            exit_choice = self._leave_marsh(observation)
            if exit_choice is not None:
                return exit_choice
        if self.safety_mode == "EVADE":
            return self._escape(observation)
        if self.safety_mode == "RECOVER":
            if self.safety_clear_since is None:
                choice = self._escape(observation)
                if choice is not None:
                    return choice
            self.reason = "recovering_from_threat"
            return None
        if observation.get("visible_threat_within_8") is not False:
            self.reason = "threat_unknown"
            return None
        vitals = observation.get("vitals") or {}
        health = (vitals.get("health") or {}).get("current")
        hunger = (vitals.get("hunger") or {}).get("current")
        sanity = (vitals.get("sanity") or {}).get("current")
        sanity_max = (vitals.get("sanity") or {}).get("max")
        if not isinstance(health, (int, float)) or not isinstance(hunger, (int, float)):
            self.reason = "vitals_unknown"
            return None
        inv = observation.get("inventory") or {}
        counts = inv.get("counts") or {}
        free_slots = inv.get("free_slots", 15)
        edible = inv.get("edible_counts") or counts
        grass = counts.get("cutgrass", 0)
        twigs = counts.get("twigs", 0)
        torch = counts.get("torch", 0)
        flint = counts.get("flint", 0)
        stone = counts.get("rocks", 0)
        gold = counts.get("goldnugget", 0)
        morsels = counts.get("smallmeat", 0)
        logs = counts.get("log", 0)
        axes = counts.get("axe", 0)
        hand_torch = inv.get("hand") == "torch"
        hand_axe = inv.get("hand") == "axe"
        phase = observation.get("phase")
        in_light = observation.get("in_light")
        seconds_until_day = observation.get("seconds_until_day")
        seconds_until_night = observation.get("seconds_until_night")
        hunger_max = (vitals.get("hunger") or {}).get("max") or 150
        hunger_scale = hunger_max / 150
        food_ready_hunger = inv.get("food_ready_hunger")
        if not isinstance(food_ready_hunger, (int, float)):
            food_ready_hunger = sum(edible.get(prefab, 0) * value
                                    for prefab, value in FOOD_HUNGER_FALLBACK.items())
        food_refill_low = (18.75 if observation.get("cycles", 0) < 1 else 37.5) * hunger_scale
        food_refill_target = (37.5 if observation.get("cycles", 0) < 1 else 75) * hunger_scale
        if food_ready_hunger < food_refill_low:
            self.food_refill_active = True
        elif food_ready_hunger >= food_refill_target:
            self.food_refill_active = False
        if hunger <= 100 * hunger_scale:
            self.eating_batch = True
        elif hunger >= 125 * hunger_scale:
            self.eating_batch = False
        for name, count in (("grass", grass), ("sapling", twigs)):
            if count < 4:
                self.material_refill[name] = True
            elif count >= (8 if observation.get("cycles", 0) < 1 else 10):
                self.material_refill[name] = False

        ready_light_seconds = inv.get("torch_ready_seconds")
        if not isinstance(ready_light_seconds, (int, float)):
            ready_light_seconds = torch * TORCH_SECONDS_FALLBACK
            if hand_torch:
                ready_light_seconds += inv.get("hand_fuel_seconds") or TORCH_SECONDS_FALLBACK
        if phase == "night" and isinstance(seconds_until_day, (int, float)):
            night_seconds = seconds_until_day
        elif (phase == "dusk" and isinstance(seconds_until_day, (int, float))
              and isinstance(seconds_until_night, (int, float))):
            night_seconds = max(0, seconds_until_day - seconds_until_night)
        else:
            night_seconds = 60
        light_needed = ready_light_seconds < night_seconds + LIGHT_MARGIN_SECONDS
        night_imminent = (phase == "dusk" and isinstance(seconds_until_night, (int, float))
                          and seconds_until_night <= EQUIP_LEAD_SECONDS)
        critical_hunger = hunger <= 25 * hunger_scale

        if phase in ("day", "dusk") and hand_torch and not night_imminent and in_light is not False:
            return self._utility("UNEQUIP_TORCH", "light", "天还亮着，先收起火炬")
        if (((phase == "night" and in_light is not True) or night_imminent)
                and not hand_torch and torch > 0):
            return self._utility("EQUIP_TORCH", "light", "天黑了，拿出火炬")
        hand_seconds = inv.get("hand_fuel_seconds")
        if (hand_torch and (phase == "night" or night_imminent)
                and isinstance(hand_seconds, (int, float))
                and hand_seconds < REPLACE_MARGIN_SECONDS and torch > 0):
            return self._utility("EQUIP_TORCH", "light", "火炬快灭了，换一支")
        if critical_hunger and food_ready_hunger > 0 and not night_imminent:
            return self._utility("EAT_FOOD", "food", "饥饿危险，先吃点东西")
        total_torches = torch + int(hand_torch)
        need_torch = light_needed or total_torches == 0
        if need_torch and grass >= 2 and twigs >= 2:
            return self._utility("CRAFT_TORCH", "light", "材料够了，做一支火炬")
        if phase == "night" and not hand_torch and in_light is not True:
            self.reason = "night_without_light"
            return None
        if self.eating_batch and food_ready_hunger > 0:
            return self._utility("EAT_FOOD", "food", "有点饿了，先吃点东西")

        needs = []
        if critical_hunger and phase != "night" and not night_imminent:
            needs.append("food")
        if need_torch:
            if grass < 2:
                needs.append("grass")
            if twigs < 2:
                needs.append("sapling")
        if ((self.food_refill_active or hunger <= 50 * hunger_scale)
                and (phase != "night" or critical_hunger)
                and "food" not in needs):
            needs.append("food")
        if phase in ("day", "dusk") and not night_imminent:
            if self.material_refill["grass"] and grass < (8 if observation.get("cycles", 0) < 1 else 10):
                needs.append("grass")
            if self.material_refill["sapling"] and twigs < (8 if observation.get("cycles", 0) < 1 else 10):
                needs.append("sapling")

        nearby = observation.get("local_entities") or []
        now = time.monotonic()
        if (observation.get("on_marsh") is True
                and observation.get("cycles", 0) < 2 and phase in ("day", "dusk")):
            exit_choice = self._leave_marsh(observation)
            if exit_choice is not None:
                self._end_area("LEAVING_MARSH")
                return exit_choice
        if self.collect_area is not None:
            if critical_hunger or night_imminent or phase == "night":
                self._end_area("SURVIVAL_INTERRUPT")
            else:
                area_choice = self._continue_area(observation, free_slots, now)
                if area_choice is not None:
                    return area_choice
        can_cook = (phase == "day" and observation.get("cycles", 0) >= 1
                    and not light_needed and morsels > 0 and grass >= 7
                    and twigs >= 4 and health >= 90 and hunger > 50 * hunger_scale
                    and isinstance(sanity, (int, float))
                    and isinstance(sanity_max, (int, float))
                    and sanity >= 0.4 * sanity_max
                    and (not isinstance(seconds_until_night, (int, float))
                         or seconds_until_night > 30))
        if can_cook:
            fire = next((fire for fire in observation.get("nearby_fires") or []
                         if self.avoid_targets.get(fire.get("guid"), 0) <= now), None)
            if fire is not None:
                if fire.get("dx", 99) ** 2 + fire.get("dz", 99) ** 2 > 4:
                    return {"type": "MOVE_TO_TARGET", "target_guid": fire["guid"],
                            "target_prefab": "campfire", "goal": "cook",
                            "say": "有营火，我过去处理小肉"}
                if fire.get("fuel_seconds", 0) < 20 and logs > 0:
                    return {"type": "ADD_FUEL", "target_guid": fire["guid"],
                            "goal": "cook", "say": "营火快灭了，加一块木头"}
                if fire.get("fuel_seconds", 0) >= 10:
                    return {"type": "COOK_AT", "target_guid": fire["guid"],
                            "goal": "cook", "say": "把一块小肉烤熟"}
            elif logs >= 3 and self.retry_after.get("BUILD_CAMPFIRE", 0) <= now:
                return self._utility("BUILD_CAMPFIRE", "cook", "找块空地生火，准备烤食物")

        can_develop = (phase == "day" and observation.get("cycles", 0) >= 1
                       and not light_needed and not self.food_refill_active
                       and not any(self.material_refill.values())
                       and food_ready_hunger >= 37.5 * hunger_scale
                       and hunger > 75 * hunger_scale
                       and health >= 90
                       and isinstance(sanity, (int, float))
                       and isinstance(sanity_max, (int, float))
                       and sanity >= 0.4 * sanity_max
                       and (not isinstance(seconds_until_night, (int, float))
                            or seconds_until_night > 15))
        if can_develop and logs < 6:
            loose_log = next((entity for entity in nearby
                              if entity.get("prefab") == "log"
                              and entity.get("ready") is True
                              and self.avoid_targets.get(entity.get("guid"), 0) <= now), None)
            if loose_log is not None:
                return self._resource_choice("wood", loose_log, observation)
            if axes + int(hand_axe) == 0:
                if flint >= 1 and twigs >= 3:
                    return self._utility("CRAFT_AXE", "wood", "生存储备够了，做把斧头")
                if flint < 1:
                    needs.append("flint")
            elif not hand_axe:
                return self._utility("EQUIP_AXE", "wood", "准备砍树，拿出斧头")
            else:
                needs.append("wood")

        material_target = 8 if observation.get("cycles", 0) < 1 else 10
        opportunities = {
            "food": (9 if critical_hunger else 7 if hunger <= 50 * hunger_scale
                     else 5 if self.food_refill_active else 3
                     if food_ready_hunger < 75 * hunger_scale else 1
                     if food_ready_hunger < 125 * hunger_scale else 0),
            "grass": (10 if need_torch and grass < 2 else 4
                      if grass < material_target else 1 if grass < 16 else 0),
            "sapling": (10 if need_torch and twigs < 2 else 4
                        if twigs < material_target else 1 if twigs < 16 else 0),
            "flint": 8 if flint == 0 else 4 if flint < 3 else 1 if flint < 6 else 0,
            "morsel": 2 if morsels < 2 else 0,
            "wood": 6 if can_develop and hand_axe and logs < 6 else 0,
            "stone": 4 if stone < 4 else 2 if stone < 8 else 0,
            "gold": 2 if gold < 3 else 0,
        }
        if "flint" in needs:
            opportunities["flint"] = max(opportunities["flint"], 5)
        if phase == "dusk" and night_imminent:
            opportunities["food"] = 0
            opportunities["flint"] = 0
            opportunities["morsel"] = 0
            opportunities["stone"] = 0
            opportunities["gold"] = 0
        if phase == "night":
            opportunities["flint"] = 0
            opportunities["morsel"] = 0
            opportunities["wood"] = 0
            opportunities["stone"] = 0
            opportunities["gold"] = 0

        candidates = []
        rejected = []
        for target in nearby:
            label = (f"{target.get('prefab')}:{target.get('guid')}"
                     f"(owned={counts.get(target.get('prefab'), 0)})")
            if target.get("ready") is not True:
                rejected.append(f"{label}=NOT_READY")
                continue
            if self.avoid_targets.get(target.get("guid"), 0) > now:
                rejected.append(f"{label}=RECENT_FAILURE_COOLDOWN")
                continue
            if free_slots <= 0 and target.get("kind") in ("pickup", "harvest"):
                rejected.append(f"{label}=INVENTORY_FULL")
                continue
            distance_sq = target.get("dx", 99) ** 2 + target.get("dz", 99) ** 2
            if distance_sq > (64 if phase == "night" and hand_torch else
                              4 if phase == "night" else 1600):
                rejected.append(f"{label}=OUTSIDE_ALLOWED_RADIUS")
                continue
            distance = distance_sq ** 0.5
            if self._route_near_hazard(observation, target):
                rejected.append(f"{label}=UNSAFE_HAZARD_ROUTE")
                continue
            if (observation.get("cycles", 0) < 2
                    and target.get("marsh_steps", 0) > 0):
                rejected.append(f"{label}=MARSH_ROUTE")
                continue
            matched = False
            for resource, prefabs in RESOURCE_PREFABS.items():
                if target.get("prefab") not in prefabs:
                    continue
                matched = True
                priority = opportunities[resource]
                if resource == "wood" and target["prefab"] == "log" and logs < 6:
                    priority = max(priority, 2)
                if (priority <= 0 or (priority <= 3 and distance_sq > 64)
                        or (priority < 8 and distance_sq > 256)
                        or (resource == "flint" and distance_sq > 576)):
                    rejected.append(f"{label}=" + ("RESOURCE_ALREADY_SUFFICIENT"
                                                     if priority <= 0 else
                                                     "OUTSIDE_ALLOWED_RADIUS"))
                    continue
                value_bonus = (1 if target["prefab"] in ("carrot", "carrot_planted")
                               else 0.5 if target["prefab"] in
                               ("berrybush", "berrybush2", "berrybush_juicy") else 0)
                near_bonus = (0 if critical_hunger and resource != "food" else
                              8 if distance_sq <= 36 else 0)
                score = (priority + value_bonus + near_bonus - 0.7 * distance
                         + (20 - 0.5 * distance_sq if distance_sq <= 16 else 0))
                candidates.append((-score, distance_sq, target["guid"], resource, target))
            if target.get("kind") == "pickup" and not matched:
                offer = loose_item_offer(target.get("prefab"),
                                         counts.get(target.get("prefab"), 0),
                                         free_slots, distance)
                if offer is not None:
                    priority, _ = offer
                    score = (priority + (8 if distance_sq <= 36 else 0)
                             - 0.7 * distance
                             + (20 - 0.5 * distance_sq if distance_sq <= 16 else 0))
                    candidates.append((-score, distance_sq, target["guid"], "loot", target))
                else:
                    desired = ITEM_CATALOG.get(target.get("prefab"), (None, 1, 1, 3))[1]
                    rejected.append(f"{label}=" + (
                        "RESOURCE_ALREADY_SUFFICIENT"
                        if counts.get(target.get("prefab"), 0) >= desired else
                        "INVENTORY_PRESSURE" if free_slots <= 3 else
                        "OUTSIDE_ALLOWED_RADIUS"))
        if candidates:
            top = sorted(candidates)[:5]
            self.decision_seq += 1
            top_text = ", ".join(
                f"{row[4]['prefab']}:{row[2]}:{-row[0]:.1f}" for row in top)
            area_options = []
            if phase != "night" and not night_imminent and free_slots > 0:
                collectible = [row for row in sorted(candidates)
                               if row[4].get("kind") in ("harvest", "pickup")
                               and (not critical_hunger or row[3] == "food")]
                seen = set()
                for seed in collectible:
                    center = seed[4]
                    if center["dx"] ** 2 + center["dz"] ** 2 > 256:
                        continue
                    members = [row for row in collectible
                               if (row[4]["dx"] - center["dx"]) ** 2
                               + (row[4]["dz"] - center["dz"]) ** 2 <= 36
                               and row[4]["dx"] ** 2 + row[4]["dz"] ** 2 <= 484]
                    members = members[:12]
                    key = frozenset(row[2] for row in members)
                    if len(key) < 2 or key in seen:
                        continue
                    seen.add(key)
                    best = min(members)
                    area_score = -best[0] + 3 * min(len(members) - 1, 5)
                    area_options.append((-area_score, best[1], best[2], members))
            best_area = min(area_options, key=lambda row: row[:3]) if area_options else None
            if best_area and best_area[:3] < min(candidates)[:3]:
                _, _, _, members = best_area
                self.behavior_seq += 1
                area_id = f"area-{self.behavior_seq}"
                self.collect_area = {
                    "id": area_id, "goal": "food" if critical_hunger else "stockpile",
                    "items": [{"guid": row[4]["guid"], "prefab": row[4]["prefab"],
                               "kind": row[4]["kind"]} for row in members],
                    "collected": 0, "started_at": now,
                }
                self.events.append(
                    f"decision={self.decision_seq} chosen=collect_area:{area_id} "
                    f"score={-best_area[0]:.1f} "
                    f"members=[{','.join(str(item['guid']) for item in self.collect_area['items'])}] "
                    f"top=[{top_text}] rejected=[{', '.join(rejected[:8])}] "
                    f"free_slots={free_slots}")
                return self._continue_area(observation, free_slots, now)
            _, _, _, resource, target = min(candidates)
            self.events.append(
                f"decision={self.decision_seq} chosen={target['prefab']}:{target['guid']} "
                f"top=[{top_text}] "
                f"rejected=[{', '.join(rejected[:8])}] free_slots={free_slots}")
            choice = self._resource_choice(resource, target, observation)
            if choice["type"] == "FELL_TREE":
                self.behavior_seq += 1
                choice["behavior_id"] = f"tree-{self.behavior_seq}"
            return choice

        if (phase == "night" and (not hand_torch
                or ready_light_seconds < night_seconds + 10)):
            self.reason = "night_waiting_in_light"
            return None
        if phase not in ("day", "dusk", "night"):
            self.reason = "unknown_phase"
            return None
        frontier = observation.get("frontier") or []
        x, z = observation.get("x"), observation.get("z")
        if not isinstance(x, (int, float)) or not isinstance(z, (int, float)):
            self.reason = "position_unknown"
            return None
        choices = []
        for index, point in enumerate(frontier):
            dx, dz = point.get("dx"), point.get("dz")
            if point.get("passable") is not True or not isinstance(dx, (int, float)) or not isinstance(dz, (int, float)):
                continue
            if observation.get("cycles", 0) < 2 and point.get("marsh_steps", 0) > 0:
                continue
            if self._route_near_hazard(observation, point):
                continue
            if (phase == "night" and ready_light_seconds < night_seconds + 30
                    and dx * dx + dz * dz > 64):
                continue
            destination = (x + dx, z + dz)
            cell = self._cell(*destination)
            distance = (dx * dx + dz * dz) ** 0.5
            crossed_cells = [self._cell(x + dx * step / max(1, int(distance / 4)),
                                        z + dz * step / max(1, int(distance / 4)))
                             for step in range(1, max(1, int(distance / 4)) + 1)]
            if cell in self.blocked_cells or any(
                    crossed in self.blocked_cells for crossed in crossed_cells):
                continue
            visits = sum(self.visits.get(crossed, 0) for crossed in crossed_cells)
            if self.heading is not None:
                hx, hz = self.heading
                heading_length = (hx * hx + hz * hz) ** 0.5
                alignment = ((hx * dx + hz * dz) / (heading_length * distance)
                             if heading_length > 0 and distance > 0 else 0)
                turn_cost = 24 * (1 - alignment)
            else:
                turn_cost = 0
            new_cells = len(self._cells_visible_from(*destination) - self.seen_cells)
            marsh_steps = point.get("marsh_steps", 0)
            score = visits * 1.5 - new_cells + turn_cost + marsh_steps * 35
            choices.append((score, visits, index, destination, (dx, dz)))
        if not choices:
            self.reason = "no_safe_frontier"
            return None
        best_score, _, _, destination, heading = min(choices)
        self.decision_seq += 1
        self.events.append(f"decision={self.decision_seq} chosen=frontier:{destination} "
                           f"score={best_score:.1f} alternatives={len(choices)} "
                           f"rejected=[{', '.join(rejected[:8])}]")
        self.heading = heading
        urgent_search = ("grass" if need_torch and grass < 2 else
                         "sapling" if need_torch and twigs < 2 else
                         "food" if self.food_refill_active else None)
        self.reason = f"searching_{urgent_search}" if urgent_search else "exploring"
        say = (f"附近没找到{RESOURCE_NAMES[urgent_search]}，我继续找新区域"
               if urgent_search else "附近没找到需要的东西，我往前看看")
        return {"type": "MOVE_TO_POINT", "x": destination[0], "z": destination[1],
                "goal": "explore", "say": say}

    def _resource_choice(self, prefab, target, observation=None, behavior_id=None):
        name = (RESOURCE_NAMES.get(prefab)
                or ITEM_CATALOG.get(target["prefab"], (target["prefab"],))[0])
        distance_sq = target["dx"] ** 2 + target["dz"] ** 2
        direct_radius_sq = 64 if target["prefab"] in CHOP_PREFABS else 256
        action = (("PICK_TARGET" if target["prefab"] in HARVEST_PREFABS else
                   "FELL_TREE" if target["prefab"] in CHOP_PREFABS else "PICKUP_TARGET")
                  if distance_sq <= direct_radius_sq else "MOVE_TO_TARGET")
        verb = "砍倒" if action == "FELL_TREE" else "捡" if action == "PICKUP_TARGET" else "采"
        say = (f"{name}不够，我{verb}一些" if action != "MOVE_TO_TARGET"
               else f"{name}不够，我走过去看看")
        goal = ("food" if prefab == "food" else
                "stockpile" if prefab in ("flint", "morsel", "stone", "gold", "loot") else
                "wood" if prefab == "wood" else "light")
        if distance_sq > 324 and observation is not None:
            frontier = [point for point in observation.get("frontier") or []
                        if point.get("passable") is True
                        and not self._route_near_hazard(observation, point)
                        and (observation.get("cycles", 0) >= 2
                             or point.get("marsh_steps", 0) == 0)]
            if frontier:
                waypoint = min(frontier, key=lambda point:
                               (point["dx"] - target["dx"]) ** 2
                               + (point["dz"] - target["dz"]) ** 2)
                x, z = observation.get("x"), observation.get("z")
                if isinstance(x, (int, float)) and isinstance(z, (int, float)):
                    choice = {"type": "MOVE_TO_POINT", "x": x + waypoint["dx"],
                              "z": z + waypoint["dz"], "goal": goal,
                              "say": f"看到{name}了，我往那边走"}
                    if behavior_id is not None:
                        choice["behavior_id"] = behavior_id
                    return choice
        choice = {"type": action, "target_guid": target["guid"],
                  "target_prefab": target["prefab"], "auto": action == "PICK_TARGET",
                  "goal": goal, "say": say}
        if behavior_id is not None:
            choice["behavior_id"] = behavior_id
        return choice

    def _utility(self, action_type, goal, say):
        if self.retry_after.get(action_type, 0) > time.monotonic():
            self.reason = f"retry_wait_{action_type.lower()}"
            return None
        return {"type": action_type, "goal": goal, "say": say}

    def _escape(self, observation):
        threat = observation.get("nearest_threat") or {}
        if not threat:
            hazards = observation.get("visible_hazards") or []
            threat = min(hazards, key=lambda item: item.get("distance_sq",
                         item.get("dx", 99) ** 2 + item.get("dz", 99) ** 2)) if hazards else {}
        dx, dz = threat.get("dx"), threat.get("dz")
        x, z = observation.get("x"), observation.get("z")
        if not all(isinstance(value, (int, float)) for value in (x, z, dx, dz)):
            self.reason = "threat_position_unknown"
            return None
        current_distance_sq = dx * dx + dz * dz
        options = []
        for index, point in enumerate(observation.get("frontier") or []):
            px, pz = point.get("dx"), point.get("dz")
            if point.get("passable") is not True or not all(
                    isinstance(value, (int, float)) for value in (px, pz)):
                continue
            distance_sq = px * px + pz * pz
            if distance_sq > 400:
                continue
            if observation.get("cycles", 0) < 2 and (
                    point.get("endpoint_marsh") is True
                    or (observation.get("on_marsh") is not True
                        and point.get("marsh_steps", 0) > 0)):
                continue
            new_distance_sq = (px - dx) ** 2 + (pz - dz) ** 2
            if new_distance_sq <= current_distance_sq + 4:
                continue
            if self._route_near_hazard(observation, point):
                continue
            destination = (x + px, z + pz)
            if self._cell(*destination) in self.blocked_cells:
                continue
            marsh_cost = (point.get("marsh_steps", 0) * 30
                          if observation.get("on_marsh") is not True else
                          point.get("marsh_steps", 0) * 10)
            if point.get("endpoint_marsh") is True:
                marsh_cost += 60
            visits = self.visits.get(self._cell(*destination), 0)
            score = marsh_cost + visits * 3 - new_distance_sq * 0.12 - distance_sq * 0.03
            options.append((score, index, destination, (px, pz)))
        if not options:
            self.reason = "no_safe_escape_point"
            return None
        _, _, destination, heading = min(options)
        self.heading = heading
        self.reason = "avoiding_threat"
        return {"type": "MOVE_TO_POINT", "x": destination[0], "z": destination[1],
                "escape": True, "goal": "avoid_threat",
                "say": "附近有危险，我往安全的方向走"}
