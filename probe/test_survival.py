import unittest
import time

from survival import SurvivalPlanner


def observation(**changes):
    state = {
        "guid": 42,
        "seq": 1,
        "x": 0,
        "z": 0,
        "phase": "day",
        "visible_threat_within_8": False,
        "local_entities_truncated": False,
        "vitals": {"health": {"current": 150}, "hunger": {"current": 120},
                   "sanity": {"current": 200, "max": 200}},
        "inventory": {"counts": {"cutgrass": 0, "twigs": 0, "berries": 0, "torch": 0},
                      "hand": None, "hand_fuel_percent": None},
        "local_entities": [],
        "frontier": [{"dx": 6, "dz": 0, "passable": True},
                     {"dx": 0, "dz": 6, "passable": True}],
    }
    state.update(changes)
    return state


class SurvivalPlannerTests(unittest.TestCase):
    def test_approach_and_pick_waits_for_real_completion(self):
        planner = SurvivalPlanner()
        grass = {"guid": 99, "prefab": "grass", "ready": True, "dx": 5, "dz": 0}
        planner.start(observation(local_entities=[grass]))
        choice = planner.on_observation(observation(local_entities=[grass]), "epoch")
        self.assertEqual(choice["type"], "PICK_TARGET")
        planner.record_command(1, choice)
        self.assertIsNone(planner.on_observation(observation(
            local_entities=[grass], execution={"epoch": "epoch", "id": 1,
                                               "status": "started"}), "epoch"))
        choice = planner.on_observation(observation(
            inventory={"counts": {"cutgrass": 1, "twigs": 0, "berries": 0, "torch": 0}},
            execution={"epoch": "epoch", "id": 1, "status": "completed", "inventory_delta": 1}), "epoch")
        self.assertEqual(planner.completed, 1)
        self.assertEqual(choice["type"], "MOVE_TO_POINT")

    def test_craft_eat_and_equip_from_inventory_state(self):
        planner = SurvivalPlanner()
        supplies = {"cutgrass": 2, "twigs": 2, "berries": 1, "torch": 0}
        planner.start(observation())
        choice = planner.on_observation(observation(
            inventory={"counts": supplies},
            vitals={"health": {"current": 150}, "hunger": {"current": 100}}), "epoch")
        self.assertEqual(choice["type"], "CRAFT_TORCH")
        planner.record_command(1, choice)
        choice = planner.on_observation(observation(
            inventory={"counts": {"cutgrass": 0, "twigs": 0, "berries": 1, "torch": 1}},
            vitals={"health": {"current": 150}, "hunger": {"current": 100}},
            utility={"epoch": "epoch", "id": 1, "status": "completed"}), "epoch")
        self.assertEqual(choice["type"], "EAT_FOOD")
        planner.record_command(2, choice)
        choice = planner.on_observation(observation(
            phase="night",
            inventory={"counts": {"cutgrass": 0, "twigs": 0, "berries": 0, "torch": 1}},
            vitals={"health": {"current": 150}, "hunger": {"current": 112}},
            utility={"epoch": "epoch", "id": 2, "status": "completed"}), "epoch")
        self.assertEqual(choice["type"], "EQUIP_TORCH")

    def test_threat_interrupts_movement(self):
        planner = SurvivalPlanner()
        planner.start(observation())
        choice = planner.on_observation(observation(), "epoch")
        planner.record_command(1, choice)
        threat = {"dx": 4, "dz": 0, "prefab": "frog"}
        stop = planner.on_observation(observation(visible_threat_within_8=True,
            nearest_threat=threat,
            movement={"epoch": "epoch", "id": 1, "status": "started"}), "epoch")
        self.assertEqual(stop["type"], "STOP")
        planner.record_command(2, stop)
        escape = planner.on_observation(observation(visible_threat_within_8=True,
            nearest_threat=threat,
            movement={"epoch": "epoch", "id": 1, "status": "interrupted_threat"}), "epoch")
        self.assertNotIn(planner._cell(choice["x"], choice["z"]), planner.blocked_cells)
        self.assertEqual(escape["type"], "MOVE_TO_POINT")
        self.assertTrue(escape["escape"])
        self.assertEqual((escape["x"], escape["z"]), (0, 6))
        planner.record_command(3, escape)
        self.assertIsNone(planner.on_observation(observation(visible_threat_within_8=True,
            nearest_threat=threat,
            movement={"epoch": "epoch", "id": 3, "status": "started"}), "epoch"))

    def test_exploration_stops_for_grass_reached_along_route(self):
        planner = SurvivalPlanner()
        start = observation()
        planner.start(start)
        move = planner.on_observation(start, "epoch")
        self.assertEqual(move["type"], "MOVE_TO_POINT")
        planner.record_command(1, move)
        grass = {"guid": 99, "prefab": "grass", "kind": "harvest",
                 "ready": True, "dx": 3, "dz": 0, "marsh_steps": 0}
        passing = observation(local_entities=[grass],
                              movement={"epoch": "epoch", "id": 1,
                                        "status": "started"})
        stop = planner.on_observation(passing, "epoch")
        self.assertEqual(stop["type"], "STOP")
        planner.record_command(2, stop)
        passing["movement"]["status"] = "stopped"
        self.assertEqual(planner.on_observation(passing, "epoch")["type"], "PICK_TARGET")

    def test_daylight_puts_torch_away(self):
        planner = SurvivalPlanner()
        planner.start(observation())
        choice = planner.on_observation(observation(
            inventory={"counts": {"cutgrass": 0, "twigs": 0, "berries": 0, "torch": 0},
                       "hand": "torch", "hand_fuel_percent": 0.6}), "epoch")
        self.assertEqual(choice["type"], "UNEQUIP_TORCH")

    def test_late_dusk_keeps_ready_torch_in_inventory(self):
        planner = SurvivalPlanner()
        planner.start(observation())
        choice = planner.on_observation(observation(
            phase="dusk", phase_progress=0.93,
            inventory={"counts": {"cutgrass": 0, "twigs": 0, "berries": 0, "torch": 1},
                       "hand": None}), "epoch")
        self.assertEqual(choice["type"], "MOVE_TO_POINT")

    def test_dusk_puts_away_auto_equipped_torch(self):
        planner = SurvivalPlanner()
        state = observation(
            phase="dusk", phase_progress=0.3,
            inventory={"counts": {"cutgrass": 0, "twigs": 0,
                                  "berries": 0, "torch": 1},
                       "hand": "torch", "hand_fuel_percent": 0.99})
        planner.start(state)
        self.assertEqual(planner.on_observation(state, "epoch")["type"], "UNEQUIP_TORCH")

    def test_dusk_without_torch_keeps_searching_for_materials(self):
        planner = SurvivalPlanner()
        state = observation(phase="dusk", seconds_until_night=168,
                            seconds_until_day=228,
                            inventory={"counts": {"cutgrass": 0, "twigs": 2,
                                                  "torch": 0}, "hand": None})
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "MOVE_TO_POINT")
        self.assertEqual(planner.reason, "searching_grass")

    def test_collects_nearby_food_before_distant_grass(self):
        planner = SurvivalPlanner()
        state = observation(local_entities=[
            {"guid": 75, "prefab": "grass", "ready": True, "dx": 12, "dz": 0},
            {"guid": 76, "prefab": "berrybush", "ready": True, "dx": 1, "dz": 0},
        ], inventory={"counts": {"cutgrass": 0, "twigs": 2, "torch": 0,
                                "berries": 2, "carrot": 1, "seeds": 2},
                      "food_ready_hunger": 40.625, "hand": None})
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "PICK_TARGET")
        self.assertEqual(choice["target_prefab"], "berrybush")

    def test_nearby_mixed_area_stays_together_before_distant_targets(self):
        planner = SurvivalPlanner()
        state = observation(local_entities=[
            {"guid": 101, "prefab": "grass", "kind": "harvest", "ready": True,
             "dx": 3, "dz": 0},
            {"guid": 102, "prefab": "grass", "kind": "harvest", "ready": True,
             "dx": 4, "dz": 1},
            {"guid": 103, "prefab": "grass", "kind": "harvest", "ready": True,
             "dx": 5, "dz": -1},
            {"guid": 104, "prefab": "sapling", "kind": "harvest", "ready": True,
             "dx": 5.5, "dz": 0},
            {"guid": 105, "prefab": "flint", "kind": "pickup", "ready": True,
             "dx": 4.5, "dz": 0},
            {"guid": 106, "prefab": "sapling", "kind": "harvest", "ready": True,
             "dx": 14, "dz": 0},
        ], inventory={"counts": {"cutgrass": 3, "twigs": 0, "torch": 0},
                      "free_slots": 12})
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "COLLECT_AREA")
        self.assertEqual({item["guid"] for item in choice["items"]},
                         {101, 102, 103, 104, 105})
        self.assertEqual({item["kind"] for item in choice["items"]},
                         {"harvest", "pickup"})
        planner.record_command(1, choice)
        self.assertIsNone(planner.on_observation(observation(
            local_entities=state["local_entities"],
            execution={"epoch": "epoch", "id": 1, "status": "started"}), "epoch"))
        followup = planner.on_observation(observation(
            local_entities=[state["local_entities"][5]],
            inventory={"counts": {"cutgrass": 6, "twigs": 1, "flint": 1, "torch": 0},
                       "free_slots": 12},
            execution={"epoch": "epoch", "id": 1, "status": "completed",
                       "picked_count": 5, "inventory_delta": 5,
                       "cluster_end_reason": "CLUSTER_EXHAUSTED"}), "epoch")
        self.assertEqual(planner.picked_items, 5)
        self.assertEqual(followup["target_guid"], 106)

    def test_frog_away_from_berry_route_allows_harvest(self):
        planner = SurvivalPlanner()
        state = observation(local_entities=[
            {"guid": 201, "prefab": "berrybush", "kind": "harvest", "ready": True,
             "dx": 4, "dz": 0},
        ], visible_hazards=[{"prefab": "frog", "dx": 0, "dz": 7}])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "PICK_TARGET")
        self.assertEqual(choice["target_guid"], 201)

    def test_frog_on_berry_route_blocks_harvest(self):
        planner = SurvivalPlanner()
        state = observation(local_entities=[
            {"guid": 201, "prefab": "berrybush", "kind": "harvest", "ready": True,
             "dx": 7, "dz": 0},
        ], visible_hazards=[{"prefab": "frog", "dx": 6, "dz": 0}])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "MOVE_TO_POINT")
        self.assertTrue(any("UNSAFE_HAZARD_ROUTE" in event for event in planner.events))

    def test_frog_route_remains_avoided_after_short_escape(self):
        planner = SurvivalPlanner()
        first = observation(local_entities=[
            {"guid": 201, "prefab": "berrybush", "kind": "harvest", "ready": True,
             "dx": 7, "dz": 0},
        ], visible_hazards=[{"prefab": "frog", "dx": 6, "dz": 0}])
        planner.start(first)
        later = observation(x=-6, local_entities=[
            {"guid": 201, "prefab": "berrybush", "kind": "harvest", "ready": True,
             "dx": 13, "dz": 0},
        ], visible_hazards=[])
        self.assertTrue(planner._route_near_hazard(later, later["local_entities"][0]))

    def test_direct_pick_for_grass_visible_twelve_units_away(self):
        planner = SurvivalPlanner()
        state = observation(local_entities=[
            {"guid": 75, "prefab": "grass", "ready": True, "dx": 12, "dz": 0}])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "PICK_TARGET")
        self.assertEqual(choice["target_guid"], 75)

    def test_loose_twigs_are_picked_up_for_torch(self):
        planner = SurvivalPlanner()
        planner.start(observation())
        choice = planner.on_observation(observation(
            inventory={"counts": {"cutgrass": 2, "twigs": 1, "berries": 0, "torch": 0}},
            local_entities=[{"guid": 73, "prefab": "twigs", "ready": True,
                             "dx": 1, "dz": 0}]), "epoch")
        self.assertEqual(choice["type"], "PICKUP_TARGET")
        self.assertEqual(choice["target_prefab"], "twigs")

    def test_picks_nearby_flint_while_gathering_other_supplies(self):
        planner = SurvivalPlanner()
        state = observation(local_entities=[
            {"guid": 76, "prefab": "grass", "ready": True, "dx": 4, "dz": 0},
            {"guid": 77, "prefab": "flint", "ready": True, "dx": 1, "dz": 0},
        ])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "PICKUP_TARGET")
        self.assertEqual(choice["target_prefab"], "flint")

    def test_picks_flint_three_units_away_before_grass_four_units_away(self):
        planner = SurvivalPlanner()
        state = observation(local_entities=[
            {"guid": 80, "prefab": "grass", "ready": True, "dx": 4, "dz": 0},
            {"guid": 81, "prefab": "flint", "ready": True, "dx": 3, "dz": 0},
        ])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "PICKUP_TARGET")
        self.assertEqual(choice["target_prefab"], "flint")

    def test_picks_morsel_but_does_not_treat_it_as_ready_food(self):
        planner = SurvivalPlanner()
        state = observation(
            inventory={"counts": {"cutgrass": 2, "twigs": 2,
                                  "berries": 0, "torch": 2, "flint": 2,
                                  "smallmeat": 0}},
            local_entities=[{"guid": 78, "prefab": "smallmeat", "ready": True,
                             "dx": 1, "dz": 0}])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "PICKUP_TARGET")
        self.assertEqual(choice["target_prefab"], "smallmeat")
        after = observation(inventory={"counts": {"cutgrass": 2, "twigs": 2,
            "berries": 0, "torch": 2, "flint": 2, "smallmeat": 1}},
            execution={"epoch": "epoch", "id": 1, "status": "completed",
                       "inventory_delta": 1})
        planner.record_command(1, choice)
        self.assertEqual(planner.on_observation(after, "epoch")["type"], "MOVE_TO_POINT")

    def test_collects_flint_five_units_away_when_inventory_is_empty(self):
        planner = SurvivalPlanner()
        state = observation(
            inventory={"counts": {"cutgrass": 2, "twigs": 2,
                                  "berries": 2, "torch": 2,
                                  "flint": 0, "smallmeat": 3}},
            local_entities=[{"guid": 79, "prefab": "flint", "ready": True,
                             "dx": 5, "dz": 0}])
        planner.start(state)
        self.assertEqual(planner.on_observation(state, "epoch")["type"], "PICKUP_TARGET")
        full = observation(inventory={"counts": {**state["inventory"]["counts"], "flint": 6}},
                           local_entities=state["local_entities"])
        self.assertEqual(planner.on_observation(full, "epoch")["type"], "MOVE_TO_POINT")

    def test_gathers_carrot_when_food_is_low(self):
        planner = SurvivalPlanner()
        state = observation(
            inventory={"counts": {"cutgrass": 2, "twigs": 2, "berries": 0,
                                  "carrot": 0, "seeds": 0, "torch": 2}},
            local_entities=[{"guid": 74, "prefab": "carrot_planted", "ready": True,
                             "dx": 1, "dz": 0}])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "PICK_TARGET")
        self.assertEqual(choice["goal"], "food")

    def test_harvest_target_two_units_away_uses_one_action(self):
        planner = SurvivalPlanner()
        state = observation(local_entities=[
            {"guid": 95, "prefab": "berrybush", "ready": True,
             "dx": 2, "dz": 0}])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "PICK_TARGET")
        self.assertEqual(choice["target_prefab"], "berrybush")

    def test_prepares_second_torch_before_night(self):
        planner = SurvivalPlanner()
        state = observation(inventory={"counts": {"cutgrass": 2, "twigs": 2,
            "berries": 0, "torch": 1}})
        planner.start(state)
        self.assertEqual(planner.on_observation(state, "epoch")["type"], "CRAFT_TORCH")

    def test_night_fuel_shortfall_triggers_spare_torch(self):
        planner = SurvivalPlanner()
        state = observation(
            phase="night", in_light=True, seconds_until_day=90,
            inventory={"counts": {"cutgrass": 2, "twigs": 2,
                                  "berries": 0, "torch": 0},
                       "hand": "torch", "hand_fuel_percent": 0.7,
                       "hand_fuel_seconds": 65})
        planner.start(state)
        self.assertEqual(planner.on_observation(state, "epoch")["type"], "CRAFT_TORCH")

    def test_two_nearly_spent_torches_do_not_cover_night(self):
        planner = SurvivalPlanner()
        state = observation(
            phase="dusk", seconds_until_day=75, seconds_until_night=15,
            inventory={"counts": {"cutgrass": 2, "twigs": 2,
                                  "berries": 0, "torch": 2},
                       "hand": None, "torch_ready_seconds": 18})
        planner.start(state)
        self.assertEqual(planner.on_observation(state, "epoch")["type"], "CRAFT_TORCH")

    def test_equips_before_night_and_interrupts_long_move(self):
        planner = SurvivalPlanner()
        supplies = {"cutgrass": 8, "twigs": 8, "berries": 4, "torch": 2}
        inventory = {"counts": supplies, "hand": None,
                     "torch_ready_seconds": 150, "food_ready_hunger": 37.5}
        daytime = observation(inventory=inventory)
        planner.start(daytime)
        choice = planner.on_observation(daytime, "epoch")
        self.assertEqual(choice["type"], "MOVE_TO_POINT")
        planner.record_command(1, choice)
        dusk = observation(phase="dusk", seconds_until_night=4,
                           seconds_until_day=64, inventory=inventory,
                           movement={"epoch": "epoch", "id": 1,
                                     "status": "started"})
        stop = planner.on_observation(dusk, "epoch")
        self.assertEqual(stop["type"], "STOP")
        self.assertEqual(stop["goal"], "light")
        planner.record_command(2, stop)
        dusk["movement"]["status"] = "stopped"
        self.assertEqual(planner.on_observation(dusk, "epoch")["type"], "EQUIP_TORCH")
        self.assertEqual(planner.failed, 0)

    def test_food_reserve_uses_hunger_value_instead_of_item_count(self):
        base = {"cutgrass": 8, "twigs": 8, "berries": 0,
                "seeds": 2, "carrot": 0, "torch": 2}
        berry = {"guid": 82, "prefab": "berrybush", "ready": True,
                 "dx": 1, "dz": 0}
        planner = SurvivalPlanner()
        low = observation(inventory={"counts": base, "hand": None,
                                     "torch_ready_seconds": 150,
                                     "food_ready_hunger": 9.375},
                          local_entities=[berry])
        planner.start(low)
        self.assertEqual(planner.on_observation(low, "epoch")["type"], "PICK_TARGET")

        planner = SurvivalPlanner()
        adequate = observation(inventory={"counts": {**base, "seeds": 0, "carrot": 2},
                                          "hand": None, "torch_ready_seconds": 150,
                                          "food_ready_hunger": 25},
                               local_entities=[berry])
        planner.start(adequate)
        self.assertEqual(planner.on_observation(adequate, "epoch")["type"], "PICK_TARGET")

    def test_absent_grass_does_not_block_visible_food(self):
        planner = SurvivalPlanner()
        state = observation(
            inventory={"counts": {"cutgrass": 0, "twigs": 8, "torch": 0},
                       "hand": None, "food_ready_hunger": 0},
            local_entities=[{"guid": 94, "prefab": "carrot_planted",
                             "ready": True, "dx": 1, "dz": 0}])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "PICK_TARGET")
        self.assertEqual(choice["target_prefab"], "carrot_planted")

    def test_search_heading_continues_through_empty_area(self):
        planner = SurvivalPlanner()
        state = observation()
        planner.start(state)
        planner.heading = (6, 0)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual((choice["x"], choice["z"]), (6, 0))
        self.assertEqual(planner.reason, "searching_grass")

    def test_exploration_takes_long_safe_leg(self):
        planner = SurvivalPlanner()
        state = observation(frontier=[
            {"dx": 36, "dz": 0, "passable": True, "marsh_steps": 0},
            {"dx": 6, "dz": 0, "passable": True, "marsh_steps": 0},
        ])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual((choice["x"], choice["z"]), (36, 0))

    def test_exploration_avoids_marsh_and_tentacle_ahead(self):
        planner = SurvivalPlanner()
        state = observation(frontier=[
            {"dx": 36, "dz": 0, "passable": True, "marsh_steps": 9},
            {"dx": 0, "dz": 18, "passable": True, "marsh_steps": 0},
        ], visible_hazards=[{"prefab": "tentacle", "dx": 12, "dz": 0}])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual((choice["x"], choice["z"]), (0, 18))

    def test_first_two_days_never_fall_back_to_marsh_frontier(self):
        planner = SurvivalPlanner()
        state = observation(cycles=0, frontier=[
            {"dx": 18, "dz": 0, "passable": True, "marsh_steps": 2,
             "endpoint_marsh": True}])
        planner.start(state)
        self.assertIsNone(planner.on_observation(state, "epoch"))
        self.assertEqual(planner.reason, "no_safe_frontier")

    def test_safety_episode_waits_for_stable_recovery(self):
        planner = SurvivalPlanner()
        planner.start(observation())
        danger = observation(visible_threat_within_8=True,
            nearest_threat={"prefab": "frog", "dx": 3, "dz": 0})
        planner._remember(danger)
        self.assertEqual(planner.safety_mode, "EVADE")
        planner._remember(observation())
        self.assertEqual(planner.safety_mode, "RECOVER")
        self.assertIsNone(planner._choose(observation()))
        planner.safety_clear_since = time.monotonic() - 3
        planner._remember(observation())
        self.assertEqual(planner.safety_mode, "NORMAL")

    def test_recovery_continues_moving_away_from_nearby_frog(self):
        planner = SurvivalPlanner()
        planner.start(observation())
        planner._remember(observation(visible_threat_within_8=True,
            nearest_threat={"prefab": "frog", "dx": 3, "dz": 0}))
        near = observation(visible_hazards=[
            {"prefab": "frog", "dx": 5, "dz": 0, "distance_sq": 25}],
            frontier=[{"dx": -18, "dz": 0, "passable": True, "marsh_steps": 0}])
        planner._remember(near)
        self.assertEqual(planner.safety_mode, "RECOVER")
        choice = planner._choose(near)
        self.assertEqual(choice["type"], "MOVE_TO_POINT")
        self.assertTrue(choice["escape"])

    def test_escape_uses_long_leg_and_remembers_danger(self):
        planner = SurvivalPlanner()
        danger = observation(visible_threat_within_8=True,
            nearest_threat={"prefab": "tentacle", "dx": 4, "dz": 0},
            visible_hazards=[{"prefab": "tentacle", "dx": 4, "dz": 0}],
            frontier=[{"dx": -18, "dz": 0, "passable": True, "marsh_steps": 0},
                      {"dx": 0, "dz": 6, "passable": True, "marsh_steps": 0}])
        planner.start(danger)
        escape = planner.on_observation(danger, "epoch")
        self.assertEqual((escape["x"], escape["z"]), (-18, 0))
        self.assertTrue(escape["escape"])
        after = observation(x=-18, visible_hazards=[], frontier=[
            {"dx": 36, "dz": 0, "passable": True, "marsh_steps": 0},
            {"dx": 0, "dz": 18, "passable": True, "marsh_steps": 0},
        ])
        planner._remember(after)
        self.assertTrue(planner._route_near_hazard(after, after["frontier"][0]))
        self.assertFalse(planner._route_near_hazard(after, after["frontier"][1]))

    def test_leaves_marsh_before_collecting(self):
        planner = SurvivalPlanner()
        state = observation(on_marsh=True, frontier=[
            {"dx": 0, "dz": 6, "passable": True, "marsh_steps": 1,
             "endpoint_marsh": False},
            {"dx": 18, "dz": 0, "passable": True, "marsh_steps": 5,
             "endpoint_marsh": True},
        ], local_entities=[{"guid": 99, "prefab": "grass", "kind": "harvest",
                            "ready": True, "dx": 1, "dz": 0}])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual((choice["x"], choice["z"]), (0, 6))

    def test_blocked_leg_changes_direction(self):
        planner = SurvivalPlanner()
        state = observation(frontier=[
            {"dx": 36, "dz": 0, "passable": True, "marsh_steps": 0},
            {"dx": 0, "dz": 18, "passable": True, "marsh_steps": 0},
        ])
        planner.start(state)
        first = planner.on_observation(state, "epoch")
        self.assertEqual((first["x"], first["z"]), (36, 0))
        planner.record_command(1, first)
        after = observation(x=2, frontier=state["frontier"],
                            movement={"epoch": "epoch", "id": 1,
                                      "status": "blocked"})
        next_move = planner.on_observation(after, "epoch")
        self.assertEqual((next_move["x"], next_move["z"]), (2, 18))

    def test_critical_hunger_eats_before_daylight_torch_crafting(self):
        planner = SurvivalPlanner()
        state = observation(
            vitals={"health": {"current": 150}, "hunger": {"current": 20}},
            inventory={"counts": {"cutgrass": 2, "twigs": 2, "carrot": 1,
                                  "torch": 0}, "hand": None,
                       "food_ready_hunger": 12.5, "torch_ready_seconds": 0})
        planner.start(state)
        self.assertEqual(planner.on_observation(state, "epoch")["type"], "EAT_FOOD")

    def test_critical_hunger_seeks_food_before_other_materials(self):
        planner = SurvivalPlanner()
        state = observation(
            vitals={"health": {"current": 150}, "hunger": {"current": 20}},
            inventory={"counts": {"cutgrass": 0, "twigs": 0, "torch": 0},
                       "hand": None, "food_ready_hunger": 0,
                       "torch_ready_seconds": 0},
            local_entities=[{"guid": 88, "prefab": "carrot_planted", "ready": True,
                             "dx": 1, "dz": 0},
                            {"guid": 89, "prefab": "grass", "ready": True,
                             "dx": 1, "dz": 1}])
        planner.start(state)
        self.assertEqual(planner.on_observation(state, "epoch")["target_prefab"],
                         "carrot_planted")

    def test_axe_chop_and_loose_log_follow_survival_reserves(self):
        planner = SurvivalPlanner()
        supplies = {"cutgrass": 10, "twigs": 10, "berries": 0,
                    "torch": 2, "flint": 1, "axe": 0, "log": 0}
        inventory = {"counts": supplies, "hand": None,
                     "torch_ready_seconds": 150, "food_ready_hunger": 75}
        tree = {"guid": 83, "prefab": "evergreen", "ready": True,
                "dx": 5, "dz": 0}
        ready = observation(cycles=1, seconds_until_night=60,
                            vitals={"health": {"current": 150},
                                    "hunger": {"current": 120},
                                    "sanity": {"current": 200, "max": 200}},
                            inventory=inventory, local_entities=[tree])
        planner.start(ready)
        choice = planner.on_observation(ready, "epoch")
        self.assertEqual(choice["type"], "CRAFT_AXE")
        planner.record_command(1, choice)

        with_axe = observation(cycles=1, seconds_until_night=55,
            vitals={"health": {"current": 150}, "hunger": {"current": 120},
                    "sanity": {"current": 200, "max": 200}},
            inventory={"counts": {**supplies, "twigs": 9, "flint": 0},
                       "hand": "axe", "torch_ready_seconds": 150,
                       "food_ready_hunger": 75},
            local_entities=[tree],
            utility={"epoch": "epoch", "id": 1, "status": "completed"})
        choice = planner.on_observation(with_axe, "epoch")
        self.assertEqual(choice["type"], "FELL_TREE")
        self.assertTrue(choice["behavior_id"].startswith("tree-"))
        planner.record_command(2, choice)
        midway = observation(**{**with_axe,
            "execution": {"epoch": "epoch", "id": 2,
                          "status": "started", "work_delta": 1}})
        self.assertIsNone(planner.on_observation(midway, "epoch"))
        log = {"guid": 84, "prefab": "log", "ready": True,
               "dx": 1, "dz": 0}
        felled = observation(**{**with_axe, "local_entities": [log],
            "execution": {"epoch": "epoch", "id": 2,
                          "status": "completed", "work_delta": 3,
                          "tree_felled": True}})
        self.assertEqual(planner.on_observation(felled, "epoch")["type"], "PICKUP_TARGET")

    def test_axe_task_waits_when_light_or_material_reserve_is_short(self):
        planner = SurvivalPlanner()
        state = observation(
            cycles=1, seconds_until_night=60,
            inventory={"counts": {"cutgrass": 2, "twigs": 2,
                                  "berries": 0, "torch": 1,
                                  "flint": 1, "axe": 0, "log": 0},
                       "hand": None, "torch_ready_seconds": 20,
                       "food_ready_hunger": 75})
        planner.start(state)
        self.assertNotEqual(planner.on_observation(state, "epoch")["type"], "CRAFT_AXE")

    def test_meat_cooking_uses_safe_daytime_fire_chain(self):
        planner = SurvivalPlanner()
        supplies = {"cutgrass": 10, "twigs": 10, "torch": 2,
                    "smallmeat": 1, "log": 6, "axe": 1}
        inventory = {"counts": supplies, "hand": None,
                     "torch_ready_seconds": 150, "food_ready_hunger": 75}
        state = observation(cycles=1, seconds_until_night=80,
                            inventory=inventory)
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "BUILD_CAMPFIRE")
        planner.record_command(1, choice)

        fire = {"guid": 91, "dx": 1, "dz": 0, "fuel_seconds": 80}
        with_fire = observation(cycles=1, seconds_until_night=75,
            inventory={**inventory, "counts": {**supplies, "cutgrass": 7, "log": 4}},
            nearby_fires=[fire],
            utility={"epoch": "epoch", "id": 1, "status": "completed"})
        choice = planner.on_observation(with_fire, "epoch")
        self.assertEqual(choice["type"], "COOK_AT")
        self.assertEqual(choice["target_guid"], 91)
        planner.record_command(2, choice)
        cooked = observation(cycles=1, seconds_until_night=70,
            inventory={**inventory, "counts": {**supplies, "smallmeat": 0,
                                               "cookedsmallmeat": 1,
                                               "cutgrass": 7, "log": 4},
                       "food_ready_hunger": 87.5},
            nearby_fires=[fire],
            utility={"epoch": "epoch", "id": 2, "status": "completed"})
        self.assertNotEqual(planner.on_observation(cooked, "epoch")["type"], "COOK_AT")

    def test_fire_gets_fuel_before_cooking_if_it_is_running_low(self):
        planner = SurvivalPlanner()
        state = observation(cycles=1, seconds_until_night=80,
            inventory={"counts": {"cutgrass": 10, "twigs": 10,
                                  "torch": 2, "smallmeat": 1, "log": 4},
                       "hand": None, "torch_ready_seconds": 150,
                       "food_ready_hunger": 75},
            nearby_fires=[{"guid": 92, "dx": 1, "dz": 0,
                           "fuel_seconds": 8}])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "ADD_FUEL")
        self.assertEqual(choice["target_guid"], 92)

    def test_uses_existing_light_at_night(self):
        planner = SurvivalPlanner()
        state = observation(
            phase="night", in_light=True,
            inventory={"counts": {"cutgrass": 0, "twigs": 0,
                                  "berries": 0, "torch": 1}, "hand": None})
        planner.start(state)
        self.assertIsNone(planner.on_observation(state, "epoch"))

    def test_dusk_explores_for_food_with_torch_ready(self):
        planner = SurvivalPlanner()
        state = observation(
            phase="dusk", phase_progress=0.2,
            inventory={"counts": {"cutgrass": 0, "twigs": 0,
                                  "berries": 0, "torch": 1},
                       "hand": None})
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "MOVE_TO_POINT")
        self.assertEqual(choice["goal"], "explore")

    def test_night_explores_when_torch_last_longer_than_the_night(self):
        planner = SurvivalPlanner()
        state = observation(
            phase="night", in_light=True,
            inventory={"counts": {"cutgrass": 0, "twigs": 0,
                                  "berries": 0, "torch": 1},
                       "hand": "torch", "hand_fuel_percent": 0.8},
            vitals={"health": {"current": 150}, "hunger": {"current": 100}})
        planner.start(state)
        self.assertEqual(planner.on_observation(state, "epoch")["type"], "MOVE_TO_POINT")

    def test_exploration_uses_long_walkable_waypoint(self):
        planner = SurvivalPlanner()
        state = observation(frontier=[{"dx": 18, "dz": 0, "passable": True},
                                      {"dx": 6, "dz": 0, "passable": True}])
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "MOVE_TO_POINT")
        self.assertEqual(choice["x"], 18)

    def test_collects_spear_and_beefalo_wool_from_survivor_loot(self):
        for prefab in ("spear", "beefalowool"):
            with self.subTest(prefab=prefab):
                planner = SurvivalPlanner()
                state = observation(local_entities=[
                    {"guid": 99, "prefab": prefab, "kind": "pickup",
                     "ready": True, "dx": 4, "dz": 0}],
                    inventory={"counts": {}, "free_slots": 12, "hand": None})
                planner.start(state)
                choice = planner.on_observation(state, "epoch")
                self.assertEqual(choice["type"], "PICKUP_TARGET")
                self.assertEqual(choice["target_prefab"], prefab)

    def test_grass_at_feet_precedes_twig_five_units_away(self):
        planner = SurvivalPlanner()
        state = observation(local_entities=[
            {"guid": 801, "prefab": "grass", "kind": "harvest", "ready": True,
             "dx": 1, "dz": 0, "marsh_steps": 0},
            {"guid": 802, "prefab": "twigs", "kind": "pickup", "ready": True,
             "dx": 5, "dz": 0, "marsh_steps": 0}],
            inventory={"counts": {"cutgrass": 2, "twigs": 0},
                       "free_slots": 12, "hand": None})
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "COLLECT_AREA")
        self.assertEqual(choice["items"][0]["guid"], 801)
        self.assertEqual({item["guid"] for item in choice["items"]}, {801, 802})

    def test_loot_cluster_uses_one_command_for_nearby_items(self):
        planner = SurvivalPlanner()
        supplies = {"cutgrass": 8, "twigs": 8, "torch": 2}
        first = {"guid": 101, "prefab": "cutstone", "kind": "pickup",
                 "ready": True, "dx": 1, "dz": 0}
        second = {"guid": 102, "prefab": "cutstone", "kind": "pickup",
                  "ready": True, "dx": 2, "dz": 0}
        tool = {"guid": 103, "prefab": "pickaxe", "kind": "pickup",
                "ready": True, "dx": 3, "dz": 0}
        inventory = {"counts": supplies, "free_slots": 10,
                     "torch_ready_seconds": 150, "food_ready_hunger": 75}
        before = observation(local_entities=[first, second, tool], inventory=inventory)
        planner.start(before)
        choice = planner.on_observation(before, "epoch")
        self.assertEqual(choice["type"], "COLLECT_AREA")
        self.assertEqual({item["guid"] for item in choice["items"]}, {101, 102, 103})
        behavior_id = choice["behavior_id"]
        planner.record_command(1, choice)
        self.assertIsNone(planner.on_observation(observation(
            local_entities=[first, second, tool], inventory=inventory,
            execution={"epoch": "epoch", "id": 1,
                       "status": "started", "picked_count": 1}), "epoch"))
        after = observation(local_entities=[],
                            inventory={**inventory, "counts": {**supplies,
                                       "cutstone": 2, "pickaxe": 1}, "free_slots": 8},
                            execution={"epoch": "epoch", "id": 1,
                                       "status": "completed", "inventory_delta": 3,
                                       "picked_count": 3,
                                       "cluster_end_reason": "CLUSTER_EXHAUSTED"})
        planner.on_observation(after, "epoch")
        self.assertIsNone(planner.collect_area)
        self.assertEqual(planner.picked_items, 3)
        self.assertTrue(any(behavior_id in event and "CLUSTER_EXHAUSTED" in event
                            for event in planner.events))
        self.assertTrue(any("chosen=" in event and "top=[" in event
                            for event in planner.events))

    def test_distant_area_approaches_and_collects_in_one_command(self):
        planner = SurvivalPlanner()
        supplies = {"cutgrass": 8, "twigs": 8, "torch": 2}
        inventory = {"counts": supplies, "free_slots": 10,
                     "torch_ready_seconds": 150, "food_ready_hunger": 75}
        first = {"guid": 104, "prefab": "cutstone", "kind": "pickup",
                 "ready": True, "dx": 10, "dz": 0}
        second = {"guid": 105, "prefab": "pickaxe", "kind": "pickup",
                  "ready": True, "dx": 11, "dz": 0}
        state = observation(local_entities=[first, second], inventory=inventory)
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "COLLECT_AREA")
        self.assertEqual({item["guid"] for item in choice["items"]}, {104, 105})
        self.assertIsNotNone(choice["behavior_id"])

    def test_loot_cluster_interruption_keeps_items_already_collected(self):
        planner = SurvivalPlanner()
        items = [{"guid": guid, "prefab": "cutstone", "kind": "pickup",
                  "ready": True, "dx": guid - 110, "dz": 0}
                 for guid in (111, 112)]
        state = observation(local_entities=items,
                            inventory={"counts": {"cutgrass": 8, "twigs": 8,
                                                  "torch": 2}, "free_slots": 10,
                                       "torch_ready_seconds": 150,
                                       "food_ready_hunger": 75})
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        self.assertEqual(choice["type"], "COLLECT_AREA")
        planner.record_command(1, choice)
        interrupted = observation(local_entities=[],
            execution={"epoch": "epoch", "id": 1,
                       "status": "interrupted_threat", "picked_count": 1,
                       "inventory_delta": 1,
                       "cluster_end_reason": "SAFETY_INTERRUPT"})
        planner.on_observation(interrupted, "epoch")
        self.assertEqual(planner.picked_items, 1)
        self.assertIsNone(planner.collect_area)
        self.assertEqual(planner.failed, 0)

    def test_long_walk_interrupts_to_collect_new_ground_loot(self):
        planner = SurvivalPlanner()
        planner.start(observation())
        walk = planner.on_observation(observation(), "epoch")
        planner.record_command(1, walk)
        loot = observation(local_entities=[
            {"guid": 99, "prefab": "spear", "kind": "pickup",
             "ready": True, "dx": 1, "dz": 0}],
            inventory={"counts": {}, "free_slots": 12, "hand": None},
            movement={"epoch": "epoch", "id": 1, "status": "started"})
        stop = planner.on_observation(loot, "epoch")
        self.assertEqual(stop["type"], "STOP")
        planner.record_command(2, stop)
        loot["movement"]["status"] = "stopped"
        choice = planner.on_observation(loot, "epoch")
        self.assertEqual(choice["type"], "PICKUP_TARGET")
        self.assertEqual(choice["target_prefab"], "spear")

    def test_night_does_not_explore_to_replenish_torch_materials(self):
        planner = SurvivalPlanner()
        state = observation(
            phase="night", in_light=True, seconds_until_day=60,
            inventory={"counts": {"cutgrass": 0, "twigs": 0, "torch": 0},
                       "hand": "torch", "hand_fuel_seconds": 40,
                       "torch_ready_seconds": 40})
        planner.start(state)
        self.assertIsNone(planner.on_observation(state, "epoch"))
        self.assertEqual(planner.reason, "night_waiting_in_light")

    def test_craft_autoequip_counts_as_success(self):
        planner = SurvivalPlanner()
        before = observation(inventory={"counts": {"cutgrass": 2,
            "twigs": 2, "berries": 0, "torch": 0}})
        planner.start(before)
        planner.record_command(1, planner.on_observation(before, "epoch"))
        after = observation(inventory={"counts": {"cutgrass": 0,
            "twigs": 0, "berries": 0, "torch": 0}, "hand": "torch"},
            utility={"epoch": "epoch", "id": 1, "status": "uncertain"})
        planner.on_observation(after, "epoch")
        self.assertEqual(planner.completed, 1)
        self.assertEqual(planner.failed, 0)

    def test_explores_toward_unseen_area(self):
        planner = SurvivalPlanner()
        state = observation(inventory={"counts": {"cutgrass": 2, "twigs": 2,
            "berries": 2, "torch": 2}})
        planner.start(state)
        planner.seen_cells.update(planner._cells_visible_from(6, 0))
        choice = planner.on_observation(state, "epoch")
        self.assertEqual((choice["x"], choice["z"]), (0, 6))

    def test_spoiled_food_does_not_count_as_edible(self):
        planner = SurvivalPlanner()
        state = observation(
            inventory={"counts": {"cutgrass": 2, "twigs": 2,
                                  "berries": 1, "carrot": 0, "seeds": 0, "torch": 2},
                       "edible_counts": {"berries": 0, "carrot": 0, "seeds": 0}},
            local_entities=[{"guid": 75, "prefab": "carrot", "ready": True,
                             "dx": 1, "dz": 0}],
            vitals={"health": {"current": 150}, "hunger": {"current": 100}})
        planner.start(state)
        self.assertEqual(planner.on_observation(state, "epoch")["type"], "PICKUP_TARGET")

    def test_failed_craft_waits_before_retrying(self):
        planner = SurvivalPlanner()
        state = observation(inventory={"counts": {"cutgrass": 2, "twigs": 2,
            "berries": 0, "torch": 0}})
        planner.start(state)
        choice = planner.on_observation(state, "epoch")
        planner.record_command(1, choice)
        failed = observation(inventory=state["inventory"],
            utility={"epoch": "epoch", "id": 1, "status": "missing_torch_materials"})
        self.assertIsNone(planner.on_observation(failed, "epoch"))
        self.assertEqual(planner.reason, "retry_wait_craft_torch")

    def test_blocked_frontier_changes_direction(self):
        planner = SurvivalPlanner()
        planner.start(observation())
        first = planner.on_observation(observation(), "epoch")
        self.assertEqual((first["x"], first["z"]), (6, 0))
        planner.record_command(1, first)
        second = planner.on_observation(observation(
            movement={"epoch": "epoch", "id": 1, "status": "blocked",
                      "progress": 0.2, "distance_to_goal": 4.8}), "epoch")
        self.assertEqual((second["x"], second["z"]), (0, 6))

    def test_local_escape_defers_bridge_action_after_lost_report(self):
        planner = SurvivalPlanner()
        planner.start(observation())
        first = planner.on_observation(observation(), "epoch")
        planner.record_command(1, first)
        planner.action_started_at -= 13
        threat = {"dx": 4, "dz": 0, "prefab": "frog"}
        local_move = {"epoch": "local", "id": 1, "status": "started"}
        self.assertIsNone(planner.on_observation(observation(
            visible_threat_within_8=True, nearest_threat=threat,
            movement=local_move), "epoch"))
        self.assertEqual(planner.reason, "local_escape_running")
        self.assertEqual(planner.failed, 1)
        local_move["status"] = "arrived"
        choice = planner.on_observation(observation(
            visible_threat_within_8=True, nearest_threat=threat,
            movement=local_move), "epoch")
        self.assertEqual(choice["goal"], "avoid_threat")

    def test_first_night_result_tracks_actual_light(self):
        planner = SurvivalPlanner()
        planner.start(observation())
        planner.on_observation(observation(phase="night", in_light=True), "epoch")
        planner.on_observation(observation(phase="night", in_light=False), "epoch")
        planner.on_observation(observation(phase="day"), "epoch")
        status = planner.status()
        self.assertEqual(status["first_night_result"], "survived_with_darkness")
        self.assertEqual(status["night_light_samples"], 1)
        self.assertEqual(status["night_dark_samples"], 1)

    def test_death_ends_continuous_mode(self):
        planner = SurvivalPlanner()
        planner.start(observation())
        dead = observation(vitals={"health": {"current": 0},
                                   "hunger": {"current": 60}})
        self.assertIsNone(planner.on_observation(dead, "epoch"))
        self.assertFalse(planner.enabled)
        self.assertEqual(planner.status()["first_night_result"], "died")


if __name__ == "__main__":
    unittest.main()
