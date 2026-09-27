local G = GLOBAL
local URL = "http://127.0.0.1:8765/probe"
local SENSE_RADIUS = 8
local HAZARD_OBSERVE_RADIUS = 16
local FROG_DANGER_RADIUS_SQ = ((G.TUNING.FROG_TARGET_DIST or 4) + 0.5) ^ 2
local RESOURCE_RADIUS = 40
local MAX_LOCAL_ENTITIES = 64
local OBSERVED_PREFABS = {
    grass = true,
    sapling = true,
    berrybush = true,
    berrybush2 = true,
    berrybush_juicy = true,
    carrot_planted = true,
    flint = true,
    rocks = true,
    goldnugget = true,
    twigs = true,
    cutgrass = true,
    berries = true,
    berries_juicy = true,
    carrot = true,
    seeds = true,
    smallmeat = true,
    log = true,
    evergreen = true,
    evergreen_sparse = true,
    deciduoustree = true,
}
local HARVEST_PRODUCTS = {
    grass = "cutgrass",
    sapling = "twigs",
    berrybush = "berries",
    berrybush2 = "berries",
    berrybush_juicy = "berries_juicy",
    carrot_planted = "carrot",
}
local CHOP_PREFABS = {
    evergreen = true,
    evergreen_sparse = true,
    deciduoustree = true,
}
local THREAT_PREFABS = {
    frog = true,
    spider = true,
    hound = true,
    killerbee = true,
    tentacle = true,
    tallbird = true,
    leif = true,
    leif_sparse = true,
    birchnutdrake = true,
}

local function CountInventoryItem(inst, prefab)
    local count = 0
    local inventory = inst.components.inventory
    if inventory ~= nil then
        for _, item in G.pairs(inventory.itemslots) do
            if item.prefab == prefab then
                local stackable = item.components.stackable
                count = count + (stackable ~= nil and stackable:StackSize() or 1)
            end
        end
    end
    return count
end

local function CountOwnedItem(inst, prefab)
    local count = CountInventoryItem(inst, prefab)
    local inventory = inst.components.inventory
    local hand = inventory ~= nil and inventory:GetEquippedItem(G.EQUIPSLOTS.HANDS) or nil
    return count + (hand ~= nil and hand.prefab == prefab and 1 or 0)
end

local function CountFreshFood(inst, prefab)
    local count = 0
    local inventory = inst.components.inventory
    if inventory ~= nil then
        for _, item in G.pairs(inventory.itemslots) do
            if item.prefab == prefab and (item.components.perishable == nil
                or not item.components.perishable:IsSpoiled()) then
                local stackable = item.components.stackable
                count = count + (stackable ~= nil and stackable:StackSize() or 1)
            end
        end
    end
    return count
end

local SAFE_FOOD_PREFABS = {
    berries = true,
    berries_juicy = true,
    carrot = true,
    seeds = true,
    berries_cooked = true,
    berries_juicy_cooked = true,
    carrot_cooked = true,
    cookedsmallmeat = true,
}

local function ReadFoodReserve(inst)
    local hunger = 0
    local inventory = inst.components.inventory
    if inventory ~= nil then
        for _, item in G.pairs(inventory.itemslots) do
            local edible = item.components.edible
            local perishable = item.components.perishable
            if SAFE_FOOD_PREFABS[item.prefab] and edible ~= nil
                and (perishable == nil or not perishable:IsSpoiled()) then
                local stackable = item.components.stackable
                local count = stackable ~= nil and stackable:StackSize() or 1
                hunger = hunger + G.math.max(0, edible:GetHunger(inst)) * count
            end
        end
    end
    return hunger
end

local function ChooseSafeFood(inst)
    local inventory = inst.components.inventory
    local eater = inst.components.eater
    if inventory == nil or eater == nil then
        return nil
    end
    local hunger = inst.components.hunger
    local room = hunger ~= nil and G.math.max(0, hunger.max - hunger.current) or 150
    local best, best_score = nil, nil
    for _, item in G.pairs(inventory.itemslots) do
        local edible = item.components.edible
        local perishable = item.components.perishable
        if SAFE_FOOD_PREFABS[item.prefab] and edible ~= nil
            and (perishable == nil or not perishable:IsSpoiled())
            and eater:CanEat(item) then
            local gain = G.math.max(0, edible:GetHunger(inst))
            local freshness = perishable ~= nil and perishable:GetPercent() or 1
            local score = G.math.max(0, gain - room) * 100 + freshness
            if gain > 0 and (best_score == nil or score < best_score) then
                best, best_score = item, score
            end
        end
    end
    return best
end

local function TorchSeconds(item, equipped)
    local fueled = item ~= nil and item.components.fueled or nil
    if item == nil or item.prefab ~= "torch" or fueled == nil then
        return 0
    end
    local rain = G.TheWorld.state.precipitationrate or 0
    local rain_rate = 1 + (G.TUNING.TORCH_RAIN_RATE or 0) * rain
    local rate = fueled.rate or 1
    if equipped and fueled.rate_modifiers ~= nil then
        rate = rate * fueled.rate_modifiers:Get()
    else
        rate = G.math.max(rate, rain_rate)
    end
    return fueled.currentfuel / G.math.max(rate, 0.01)
end

local function ReadVitals(inst)
    local health = inst.components.health
    local hunger = inst.components.hunger
    local sanity = inst.components.sanity
    return {
        health = health ~= nil
            and {current = health.currenthealth, max = health:GetMaxWithPenalty()}
            or {status = "unknown"},
        hunger = hunger ~= nil
            and {current = hunger.current, max = hunger.max}
            or {status = "unknown"},
        sanity = sanity ~= nil
            and {current = sanity.current, max = sanity:GetMaxWithPenalty()}
            or {status = "unknown"},
    }
end

local function ReadInventory(inst)
    local inventory = inst.components.inventory
    local hand = inventory ~= nil and inventory:GetEquippedItem(G.EQUIPSLOTS.HANDS) or nil
    local fueled = hand ~= nil and hand.components.fueled or nil
    local torch_seconds = TorchSeconds(hand, true)
    if inventory ~= nil then
        for _, item in G.pairs(inventory.itemslots) do
            torch_seconds = torch_seconds + TorchSeconds(item, false)
        end
    end
    local counts = {}
    if inventory ~= nil then
        for _, item in G.pairs(inventory.itemslots) do
            local stackable = item.components.stackable
            counts[item.prefab] = (counts[item.prefab] or 0)
                + (stackable ~= nil and stackable:StackSize() or 1)
        end
    end
    return {
        counts = counts,
        free_slots = inventory ~= nil and inventory:GetNumSlots() - inventory:NumItems() or 0,
        edible_counts = {
            berries = CountFreshFood(inst, "berries"),
            berries_juicy = CountFreshFood(inst, "berries_juicy"),
            carrot = CountFreshFood(inst, "carrot"),
            seeds = CountFreshFood(inst, "seeds"),
            berries_cooked = CountFreshFood(inst, "berries_cooked"),
            berries_juicy_cooked = CountFreshFood(inst, "berries_juicy_cooked"),
            carrot_cooked = CountFreshFood(inst, "carrot_cooked"),
            cookedsmallmeat = CountFreshFood(inst, "cookedsmallmeat"),
        },
        hand = hand ~= nil and hand.prefab or nil,
        hand_fuel_percent = fueled ~= nil and fueled:GetPercent() or nil,
        hand_fuel_seconds = hand ~= nil and hand.prefab == "torch"
            and TorchSeconds(hand, true) or nil,
        torch_ready_seconds = torch_seconds,
        food_ready_hunger = ReadFoodReserve(inst),
    }
end

local FRONTIER_DIRECTIONS = {
    {36, 0}, {25.5, 25.5}, {0, 36}, {-25.5, 25.5},
    {-36, 0}, {-25.5, -25.5}, {0, -36}, {25.5, -25.5},
    {18, 0}, {12.7, 12.7}, {0, 18}, {-12.7, 12.7},
    {-18, 0}, {-12.7, -12.7}, {0, -18}, {12.7, -12.7},
    {6, 0}, {4.25, 4.25}, {0, 6}, {-4.25, 4.25},
    {-6, 0}, {-4.25, -4.25}, {0, -6}, {4.25, -4.25},
}

local function ReadRouteTerrain(x, z, dx, dz)
    local map = G.TheWorld.Map
    local steps = G.math.max(1, G.math.ceil(G.math.sqrt(dx * dx + dz * dz) / 2))
    local passable = true
    local marsh_steps = 0
    for step = 1, steps do
        local px, pz = x + dx * step / steps, z + dz * step / steps
        if not map:IsPassableAtPoint(px, 0, pz, false, true) then
            passable = false
        end
        if map:GetTileAtPoint(px, 0, pz) == G.WORLD_TILES.MARSH then
            marsh_steps = marsh_steps + 1
        end
    end
    return passable, marsh_steps
end

local function CanReachTargetOnFoot(inst, target)
    local tx, _, tz = target.Transform:GetWorldPosition()
    local map = G.TheWorld.Map
    return map:IsPassableAtPoint(tx, 0, tz, false, true)
        and not map:IsOceanAtPoint(tx, 0, tz, true)
end

local function ReadFrontier(x, z)
    local points = {}
    local map = G.TheWorld.Map
    for _, direction in G.ipairs(FRONTIER_DIRECTIONS) do
        local dx, dz = direction[1], direction[2]
        local passable, marsh_steps = ReadRouteTerrain(x, z, dx, dz)
        points[#points + 1] = {
            dx = dx,
            dz = dz,
            passable = passable,
            marsh_steps = marsh_steps,
            endpoint_marsh = map:GetTileAtPoint(x + dx, 0, z + dz)
                == G.WORLD_TILES.MARSH,
        }
    end
    return points
end

local function ReadLocalEntities(inst, x, z)
    local candidates = {}
    local entities = G.TheSim:FindEntities(x, 0, z, RESOURCE_RADIUS, nil,
        {"INLIMBO", "FX", "DECOR"})
    for _, entity in G.ipairs(entities) do
        if entity ~= inst and (OBSERVED_PREFABS[entity.prefab]
            or entity.components.inventoryitem ~= nil)
            and entity.Transform ~= nil and G.CanEntitySeeTarget(inst, entity) then
            local ex, _, ez = entity.Transform:GetWorldPosition()
            local dx, dz = ex - x, ez - z
            local ready = nil
            local kind = nil
            if CHOP_PREFABS[entity.prefab] and not entity:HasTag("burnt")
                and entity.components.workable ~= nil then
                ready = entity.components.workable:CanBeWorked()
                    and entity.components.workable:GetWorkAction() == G.ACTIONS.CHOP
                kind = "chop"
            elseif entity.components.pickable ~= nil then
                ready = entity.components.pickable:CanBePicked()
                kind = "harvest"
            elseif entity.components.inventoryitem ~= nil then
                ready = entity.components.inventoryitem.owner == nil
                    and entity.components.inventoryitem.canbepickedup
                kind = "pickup"
            end
            if ready then
                candidates[#candidates + 1] = {
                    guid = entity.GUID,
                    prefab = entity.prefab,
                    dx = dx,
                    dz = dz,
                    distance_sq = dx * dx + dz * dz,
                    ready = true,
                    kind = kind,
                }
            end
        end
    end
    G.table.sort(candidates, function(a, b)
        local a_tree = CHOP_PREFABS[a.prefab] and 1 or 0
        local b_tree = CHOP_PREFABS[b.prefab] and 1 or 0
        if a_tree ~= b_tree then
            return a_tree < b_tree
        end
        return a.distance_sq < b.distance_sq
    end)

    local nearby, included, seen_prefabs = {}, {}, {}
    local function Include(entity)
        local _, marsh_steps = ReadRouteTerrain(x, z, entity.dx, entity.dz)
        local tx, tz = x + entity.dx, z + entity.dz
        local map = G.TheWorld.Map
        local passable = map:IsPassableAtPoint(tx, 0, tz, false, true)
            and not map:IsOceanAtPoint(tx, 0, tz, true)
        nearby[#nearby + 1] = {
            guid = entity.guid,
            prefab = entity.prefab,
            dx = entity.dx,
            dz = entity.dz,
            ready = entity.ready,
            kind = entity.kind,
            passable = passable,
            marsh_steps = marsh_steps,
        }
        included[entity.guid] = true
    end
    for _, entity in G.ipairs(candidates) do
        if #nearby >= MAX_LOCAL_ENTITIES then
            break
        end
        if not seen_prefabs[entity.prefab] then
            seen_prefabs[entity.prefab] = true
            Include(entity)
        end
    end
    for _, entity in G.ipairs(candidates) do
        if #nearby >= MAX_LOCAL_ENTITIES then
            break
        end
        if not included[entity.guid] then
            Include(entity)
        end
    end
    return nearby, #candidates > MAX_LOCAL_ENTITIES
end

local function ReadNearbyFires(x, z)
    local fires = {}
    for _, entity in G.ipairs(G.TheSim:FindEntities(x, 0, z, SENSE_RADIUS,
        {"campfire"}, {"INLIMBO"})) do
        if entity.prefab == "campfire" and entity.components.fueled ~= nil
            and entity.components.burnable ~= nil
            and entity.components.burnable:IsBurning()
            and entity.components.cooker ~= nil then
            local ex, _, ez = entity.Transform:GetWorldPosition()
            local rate = G.math.max(entity.components.fueled.rate or 1, 0.01)
            fires[#fires + 1] = {
                guid = entity.GUID,
                dx = ex - x,
                dz = ez - z,
                fuel_seconds = entity.components.fueled.currentfuel / rate,
            }
        end
    end
    G.table.sort(fires, function(a, b)
        return a.dx * a.dx + a.dz * a.dz < b.dx * b.dx + b.dz * b.dz
    end)
    return fires
end

local CAMPFIRE_OFFSETS = {
    {2.5, 0}, {0, 2.5}, {-2.5, 0}, {0, -2.5},
    {1.8, 1.8}, {-1.8, 1.8}, {-1.8, -1.8}, {1.8, -1.8},
}

local function FindSafeCampfirePoint(inst)
    local recipe = G.GetValidRecipe("campfire")
    if recipe == nil then
        return nil
    end
    local x, _, z = inst.Transform:GetWorldPosition()
    for _, offset in G.ipairs(CAMPFIRE_OFFSETS) do
        local px, pz = x + offset[1], z + offset[2]
        local point = G.Vector3(px, 0, pz)
        if G.TheWorld.Map:CanDeployRecipeAtPoint(point, recipe, 0, inst) then
            local clear = true
            for _, entity in G.ipairs(G.TheSim:FindEntities(px, 0, pz, 5,
                nil, {"INLIMBO", "FX", "DECOR"})) do
                if entity ~= inst and entity.components.burnable ~= nil then
                    clear = false
                    break
                end
            end
            if clear then
                return point
            end
        end
    end
    return nil
end

local function ReadVisibleHazards(inst, radius)
    local x, _, z = inst.Transform:GetWorldPosition()
    local entities = G.TheSim:FindEntities(x, 0, z, radius, nil,
        {"INLIMBO", "FX", "DECOR"})
    local frog_visible = false
    local threat_visible = false
    local nearest_threat = nil
    local nearest_distance_sq = nil
    local hazards = {}
    for _, entity in G.ipairs(entities) do
        if THREAT_PREFABS[entity.prefab] and G.CanEntitySeeTarget(inst, entity) then
            local ex, _, ez = entity.Transform:GetWorldPosition()
            local dx, dz = ex - x, ez - z
            local distance_sq = dx * dx + dz * dz
            if entity.prefab == "frog" and distance_sq <= SENSE_RADIUS ^ 2 then
                frog_visible = true
            end
            local combat = entity.components.combat
            local targeting_player = combat ~= nil and combat.target == inst
            hazards[#hazards + 1] = {
                prefab = entity.prefab,
                dx = dx,
                dz = dz,
                distance_sq = distance_sq,
                targeting_player = targeting_player,
            }
            local immediate = targeting_player or (distance_sq <= SENSE_RADIUS ^ 2
                and (entity.prefab ~= "frog"
                    or distance_sq <= FROG_DANGER_RADIUS_SQ))
            if immediate and (nearest_distance_sq == nil
                or distance_sq < nearest_distance_sq) then
                threat_visible = true
                nearest_distance_sq = distance_sq
                nearest_threat = {
                    prefab = entity.prefab,
                    dx = dx,
                    dz = dz,
                    distance_sq = distance_sq,
                }
            end
        end
    end
    return frog_visible, threat_visible, nearest_threat, hazards
end

local function HasVisibleThreat(inst, radius)
    local _, threat_visible = ReadVisibleHazards(inst, radius)
    return threat_visible
end

local CLIENT_MOVE_NAMESPACE = "wilson_p0_probe"
local client_move = nil

AddClientModRPCHandler(CLIENT_MOVE_NAMESPACE, "move_start", function(epoch, id, x, z,
    action_name, target_guid)
    if G.TheWorld == nil or G.TheWorld.ismastersim then
        return
    end
    local player = G.ThePlayer
    local locomotor = player ~= nil and player.components.locomotor or nil
    if player == nil or player.prefab ~= "wilson" or locomotor == nil
        or G.type(epoch) ~= "string" or G.type(id) ~= "number"
        or G.type(x) ~= "number" or G.type(z) ~= "number" then
        G.print("[Wilson P0 client] move preview unavailable")
        return
    end
    local key = epoch .. ":" .. id
    if client_move ~= nil and client_move.key == key then
        return
    end
    local target = G.type(target_guid) == "number" and G.Ents[target_guid] or nil
    local action_type = action_name == "PICK" and G.ACTIONS.PICK
        or action_name == "PICKUP" and G.ACTIONS.PICKUP
        or action_name == "CHOP" and G.ACTIONS.CHOP or nil
    local action = target ~= nil and target:IsValid() and action_type ~= nil
        and G.BufferedAction(player, target, action_type)
        or G.BufferedAction(player, nil, G.ACTIONS.WALKTO, nil, G.Vector3(x, 0, z))
    if action_type ~= nil and target ~= nil and target:IsValid() then
        action.preview_cb = function()
            local controller = player.components.playercontroller
            if controller ~= nil then
                controller:RemoteActionButton(action, true)
            end
        end
    end
    local ok = G.pcall(locomotor.PreviewAction, locomotor, action, false)
    if ok then
        client_move = {key = key, owned_dest = locomotor.dest}
    end
    G.print("[Wilson P0 client] move id=" .. id .. " preview=" .. G.tostring(ok))
end)

AddClientModRPCHandler(CLIENT_MOVE_NAMESPACE, "move_stop", function(epoch, id)
    local player = G.ThePlayer
    local locomotor = player ~= nil and player.components.locomotor or nil
    local key = G.tostring(epoch) .. ":" .. G.tostring(id)
    if client_move ~= nil and client_move.key == key then
        if locomotor ~= nil and client_move.owned_dest ~= nil
            and locomotor.dest == client_move.owned_dest then
            locomotor:Stop()
        end
        client_move = nil
        G.print("[Wilson P0 client] move id=" .. G.tostring(id) .. " preview ended")
    end
end)

AddPlayerPostInit(function(inst)
    if G.TheWorld == nil or not G.TheWorld.ismastersim or inst.prefab ~= "wilson" then
        return
    end

    local seq = 0
    local pending_seq = nil
    local pending_since = nil
    local last_command_key = nil
    local command_ack = nil
    local active_pick = nil
    local active_move = nil
    local active_utility = nil
    local survival_seen = false
    local last_bridge_ok_at = nil
    local last_local_escape_at = nil
    local last_local_light_at = nil
    local last_local_marsh_at = nil
    local last_safe_non_marsh_position = nil
    local local_move_id = 0
    local last_intent_goal = nil
    local last_intent_at = nil

    local function SayIntent(command, fallback)
        local talker = inst.components.talker
        if talker ~= nil then
            local phrase = G.type(command.say) == "string" and command.say or fallback
            if phrase ~= nil then
                if command.goal == "explore" and last_intent_goal == "explore"
                    and last_intent_at ~= nil
                    and G.GetTime() - last_intent_at < 15 then
                    return
                end
                talker:Say(phrase, 2, true)
                last_intent_goal = command.goal
                last_intent_at = G.GetTime()
            end
        end
    end

    local function SendClientMove(name, epoch, id, x, z, action_name, target_guid)
        if inst.userid ~= nil then
            local rpc = GetClientModRPC(CLIENT_MOVE_NAMESPACE, name)
            local ok, err
            if name == "move_start" then
                if action_name ~= nil then
                    ok, err = G.pcall(SendModRPCToClient, rpc, inst.userid, epoch, id,
                        x, z, action_name, target_guid)
                else
                    ok, err = G.pcall(SendModRPCToClient, rpc, inst.userid, epoch, id, x, z)
                end
            else
                ok, err = G.pcall(SendModRPCToClient, rpc, inst.userid, epoch, id)
            end
            if not ok then
                G.print("[Wilson P0] client move RPC failed: " .. G.tostring(err))
            end
        end
    end

    local function SetMoveStatus(move, status)
        if active_move == move then
            move.status = status
            if status == "started" then
                move.behavior_started_at = G.GetTime()
            else
                move.terminal_at = G.GetTime()
            end
            command_ack = {epoch = move.epoch, id = move.id, status = status}
            G.print("[Wilson P0] move id=" .. move.id .. " status=" .. status)
        end
    end

    local function FinishMove(move, status)
        if active_move ~= move or move.status ~= "started" then
            return
        end
        local locomotor = inst.components.locomotor
        local own_move = locomotor ~= nil and move.owned_dest ~= nil
            and locomotor.dest == move.owned_dest
        if own_move then
            locomotor:Stop()
        end
        local x, _, z = inst.Transform:GetWorldPosition()
        move.delta_x = x - move.start_x
        move.delta_z = z - move.start_z
        move.distance_to_goal = G.math.sqrt((x - move.goal_x) ^ 2
            + (z - move.goal_z) ^ 2)
        SetMoveStatus(move, status)
        SendClientMove("move_stop", move.epoch, move.id)
        G.print("[Wilson P0] move id=" .. move.id
            .. " delta_x=" .. G.tostring(move.delta_x)
            .. " delta_z=" .. G.tostring(move.delta_z)
            .. " remaining=" .. G.tostring(move.distance_to_goal)
            .. " started_at=" .. G.tostring(move.behavior_started_at)
            .. " terminal_at=" .. G.tostring(move.terminal_at))
    end

    local function StopPickPreview(pick)
        if pick.preview_id ~= nil then
            SendClientMove("move_stop", pick.epoch, pick.preview_id)
            pick.preview_id = nil
        end
    end

    local function PushTargetAction(pick, target, action, on_failed)
        local locomotor = inst.components.locomotor
        if active_pick ~= pick or pick.status ~= "started" then
            return
        end
        if not target:IsValid() then
            pick.failure_reason = "target_invalid"
            on_failed()
            return
        end
        local valid, reason = action:IsValid()
        if not valid then
            pick.failure_reason = "invalid_action:" .. G.tostring(reason)
            on_failed()
            return
        end
        pick.approach_started_at = G.GetTime()
        if pick.native_probe then
            pick.native_action_started_at = G.GetTime()
            local ok, result = G.pcall(locomotor.PushAction, locomotor, action, false)
            if pick.status == "started" and (not ok or (locomotor.dest == nil
                and locomotor.bufferedaction ~= action
                and inst:GetBufferedAction() ~= action)) then
                pick.failure_reason = "native_push_rejected:" .. G.tostring(result)
                on_failed()
            end
            return
        end
        local action_name = action.action == G.ACTIONS.PICK and "PICK"
            or action.action == G.ACTIONS.PICKUP and "PICKUP"
            or action.action == G.ACTIONS.CHOP and "CHOP" or nil
        if action_name == nil or inst.userid == nil then
            pick.failure_reason = "client_action_unavailable"
            on_failed()
            return
        end
        if pick.action_observer ~= nil then
            inst:RemoveEventCallback("performaction", pick.action_observer)
        end
        local function on_perform(_, data)
            local actual = data ~= nil and data.action or nil
            if active_pick == pick and pick.status == "started"
                and pick.action == action and actual ~= nil
                and actual.target == target and actual.action == action.action then
                pick.native_action = actual
                pick.native_action_started_at = G.GetTime()
                for _, callback in G.ipairs(action.onsuccess) do
                    actual:AddSuccessAction(callback)
                end
                for _, callback in G.ipairs(action.onfail) do
                    actual:AddFailAction(callback)
                end
                inst:RemoveEventCallback("performaction", on_perform)
                pick.action_observer = nil
                G.print("[Wilson P0] client action id=" .. pick.id
                    .. " target=" .. target.GUID .. " performed")
            end
        end
        pick.action_observer = on_perform
        inst:ListenForEvent("performaction", on_perform)
        local tx, _, tz = target.Transform:GetWorldPosition()
        pick.preview_sequence = (pick.preview_sequence or 0) + 1
        pick.preview_id = -pick.id * 1000 - pick.preview_sequence
        SendClientMove("move_start", pick.epoch, pick.preview_id,
            tx, tz, action_name, target.GUID)
        local last_distance = G.math.sqrt(inst:GetDistanceSqToInst(target))
        local last_progress_at = G.GetTime()
        local function check_progress()
            if active_pick ~= pick or pick.status ~= "started"
                or pick.action ~= action or not target:IsValid() then
                return
            end
            local distance = G.math.sqrt(inst:GetDistanceSqToInst(target))
            if distance + 0.25 < last_distance then
                last_distance = distance
                last_progress_at = G.GetTime()
            end
            if distance > 2 and G.GetTime() - last_progress_at >= 2.5
                and not locomotor:WaitingForPathSearch() then
                pick.failure_reason = "stalled_route"
                StopPickPreview(pick)
                pick.action = nil
                on_failed("failed_unreachable")
                if pick.native_action ~= nil and (locomotor.bufferedaction == pick.native_action
                    or inst:GetBufferedAction() == pick.native_action) then
                    locomotor:Clear()
                    locomotor:Stop()
                end
            else
                inst:DoTaskInTime(0.5, check_progress)
            end
        end
        if pick.status == "started" then
            inst:DoTaskInTime(0.5, check_progress)
        end
    end

    local function StopPickMotion(pick)
        local locomotor = inst.components.locomotor
        local action = pick.native_action or pick.action
        if locomotor ~= nil then
            if pick.approaching and pick.approach_dest ~= nil
                and locomotor.dest == pick.approach_dest then
                locomotor:Stop()
            elseif action ~= nil and (locomotor.bufferedaction == action
                or inst:GetBufferedAction() == action) then
                if inst:GetBufferedAction() == action then
                    inst:ClearBufferedAction()
                end
                locomotor:Clear()
                locomotor:Stop()
            end
        end
        pick.approaching = false
        StopPickPreview(pick)
    end

    local function SetPickStatus(pick, status)
        if active_pick == pick then
            if status ~= "started" and status ~= "received"
                and pick.preview_id ~= nil then
                StopPickPreview(pick)
            end
            if status ~= "started" and status ~= "received"
                and pick.action_observer ~= nil then
                inst:RemoveEventCallback("performaction", pick.action_observer)
                pick.action_observer = nil
            end
            if (pick.type == "LOOT_CLUSTER" or pick.type == "GATHER_PATCH"
                or pick.type == "COLLECT_AREA")
                and status ~= "started"
                and status ~= "received" and pick.cluster_end_reason == nil then
                pick.cluster_end_reason = status == "interrupted_threat"
                    and "SAFETY_INTERRUPT" or status == "interrupted_light"
                    and "LIGHT_INTERRUPT" or status == "stopped"
                    and "STOPPED" or status
            end
            pick.status = status
            if status ~= "started" and status ~= "received" then
                pick.terminal_at = G.GetTime()
                G.print("[Wilson timeline] id=" .. pick.id
                    .. " behavior_started=" .. G.tostring(pick.behavior_started_at)
                    .. " approach_started=" .. G.tostring(pick.approach_started_at)
                    .. " interaction_range=" .. G.tostring(pick.arrived_interaction_range_at)
                    .. " native_started=" .. G.tostring(pick.native_action_started_at)
                    .. " action_success=" .. G.tostring(pick.action_success_at)
                    .. " action_failed=" .. G.tostring(pick.action_failed_at)
                    .. " terminal=" .. G.tostring(pick.terminal_at))
            end
            command_ack = {epoch = pick.epoch, id = pick.id, status = status}
            G.print("[Wilson P0] pick id=" .. pick.id .. " target=" .. pick.target_guid
                .. " status=" .. status .. " t=" .. G.tostring(G.GetTime()))
        end
    end

    local function SetUtilityStatus(utility, status)
        if active_utility == utility then
            utility.status = status
            command_ack = {epoch = utility.epoch, id = utility.id, status = status}
            G.print("[Wilson P0] utility id=" .. utility.id .. " type="
                .. utility.type .. " status=" .. status)
        end
    end

    local function StartUtility(command)
        if (active_pick ~= nil and active_pick.status == "started")
            or (active_move ~= nil and active_move.status == "started")
            or (active_utility ~= nil and active_utility.status == "started") then
            command_ack = {epoch = command.epoch, id = command.id, status = "rejected_busy"}
            return
        end
        local inventory = inst.components.inventory
        local locomotor = inst.components.locomotor
        local builder = inst.components.builder
        local utility = {
            epoch = command.epoch,
            id = command.id,
            type = command.type,
            status = "received",
        }
        active_utility = utility
        if inventory == nil or locomotor == nil or inst:HasTag("playerghost") then
            SetUtilityStatus(utility, "unavailable")
            return
        end

        local action = nil
        local before = nil
        if command.type == "EAT_BERRIES" or command.type == "EAT_FOOD" then
            local item = ChooseSafeFood(inst)
            if item == nil or inst.components.eater == nil
                or not inst.components.eater:CanEat(item) then
                SetUtilityStatus(utility, "no_edible_food")
                return
            end
            before = CountInventoryItem(inst, item.prefab)
            utility.food_prefab = item.prefab
            utility.hunger_before = inst.components.hunger ~= nil
                and inst.components.hunger.current or nil
            action = G.BufferedAction(inst, item, G.ACTIONS.EAT)
        elseif command.type == "CRAFT_TORCH" or command.type == "CRAFT_AXE" then
            local recipe = command.type == "CRAFT_TORCH" and "torch" or "axe"
            if builder == nil or not builder:CanBuild(recipe) then
                SetUtilityStatus(utility, "missing_build_materials")
                return
            end
            before = CountOwnedItem(inst, recipe)
            utility.product_prefab = recipe
            action = G.BufferedAction(inst, inst, G.ACTIONS.BUILD,
                nil, nil, recipe)
        elseif command.type == "BUILD_CAMPFIRE" then
            if G.TheWorld.state.phase ~= "day" or builder == nil
                or not builder:CanBuild("campfire")
                or HasVisibleThreat(inst, SENSE_RADIUS) then
                SetUtilityStatus(utility, "campfire_not_ready")
                return
            end
            local point = FindSafeCampfirePoint(inst)
            if point == nil then
                SetUtilityStatus(utility, "no_safe_fire_site")
                return
            end
            utility.fire_point = point
            action = G.BufferedAction(inst, nil, G.ACTIONS.BUILD,
                nil, point, "campfire")
        elseif command.type == "COOK_AT" or command.type == "ADD_FUEL" then
            local fire = G.Ents[command.target_guid]
            if fire == nil or not fire:IsValid() or fire.prefab ~= "campfire"
                or fire.components.fueled == nil
                or fire.components.burnable == nil
                or not fire.components.burnable:IsBurning()
                or inst:GetDistanceSqToInst(fire) > 4
                or G.TheWorld.state.phase ~= "day"
                or HasVisibleThreat(inst, SENSE_RADIUS) then
                SetUtilityStatus(utility, "fire_unavailable")
                return
            end
            utility.fire = fire
            if command.type == "COOK_AT" then
                local item = inventory:FindItem(function(candidate)
                    return candidate.prefab == "smallmeat"
                end)
                if item == nil or fire.components.cooker == nil
                    or not fire.components.cooker:CanCook(item, inst) then
                    SetUtilityStatus(utility, "no_cookable_food")
                    return
                end
                utility.product_prefab = "cookedsmallmeat"
                before = CountInventoryItem(inst, "cookedsmallmeat")
                action = G.BufferedAction(inst, fire, G.ACTIONS.COOK, item)
            else
                local item = inventory:FindItem(function(candidate)
                    return candidate.prefab == "log"
                end)
                if item == nil or not fire.components.fueled.accepting then
                    SetUtilityStatus(utility, "no_fire_fuel")
                    return
                end
                utility.fuel_before = fire.components.fueled.currentfuel
                action = G.BufferedAction(inst, fire, G.ACTIONS.ADDFUEL, item)
            end
        elseif command.type == "EQUIP_TORCH" or command.type == "EQUIP_AXE" then
            local prefab = command.type == "EQUIP_TORCH" and "torch" or "axe"
            local item = inventory:FindItem(function(candidate)
                return candidate.prefab == prefab
            end)
            if item == nil then
                SetUtilityStatus(utility, "no_equipment")
                return
            end
            utility.product_prefab = prefab
            action = G.BufferedAction(inst, nil, G.ACTIONS.EQUIP, item)
        elseif command.type == "UNEQUIP_TORCH" then
            local hand = inventory:GetEquippedItem(G.EQUIPSLOTS.HANDS)
            if hand == nil or hand.prefab ~= "torch" then
                SetUtilityStatus(utility, "no_equipped_torch")
                return
            end
            action = G.BufferedAction(inst, nil, G.ACTIONS.UNEQUIP, hand)
        else
            SetUtilityStatus(utility, "unknown_utility")
            return
        end

        utility.action = action
        action:AddSuccessAction(function()
            if command.type == "EAT_BERRIES" or command.type == "EAT_FOOD" then
                local after = CountInventoryItem(inst, utility.food_prefab)
                local hunger = inst.components.hunger
                utility.inventory_delta = after - before
                SetUtilityStatus(utility, after < before and hunger ~= nil
                    and utility.hunger_before ~= nil
                    and hunger.current > utility.hunger_before
                    and "completed" or "uncertain")
            elseif command.type == "CRAFT_TORCH" or command.type == "CRAFT_AXE" then
                local after = CountOwnedItem(inst, utility.product_prefab)
                utility.owned_delta = after - before
                SetUtilityStatus(utility, after > before and "completed" or "uncertain")
            elseif command.type == "BUILD_CAMPFIRE" then
                local point = utility.fire_point
                local fires = G.TheSim:FindEntities(point.x, 0, point.z, 1,
                    {"campfire"}, {"INLIMBO"})
                local fire = fires[1]
                SetUtilityStatus(utility, fire ~= nil and fire.prefab == "campfire"
                    and fire.components.cooker ~= nil and "completed" or "uncertain")
            elseif command.type == "COOK_AT" then
                local after = CountInventoryItem(inst, utility.product_prefab)
                utility.inventory_delta = after - before
                SetUtilityStatus(utility, after > before and "completed" or "uncertain")
            elseif command.type == "ADD_FUEL" then
                local fire = utility.fire
                SetUtilityStatus(utility, fire:IsValid()
                    and fire.components.fueled ~= nil
                    and fire.components.fueled.currentfuel > utility.fuel_before
                    and "completed" or "uncertain")
            elseif command.type == "EQUIP_TORCH" or command.type == "EQUIP_AXE" then
                local hand = inventory:GetEquippedItem(G.EQUIPSLOTS.HANDS)
                SetUtilityStatus(utility, hand ~= nil and hand.prefab == utility.product_prefab
                    and "completed" or "uncertain")
            else
                local hand = inventory:GetEquippedItem(G.EQUIPSLOTS.HANDS)
                SetUtilityStatus(utility, (hand == nil or hand.prefab ~= "torch")
                    and "completed" or "uncertain")
            end
        end)
        action:AddFailAction(function()
            if utility.status == "started" then
                SetUtilityStatus(utility, "failed_or_interrupted")
            end
        end)
        SetUtilityStatus(utility, "started")
        SayIntent(command, "我来处理眼前的需要")
        local ok = G.pcall(locomotor.PushAction, locomotor, action, false)
        if not ok then
            SetUtilityStatus(utility, "failed")
            return
        end
        inst:DoTaskInTime(6, function()
            if inst:IsValid() and active_utility == utility
                and utility.status == "started" then
                if inst:GetBufferedAction() == action then
                    inst:ClearBufferedAction()
                    locomotor:Clear()
                    locomotor:Stop()
                end
                SetUtilityStatus(utility, "timed_out_or_interrupted")
            end
        end)
    end

    local function StartPick(command)
        if (active_pick ~= nil and active_pick.status == "started")
            or (active_move ~= nil and active_move.status == "started")
            or (active_utility ~= nil and active_utility.status == "started") then
            command_ack = {epoch = command.epoch, id = command.id, status = "rejected_busy"}
            return
        end

        local pick = {
            epoch = command.epoch,
            id = command.id,
            type = "PICK_TARGET",
            target_guid = command.target_guid,
            status = "received",
            server_received_at = G.GetTime(),
            chosen_at = command.chosen_at,
            command_sent_at = command.command_sent_at,
            native_probe = command.native_probe == true,
        }
        active_pick = pick
        local target = G.Ents[command.target_guid]
        local locomotor = inst.components.locomotor
        local auto_pick = command.auto == true
        if inst:HasTag("playerghost") or locomotor == nil or target == nil
            or not target:IsValid() or target.prefab ~= command.target_prefab
            or HARVEST_PRODUCTS[target.prefab] == nil
            or target.components.pickable == nil
            or not target.components.pickable:CanBePicked()
            or not G.CanEntitySeeTarget(inst, target)
            or not CanReachTargetOnFoot(inst, target)
            or inst:GetDistanceSqToInst(target) > (auto_pick and 256 or 9) then
            SetPickStatus(pick, "rejected_target")
            return
        end
        if inst.components.inventory == nil or inst.components.inventory:IsFull() then
            SetPickStatus(pick, "rejected_inventory")
            return
        end

        if HasVisibleThreat(inst, auto_pick and 8 or 6) then
            SetPickStatus(pick, "rejected_threat_nearby")
            return
        end

        local product_prefab = HARVEST_PRODUCTS[target.prefab]
        local inventory_before = CountInventoryItem(inst, product_prefab)
        local action = G.BufferedAction(inst, target, G.ACTIONS.PICK)
        pick.action = action
        action:AddSuccessAction(function()
            pick.action_success_at = G.GetTime()
            local harvested = not target:IsValid() or (target.components.pickable ~= nil
                and not target.components.pickable:CanBePicked())
            pick.inventory_delta = CountInventoryItem(inst, product_prefab) - inventory_before
            SetPickStatus(pick, harvested and pick.inventory_delta > 0
                and "completed" or "uncertain")
        end)
        action:AddFailAction(function()
            if pick.status == "started" then
                pick.action_failed_at = G.GetTime()
                G.print("[Wilson P0] pick failed detail id=" .. pick.id
                    .. " reason=" .. G.tostring(action.reason)
                    .. " distance=" .. G.tostring(target:IsValid()
                        and inst:GetDistanceSqToInst(target) or nil)
                    .. " valid=" .. G.tostring(action:IsValid())
                    .. " stuck=" .. G.tostring(target.components.pickable ~= nil
                        and target.components.pickable:IsStuck()))
                SetPickStatus(pick, "failed_or_interrupted")
            end
        end)

        SetPickStatus(pick, "started")
        pick.behavior_started_at = G.GetTime()
        SayIntent(command, "我去采些资源")
        PushTargetAction(pick, target, action, function(status)
            SetPickStatus(pick, status or "failed_native_start")
        end)
        inst:DoTaskInTime(auto_pick and 10 or 6, function()
            if inst:IsValid() and active_pick == pick and pick.status == "started" then
                StopPickMotion(pick)
                SetPickStatus(pick, "timed_out")
            end
        end)
    end

    local function StartPickup(command)
        if (active_pick ~= nil and active_pick.status == "started")
            or (active_move ~= nil and active_move.status == "started")
            or (active_utility ~= nil and active_utility.status == "started") then
            command_ack = {epoch = command.epoch, id = command.id, status = "rejected_busy"}
            return
        end
        local pickup = {
            epoch = command.epoch,
            id = command.id,
            type = "PICKUP_TARGET",
            target_guid = command.target_guid,
            status = "received",
            server_received_at = G.GetTime(),
            chosen_at = command.chosen_at,
            command_sent_at = command.command_sent_at,
        }
        active_pick = pickup
        local target = G.Ents[command.target_guid]
        local inventory = inst.components.inventory
        local locomotor = inst.components.locomotor
        if inst:HasTag("playerghost") or target == nil or not target:IsValid()
            or target.prefab ~= command.target_prefab
            or target.components.inventoryitem == nil
            or target.components.inventoryitem.owner ~= nil
            or not target.components.inventoryitem.canbepickedup
            or not G.CanEntitySeeTarget(inst, target)
            or not CanReachTargetOnFoot(inst, target)
            or inst:GetDistanceSqToInst(target) > 256
            or inventory == nil or inventory:IsFull() or locomotor == nil then
            SetPickStatus(pickup, "rejected_target")
            return
        end
        if HasVisibleThreat(inst, SENSE_RADIUS) then
            SetPickStatus(pickup, "rejected_threat_nearby")
            return
        end
        local before = CountInventoryItem(inst, target.prefab)
        local action = G.BufferedAction(inst, target, G.ACTIONS.PICKUP)
        pickup.action = action
        action:AddSuccessAction(function()
            pickup.action_success_at = G.GetTime()
            pickup.inventory_delta = CountInventoryItem(inst, command.target_prefab) - before
            SetPickStatus(pickup, pickup.inventory_delta > 0 and "completed" or "uncertain")
        end)
        action:AddFailAction(function()
            if pickup.status == "started" then
                pickup.action_failed_at = G.GetTime()
                SetPickStatus(pickup, "failed_or_interrupted")
            end
        end)
        SetPickStatus(pickup, "started")
        pickup.behavior_started_at = G.GetTime()
        SayIntent(command, "我去捡些资源")
        PushTargetAction(pickup, target, action, function(status)
            SetPickStatus(pickup, status or "failed_native_start")
        end)
        inst:DoTaskInTime(10, function()
            if inst:IsValid() and active_pick == pickup and pickup.status == "started" then
                StopPickMotion(pickup)
                SetPickStatus(pickup, "timed_out_or_interrupted")
            end
        end)
    end

    local function StartGatherGroup(command)
        if (active_pick ~= nil and active_pick.status == "started")
            or (active_move ~= nil and active_move.status == "started")
            or (active_utility ~= nil and active_utility.status == "started") then
            command_ack = {epoch = command.epoch, id = command.id, status = "rejected_busy"}
            return
        end
        local items = command.items
        local cluster = {
            epoch = command.epoch,
            id = command.id,
            type = command.type,
            target_guid = items[1].guid,
            status = "received",
            inventory_delta = 0,
            picked_count = 0,
            index = 0,
        }
        active_pick = cluster
        local inventory = inst.components.inventory
        local locomotor = inst.components.locomotor
        if inst:HasTag("playerghost") or inventory == nil or locomotor == nil then
            SetPickStatus(cluster, "rejected_unavailable")
            return
        end
        if HasVisibleThreat(inst, SENSE_RADIUS) then
            SetPickStatus(cluster, "rejected_threat_nearby")
            return
        end
        local function finish(reason, status)
            if active_pick == cluster and cluster.status == "started" then
                cluster.cluster_end_reason = reason
                SetPickStatus(cluster, status or
                    (cluster.picked_count > 0 and "completed" or "empty_cluster"))
            end
        end
        local next_pick
        next_pick = function()
            if active_pick ~= cluster or cluster.status ~= "started" then
                return
            end
            if HasVisibleThreat(inst, SENSE_RADIUS) then
                finish("SAFETY_INTERRUPT", "interrupted_threat")
                return
            end
            if inventory:IsFull() then
                finish("INVENTORY_LIMIT", cluster.picked_count > 0
                    and "completed" or "rejected_inventory")
                return
            end
            local entry, target
            while cluster.index < #items do
                cluster.index = cluster.index + 1
                local candidate = items[cluster.index]
                local entity = G.Ents[candidate.guid]
                local harvesting = command.type == "GATHER_PATCH"
                    or (command.type == "COLLECT_AREA" and candidate.kind == "harvest")
                local gathering = command.type == "LOOT_CLUSTER"
                    or (command.type == "COLLECT_AREA" and candidate.kind == "pickup")
                if entity ~= nil and entity:IsValid()
                    and entity.prefab == candidate.prefab
                    and ((harvesting and HARVEST_PRODUCTS[entity.prefab] ~= nil
                        and entity.components.pickable ~= nil
                        and entity.components.pickable:CanBePicked())
                        or (gathering and entity.components.inventoryitem ~= nil
                        and entity.components.inventoryitem.owner == nil
                        and entity.components.inventoryitem.canbepickedup))
                    and G.CanEntitySeeTarget(inst, entity)
                    and CanReachTargetOnFoot(inst, entity)
                    and inst:GetDistanceSqToInst(entity) <= 256 then
                    entry, target = candidate, entity
                    break
                end
                G.print("[Wilson P0] cluster id=" .. cluster.id
                    .. " skipped target=" .. G.tostring(candidate.guid))
            end
            if target == nil then
                finish("CLUSTER_EXHAUSTED")
                return
            end
            cluster.target_guid = entry.guid
            local harvesting = command.type == "GATHER_PATCH"
                or (command.type == "COLLECT_AREA" and entry.kind == "harvest")
            local product = harvesting and HARVEST_PRODUCTS[entry.prefab] or entry.prefab
            local before = CountInventoryItem(inst, product)
            local action = G.BufferedAction(inst, target,
                harvesting and G.ACTIONS.PICK or G.ACTIONS.PICKUP)
            cluster.action = action
            action:AddSuccessAction(function()
                if cluster.status ~= "started" or cluster.action ~= action then
                    return
                end
                local delta = CountInventoryItem(inst, product) - before
                if delta > 0 then
                    cluster.inventory_delta = cluster.inventory_delta + delta
                    cluster.picked_count = cluster.picked_count + 1
                    G.print("[Wilson P0] cluster id=" .. cluster.id
                        .. " picked=" .. entry.prefab .. ":" .. entry.guid
                        .. " total=" .. cluster.picked_count)
                end
                StopPickPreview(cluster)
                inst:DoTaskInTime(0, next_pick)
            end)
            action:AddFailAction(function()
                if cluster.status == "started" and cluster.action == action then
                    StopPickPreview(cluster)
                    G.print("[Wilson P0] cluster id=" .. cluster.id
                        .. " failed target=" .. entry.guid)
                    inst:DoTaskInTime(0, next_pick)
                end
            end)
            PushTargetAction(cluster, target, action, function()
                G.print("[Wilson P0] cluster id=" .. cluster.id
                    .. " action failed target=" .. entry.guid)
                inst:DoTaskInTime(0, next_pick)
            end)
        end
        SetPickStatus(cluster, "started")
        SayIntent(command, command.type == "COLLECT_AREA"
            and "这一片有用的东西，我一起收集"
            or command.type == "GATHER_PATCH" and "这片资源我顺手采完"
            or "我把附近的物资捡起来")
        next_pick()
        inst:DoTaskInTime(45, function()
            if inst:IsValid() and active_pick == cluster
                and cluster.status == "started" then
                StopPickMotion(cluster)
                finish("TASK_BUDGET_REACHED", cluster.picked_count > 0
                    and "completed" or "timed_out")
            end
        end)
    end

    local function StartFellTree(command)
        if (active_pick ~= nil and active_pick.status == "started")
            or (active_move ~= nil and active_move.status == "started")
            or (active_utility ~= nil and active_utility.status == "started") then
            command_ack = {epoch = command.epoch, id = command.id, status = "rejected_busy"}
            return
        end
        local chop = {
            epoch = command.epoch,
            id = command.id,
            type = "FELL_TREE",
            target_guid = command.target_guid,
            status = "received",
            server_received_at = G.GetTime(),
            chosen_at = command.chosen_at,
            command_sent_at = command.command_sent_at,
        }
        active_pick = chop
        local target = G.Ents[command.target_guid]
        local inventory = inst.components.inventory
        local locomotor = inst.components.locomotor
        local hand = inventory ~= nil and inventory:GetEquippedItem(G.EQUIPSLOTS.HANDS) or nil
        local workable = target ~= nil and target.components.workable or nil
        if inst:HasTag("playerghost") or G.TheWorld.state.phase ~= "day"
            or target == nil or not target:IsValid()
            or not CHOP_PREFABS[command.target_prefab]
            or target.prefab ~= command.target_prefab or target:HasTag("burnt")
            or workable == nil or not workable:CanBeWorked()
            or workable:GetWorkAction() ~= G.ACTIONS.CHOP
            or hand == nil or hand.prefab ~= "axe"
            or not G.CanEntitySeeTarget(inst, target)
            or not CanReachTargetOnFoot(inst, target)
            or inst:GetDistanceSqToInst(target) > 64
            or locomotor == nil or HasVisibleThreat(inst, SENSE_RADIUS) then
            SetPickStatus(chop, "rejected_target")
            return
        end
        local initial_work = workable:GetWorkLeft()
        local push_next_chop
        push_next_chop = function()
            if active_pick ~= chop or chop.status ~= "started" then
                return
            end
            if HasVisibleThreat(inst, SENSE_RADIUS) then
                SetPickStatus(chop, "interrupted_threat")
                return
            end
            if G.TheWorld.state.phase ~= "day" then
                SetPickStatus(chop, "interrupted_light")
                return
            end
            local current = target:IsValid() and target.components.workable or nil
            if current == nil or not current:CanBeWorked()
                or current:GetWorkAction() ~= G.ACTIONS.CHOP then
                chop.tree_felled = chop.work_delta ~= nil and chop.work_delta > 0
                SetPickStatus(chop, chop.tree_felled and "completed" or "blocked_target")
                return
            end
            local equipped = inventory:GetEquippedItem(G.EQUIPSLOTS.HANDS)
            if equipped == nil or equipped.prefab ~= "axe" then
                SetPickStatus(chop, "blocked_tool")
                return
            end
            if not G.CanEntitySeeTarget(inst, target)
                or inst:GetDistanceSqToInst(target) > 100 then
                SetPickStatus(chop, "blocked_target")
                return
            end
            local before = current:GetWorkLeft()
            local action = G.BufferedAction(inst, target, G.ACTIONS.CHOP)
            chop.action = action
            action:AddSuccessAction(function()
                if active_pick ~= chop or chop.status ~= "started" then
                    return
                end
                local callback_at = G.GetTime()
                G.print("[Wilson chop] id=" .. chop.id
                    .. " success_at=" .. G.tostring(callback_at)
                    .. " since_push=" .. G.tostring(callback_at
                        - (chop.native_action_started_at or callback_at)))
                chop.action_success_at = callback_at
                StopPickPreview(chop)
                chop.previous_chop_success_at = callback_at
                local after_workable = target:IsValid() and target.components.workable or nil
                local after = after_workable ~= nil
                    and after_workable:GetWorkAction() == G.ACTIONS.CHOP
                    and after_workable:GetWorkLeft() or 0
                chop.work_delta = initial_work - after
                if after <= 0 then
                    chop.tree_felled = true
                    SetPickStatus(chop, "completed")
                elseif after < before then
                    inst:DoTaskInTime(0, push_next_chop)
                else
                    SetPickStatus(chop, "uncertain")
                end
            end)
            action:AddFailAction(function()
                if chop.status == "started" then
                    chop.action_failed_at = G.GetTime()
                    SetPickStatus(chop, "failed_or_interrupted")
                end
            end)
            PushTargetAction(chop, target, action, function(status)
                SetPickStatus(chop, status or "failed_native_start")
            end)
        end
        SetPickStatus(chop, "started")
        chop.behavior_started_at = G.GetTime()
        SayIntent(command, "我来砍倒这棵树")
        push_next_chop()
        inst:DoTaskInTime(30, function()
            if inst:IsValid() and active_pick == chop and chop.status == "started" then
                StopPickMotion(chop)
                SetPickStatus(chop, "timed_out")
            end
        end)
    end

    inst:ListenForEvent("actionfailed", function(_, data)
        if active_pick ~= nil and active_pick.status == "started"
            and data ~= nil and data.action == active_pick.action then
            active_pick.failure_reason = G.tostring(data.reason)
            G.print("[Wilson actionfailed] id=" .. active_pick.id
                .. " reason=" .. active_pick.failure_reason
                .. " t=" .. G.tostring(G.GetTime()))
        end
    end)

    inst:DoPeriodicTask(0.5, function()
        local frog_visible, threat_visible, nearest_threat, visible_hazards =
            ReadVisibleHazards(inst, HAZARD_OBSERVE_RADIUS)
        local locomotor = inst.components.locomotor
        local inventory = inst.components.inventory
        if active_pick ~= nil and active_pick.status == "started"
            and active_pick.arrived_interaction_range_at == nil
            and active_pick.target_guid ~= nil then
            local target = G.Ents[active_pick.target_guid]
            if target ~= nil and target:IsValid()
                and inst:GetDistanceSqToInst(target) <= 4 then
                active_pick.arrived_interaction_range_at = G.GetTime()
            end
        end
        local px, _, pz = inst.Transform:GetWorldPosition()
        local on_marsh = G.TheWorld.Map:GetTileAtPoint(px, 0, pz)
            == G.WORLD_TILES.MARSH
        if not on_marsh then
            last_safe_non_marsh_position = {x = px, z = pz}
        elseif G.TheWorld.state.cycles < 2 and locomotor ~= nil
            and not inst:HasTag("playerghost")
            and (active_move == nil or active_move.epoch ~= "local"
                or active_move.status ~= "started")
            and (last_local_marsh_at == nil
                or G.GetTime() - last_local_marsh_at >= 2) then
            local safe = last_safe_non_marsh_position
            if safe == nil then
                for _, point in G.ipairs(ReadFrontier(px, pz)) do
                    if point.passable and point.endpoint_marsh == false
                        and point.dx * point.dx + point.dz * point.dz <= 36 then
                        safe = {x = px + point.dx, z = pz + point.dz}
                        break
                    end
                end
            end
            if safe ~= nil then
                if active_move ~= nil and active_move.status == "started" then
                    FinishMove(active_move, "interrupted_marsh")
                end
                if active_pick ~= nil and active_pick.status == "started" then
                    StopPickMotion(active_pick)
                    SetPickStatus(active_pick, "interrupted_marsh")
                end
                if active_utility ~= nil and active_utility.status == "started" then
                    if inst:GetBufferedAction() == active_utility.action then
                        inst:ClearBufferedAction()
                        locomotor:Clear()
                        locomotor:Stop()
                    end
                    SetUtilityStatus(active_utility, "interrupted_marsh")
                end
                local ok = G.pcall(locomotor.GoToPoint, locomotor,
                    G.Vector3(safe.x, 0, safe.z), nil, false)
                last_local_marsh_at = G.GetTime()
                if ok and locomotor.dest ~= nil then
                    local_move_id = local_move_id + 1
                    local distance = G.math.sqrt((safe.x - px) ^ 2 + (safe.z - pz) ^ 2)
                    local move = {
                        epoch = "local", id = local_move_id, type = "MOVE_TO_POINT",
                        escape = true, status = "received", owned_dest = locomotor.dest,
                        track_progress = true, start_x = px, start_z = pz,
                        goal_x = safe.x, goal_z = safe.z,
                        initial_distance = G.math.max(0.1, distance),
                        last_progress_x = px, last_progress_z = pz,
                        last_progress_at = G.GetTime(), distance_to_goal = distance,
                        progress = 0,
                    }
                    active_move = move
                    SetMoveStatus(move, "started")
                    SayIntent({}, "进了沼泽，先退回安全地面")
                    SendClientMove("move_start", move.epoch, move.id, safe.x, safe.z)
                    G.print("[Wilson P0] local marsh return to="
                        .. G.tostring(safe.x) .. "," .. G.tostring(safe.z))
                    inst:DoTaskInTime(G.math.max(4, distance / 4 + 2), function()
                        if inst:IsValid() and active_move == move
                            and move.status == "started" then
                            FinishMove(move, "timed_out")
                        end
                    end)
                end
            end
        end
        local clock = G.TheWorld.net ~= nil and G.TheWorld.net.components.clock or nil
        local night_soon = G.TheWorld.state.phase == "dusk" and clock ~= nil
            and clock:GetTimeUntilPhase("night") <= 2
        local dark_now = G.TheWorld.state.phase == "night" and not inst:IsInLight()
        local hand = inventory ~= nil and inventory:GetEquippedItem(G.EQUIPSLOTS.HANDS) or nil
        local replace_now = G.TheWorld.state.phase == "night"
            and hand ~= nil and hand.prefab == "torch"
            and TorchSeconds(hand, true) <= 3
        if survival_seen and (night_soon or dark_now or replace_now) and inventory ~= nil
            and not inst:HasTag("playerghost")
            and (last_local_light_at == nil or G.GetTime() - last_local_light_at >= 3) then
            local torch = inventory:FindItem(function(item)
                return item.prefab == "torch"
            end)
            if ((hand == nil or hand.prefab ~= "torch") or replace_now)
                and torch ~= nil then
                if not replace_now and active_move ~= nil and active_move.status == "started"
                    and locomotor ~= nil and active_move.owned_dest ~= nil
                    and locomotor.dest == active_move.owned_dest then
                    FinishMove(active_move, "interrupted_light")
                elseif not replace_now and active_pick ~= nil and active_pick.status == "started"
                    and locomotor ~= nil and (inst:GetBufferedAction() == active_pick.action
                        or active_pick.approaching
                        or active_pick.type == "FELL_TREE"
                        or active_pick.type == "LOOT_CLUSTER"
                        or active_pick.type == "GATHER_PATCH"
                        or active_pick.type == "COLLECT_AREA") then
                    StopPickMotion(active_pick)
                    SetPickStatus(active_pick, "interrupted_light")
                elseif not replace_now and active_utility ~= nil and active_utility.status == "started"
                    and locomotor ~= nil and inst:GetBufferedAction() == active_utility.action then
                    inst:ClearBufferedAction()
                    locomotor:Clear()
                    locomotor:Stop()
                    SetUtilityStatus(active_utility, "interrupted_light")
                end
                last_local_light_at = G.GetTime()
                if inventory:Equip(torch) then
                    SayIntent({}, replace_now and "火炬快灭了，换一支"
                        or "快天黑了，先拿出火炬")
                    G.print("[Wilson P0] local light equipped")
                end
            end
        end
        if threat_visible and locomotor ~= nil then
            if active_move ~= nil and active_move.status == "started"
                and not active_move.escape
                and active_move.owned_dest ~= nil
                and locomotor.dest == active_move.owned_dest then
                FinishMove(active_move, "interrupted_threat")
                SayIntent({}, "附近有危险，我先停下")
            elseif active_pick ~= nil and active_pick.status == "started"
                and (inst:GetBufferedAction() == active_pick.action
                    or active_pick.approaching
                    or active_pick.type == "FELL_TREE"
                    or active_pick.type == "LOOT_CLUSTER"
                    or active_pick.type == "GATHER_PATCH"
                    or active_pick.type == "COLLECT_AREA") then
                StopPickMotion(active_pick)
                SetPickStatus(active_pick, "interrupted_threat")
                SayIntent({}, "附近有危险，我先停下")
            elseif active_utility ~= nil and active_utility.status == "started"
                and inst:GetBufferedAction() == active_utility.action then
                inst:ClearBufferedAction()
                locomotor:Clear()
                locomotor:Stop()
                SetUtilityStatus(active_utility, "interrupted_threat")
                SayIntent({}, "附近有危险，我先停下")
            end
        end

        if active_move ~= nil and active_move.status == "started"
            and active_move.track_progress then
            local move = active_move
            local x, _, z = inst.Transform:GetWorldPosition()
            local remaining_sq = (x - move.goal_x) ^ 2 + (z - move.goal_z) ^ 2
            move.distance_to_goal = G.math.sqrt(remaining_sq)
            move.progress = G.math.max(0, G.math.min(1,
                1 - move.distance_to_goal / move.initial_distance))
            if remaining_sq <= 0.25
                or (locomotor ~= nil and locomotor.dest == nil
                    and remaining_sq <= (move.type == "MOVE_TO_TARGET" and 0.25 or 4)) then
                FinishMove(move, "arrived")
            elseif locomotor ~= nil and locomotor.dest ~= nil
                and locomotor.dest ~= move.owned_dest then
                FinishMove(move, "released")
            elseif (x - move.last_progress_x) ^ 2
                + (z - move.last_progress_z) ^ 2 >= 0.36 then
                move.last_progress_x = x
                move.last_progress_z = z
                move.last_progress_at = G.GetTime()
            elseif G.GetTime() - move.last_progress_at >= (
                move.initial_distance > 20 and 2.5 or 1.5) then
                FinishMove(move, "blocked")
            end
        end

        if threat_visible and nearest_threat ~= nil and survival_seen
            and last_bridge_ok_at ~= nil
            and G.GetTime() - last_bridge_ok_at >= 5
            and (last_local_escape_at == nil
                or G.GetTime() - last_local_escape_at >= 4)
            and locomotor ~= nil
            and (active_move == nil or active_move.status ~= "started")
            and (active_pick == nil or active_pick.status ~= "started")
            and (active_utility == nil or active_utility.status ~= "started") then
            local x, _, z = inst.Transform:GetWorldPosition()
            local best_point = nil
            local best_distance_sq = nearest_threat.distance_sq + 4
            for _, point in G.ipairs(ReadFrontier(x, z)) do
                if point.passable and point.dx * point.dx + point.dz * point.dz <= 64
                    and (G.TheWorld.state.cycles >= 2
                        or (point.marsh_steps == 0 and not point.endpoint_marsh)) then
                    local away_distance_sq = (point.dx - nearest_threat.dx) ^ 2
                        + (point.dz - nearest_threat.dz) ^ 2
                    if away_distance_sq > best_distance_sq then
                        best_distance_sq = away_distance_sq
                        best_point = point
                    end
                end
            end
            if best_point ~= nil then
                local goal_x, goal_z = x + best_point.dx, z + best_point.dz
                local ok = G.pcall(locomotor.GoToPoint, locomotor,
                    G.Vector3(goal_x, 0, goal_z), nil, false)
                last_local_escape_at = G.GetTime()
                if ok then
                    local_move_id = local_move_id + 1
                    local move = {
                        epoch = "local",
                        id = local_move_id,
                        type = "MOVE_TO_POINT",
                        escape = true,
                        status = "received",
                        owned_dest = locomotor.dest,
                        track_progress = true,
                        start_x = x,
                        start_z = z,
                        goal_x = goal_x,
                        goal_z = goal_z,
                        initial_distance = G.math.max(0.1,
                            G.math.sqrt(best_point.dx ^ 2 + best_point.dz ^ 2)),
                        last_progress_x = x,
                        last_progress_z = z,
                        last_progress_at = G.GetTime(),
                        distance_to_goal = G.math.sqrt(best_point.dx ^ 2
                            + best_point.dz ^ 2),
                        progress = 0,
                    }
                    active_move = move
                    SetMoveStatus(move, "started")
                    SayIntent({}, "连接暂时断开，我先躲开危险")
                    SendClientMove("move_start", move.epoch, move.id,
                        goal_x, goal_z)
                    inst:DoTaskInTime(4, function()
                        if inst:IsValid() and active_move == move
                            and move.status == "started" then
                            FinishMove(move, "timed_out")
                        end
                    end)
                end
            end
        end

        if pending_seq ~= nil and G.GetTime() - pending_since < 10 then
            return
        end

        seq = seq + 1
        local request_seq = seq
        pending_seq = request_seq
        pending_since = G.GetTime()
            local x, _, z = inst.Transform:GetWorldPosition()
            local nearby, nearby_truncated = ReadLocalEntities(inst, x, z)
        local body = G.json.encode({
            probe = "wilson-p0",
            mod_version = "0.25.4",
            seq = request_seq,
            prefab = inst.prefab,
            guid = inst.GUID,
            cycles = G.TheWorld.state.cycles,
            phase = G.TheWorld.state.phase,
            phase_progress = G.TheWorld.state.timeinphase,
            x = x,
            z = z,
            on_marsh = G.TheWorld.Map:GetTileAtPoint(x, 0, z)
                == G.WORLD_TILES.MARSH,
            vitals = ReadVitals(inst),
            inventory = ReadInventory(inst),
            in_light = inst:IsInLight(),
            seconds_until_day = G.TheWorld.net ~= nil
                and G.TheWorld.net.components.clock ~= nil
                and G.TheWorld.net.components.clock:GetTimeUntilPhase("day") or nil,
            seconds_until_night = G.TheWorld.net ~= nil
                and G.TheWorld.net.components.clock ~= nil
                and G.TheWorld.net.components.clock:GetTimeUntilPhase("night") or nil,
            local_radius = RESOURCE_RADIUS,
            local_entities = nearby,
            local_entities_truncated = nearby_truncated,
            nearby_fires = ReadNearbyFires(x, z),
            visible_frog_within_8 = frog_visible,
            visible_threat_within_8 = threat_visible,
            nearest_threat = nearest_threat,
            visible_hazards = visible_hazards,
            frontier = ReadFrontier(x, z),
            command_ack = command_ack,
            execution = active_pick ~= nil and {
                epoch = active_pick.epoch,
                id = active_pick.id,
                type = active_pick.type,
                target_guid = active_pick.target_guid,
                status = active_pick.status,
                inventory_delta = active_pick.inventory_delta,
                picked_count = active_pick.picked_count,
                cluster_end_reason = active_pick.cluster_end_reason,
                failure_reason = active_pick.failure_reason,
                server_received_at = active_pick.server_received_at,
                behavior_started_at = active_pick.behavior_started_at,
                approach_started_at = active_pick.approach_started_at,
                native_action_started_at = active_pick.native_action_started_at,
                action_success_at = active_pick.action_success_at,
                action_failed_at = active_pick.action_failed_at,
                arrived_interaction_range_at = active_pick.arrived_interaction_range_at,
                terminal_at = active_pick.terminal_at,
                chosen_at = active_pick.chosen_at,
                command_sent_at = active_pick.command_sent_at,
                work_delta = active_pick.work_delta,
                tree_felled = active_pick.tree_felled,
            } or nil,
            movement = active_move ~= nil and {
                epoch = active_move.epoch,
                id = active_move.id,
                type = active_move.type,
                target_guid = active_move.target_guid,
                status = active_move.status,
                delta_x = active_move.delta_x,
                delta_z = active_move.delta_z,
                progress = active_move.progress,
                distance_to_goal = active_move.distance_to_goal,
                chosen_at = active_move.chosen_at,
                command_sent_at = active_move.command_sent_at,
                server_received_at = active_move.server_received_at,
                behavior_started_at = active_move.behavior_started_at,
                terminal_at = active_move.terminal_at,
            } or nil,
            utility = active_utility ~= nil and {
                epoch = active_utility.epoch,
                id = active_utility.id,
                type = active_utility.type,
                status = active_utility.status,
                inventory_delta = active_utility.inventory_delta,
                hunger_before = active_utility.hunger_before,
            } or nil,
        })

        G.TheSim:QueryServer(URL, function(result, successful, code)
            local current_response = pending_seq == request_seq
            local response_age = current_response and G.GetTime() - pending_since or G.math.huge
            if current_response then
                pending_seq = nil
            end
            local parsed_ok, reply = G.pcall(G.json.decode, result or "")
            local matched = successful and code == 200 and parsed_ok and G.type(reply) == "table"
                and reply.probe == "wilson-p0" and reply.seq == request_seq and reply.ack == true
            if matched and current_response then
                last_bridge_ok_at = G.GetTime()
            end
            if not matched or request_seq % 10 == 1 then
                G.print("[Wilson P0] seq=" .. request_seq .. " ack=" .. G.tostring(matched)
                    .. " http=" .. G.tostring(code))
            end

            if matched and current_response and response_age <= 5
                and G.type(reply.command) == "table" then
                local command = reply.command
                if command.guid == inst.GUID and G.type(command.goal) == "string" then
                    survival_seen = true
                end
                local key = G.tostring(command.epoch) .. ":" .. G.tostring(command.id)
                if (command.type == "MOVE_EAST_SHORT" or command.type == "MOVE_EAST_LONG"
                    or command.type == "MOVE_TO_TARGET" or command.type == "MOVE_TO_POINT")
                    and command.guid == inst.GUID
                    and G.type(command.epoch) == "string" and G.type(command.id) == "number"
                    and (command.type ~= "MOVE_TO_TARGET" or
                        (G.type(command.target_guid) == "number"
                        and G.type(command.target_prefab) == "string"))
                    and (command.type ~= "MOVE_TO_POINT" or
                        (G.type(command.x) == "number" and G.type(command.z) == "number"))
                    and key ~= last_command_key then
                    last_command_key = key
                    local is_long = command.type == "MOVE_EAST_LONG"
                    local is_target = command.type == "MOVE_TO_TARGET"
                    local is_point = command.type == "MOVE_TO_POINT"
                    local is_escape = is_point and command.escape == true
                    local locomotor = inst.components.locomotor
                    local target = is_target and G.Ents[command.target_guid] or nil
                    local _, threat_visible, nearest_threat = ReadVisibleHazards(inst, SENSE_RADIUS)
                    local status = "unavailable"
                    if (active_pick ~= nil and active_pick.status == "started")
                        or (active_move ~= nil and active_move.status == "started")
                        or (active_utility ~= nil and active_utility.status == "started") then
                        status = "rejected_busy"
                    elseif threat_visible and not is_escape then
                        status = "rejected_threat_nearby"
                    elseif is_target and (target == nil or not target:IsValid()
                        or target.prefab ~= command.target_prefab
                        or (HARVEST_PRODUCTS[target.prefab] == nil
                            and target.components.inventoryitem == nil
                            and not CHOP_PREFABS[target.prefab]
                            and target.prefab ~= "campfire")
                        or not G.CanEntitySeeTarget(inst, target)
                        or inst:GetDistanceSqToInst(target) > 1156) then
                        status = "rejected_target"
                    elseif locomotor ~= nil then
                        local px, _, pz = inst.Transform:GetWorldPosition()
                        local distance = is_long and 8 or 1.5
                        local goal_x, goal_z = px + distance, pz
                        if is_target then
                            goal_x, _, goal_z = target.Transform:GetWorldPosition()
                            local away_x, away_z = px - goal_x, pz - goal_z
                            local away_length = G.math.sqrt(away_x * away_x
                                + away_z * away_z)
                            if away_length > 0.01 then
                                goal_x = goal_x + away_x / away_length
                                goal_z = goal_z + away_z / away_length
                            end
                        elseif is_point then
                            goal_x, goal_z = command.x, command.z
                        end
                        local point_distance_sq = (goal_x - px) ^ 2 + (goal_z - pz) ^ 2
                        local duration = (is_target or is_point)
                            and G.math.max(4, G.math.sqrt(point_distance_sq) / 4 + 2)
                            or is_long and 4 or 1.5
                        local move_ok = false
                        local threat_end_distance_sq = nearest_threat ~= nil and
                            (goal_x - px - nearest_threat.dx) ^ 2
                            + (goal_z - pz - nearest_threat.dz) ^ 2 or nil
                        local _, route_marsh_steps = ReadRouteTerrain(px, pz,
                            goal_x - px, goal_z - pz)
                        local early_marsh_route = G.TheWorld.state.cycles < 2
                            and G.TheWorld.Map:GetTileAtPoint(px, 0, pz)
                                ~= G.WORLD_TILES.MARSH
                            and route_marsh_steps > 0
                        if early_marsh_route then
                            status = "rejected_marsh_route"
                        elseif is_point and (point_distance_sq > 1600
                            or not G.TheWorld.Map:IsPassableAtPoint(goal_x, 0, goal_z)) then
                            status = "rejected_point"
                        elseif is_escape and nearest_threat ~= nil
                            and threat_end_distance_sq <= nearest_threat.distance_sq + 4 then
                            status = "rejected_escape"
                        else
                            move_ok = G.pcall(locomotor.GoToPoint, locomotor,
                                G.Vector3(goal_x, 0, goal_z), nil, false)
                            status = move_ok and "started" or "failed"
                        end
                        if move_ok then
                            local move = {
                                epoch = command.epoch,
                                id = command.id,
                                type = command.type,
                                target_guid = is_target and target.GUID or nil,
                                escape = is_escape,
                                status = "received",
                                chosen_at = command.chosen_at,
                                command_sent_at = command.command_sent_at,
                                server_received_at = G.GetTime(),
                                owned_dest = locomotor.dest,
                                track_progress = is_target or is_point,
                                start_x = px,
                                start_z = pz,
                                goal_x = goal_x,
                                goal_z = goal_z,
                                initial_distance = G.math.max(0.1,
                                    G.math.sqrt(point_distance_sq)),
                                last_progress_x = px,
                                last_progress_z = pz,
                                last_progress_at = G.GetTime(),
                                distance_to_goal = G.math.sqrt(point_distance_sq),
                                progress = 0,
                            }
                            active_move = move
                            SetMoveStatus(move, "started")
                            SayIntent(command, "我往前走走")
                            SendClientMove("move_start", move.epoch, move.id, goal_x, goal_z)
                            inst:DoTaskInTime(duration, function()
                                if inst:IsValid() and active_move == move
                                    and move.status == "started" then
                                    local still_own_move = move.owned_dest ~= nil
                                        and locomotor.dest == move.owned_dest
                                    local end_x, _, end_z = inst.Transform:GetWorldPosition()
                                    if is_target or is_point then
                                        local released = locomotor.dest ~= nil
                                            and locomotor.dest ~= move.owned_dest
                                        local goal_distance_sq = (end_x - goal_x) ^ 2
                                            + (end_z - goal_z) ^ 2
                                        FinishMove(move, released and "released"
                                            or goal_distance_sq <= (is_target and 0.25 or 4)
                                                and "arrived"
                                            or "timed_out")
                                    else
                                        FinishMove(move, still_own_move
                                            and "timer_stopped" or "released_or_arrived")
                                    end
                                end
                            end)
                        end
                    end
                    if status ~= "started" then
                        command_ack = {epoch = command.epoch, id = command.id, status = status}
                        G.print("[Wilson P0] move id=" .. command.id .. " status=" .. status)
                    end
                elseif command.type == "PICK_TARGET" and command.guid == inst.GUID
                    and G.type(command.epoch) == "string" and G.type(command.id) == "number"
                    and G.type(command.target_guid) == "number"
                    and G.type(command.target_prefab) == "string"
                    and key ~= last_command_key then
                    last_command_key = key
                    StartPick(command)
                elseif command.type == "PICKUP_TARGET" and command.guid == inst.GUID
                    and G.type(command.epoch) == "string" and G.type(command.id) == "number"
                    and G.type(command.target_guid) == "number"
                    and G.type(command.target_prefab) == "string"
                    and key ~= last_command_key then
                    last_command_key = key
                    StartPickup(command)
                elseif (command.type == "LOOT_CLUSTER"
                    or command.type == "GATHER_PATCH"
                    or command.type == "COLLECT_AREA") and command.guid == inst.GUID
                    and G.type(command.epoch) == "string" and G.type(command.id) == "number"
                    and G.type(command.items) == "table" and #command.items >= 1
                    and #command.items <= 12 and G.type(command.items[1]) == "table"
                    and G.type(command.items[1].guid) == "number"
                    and key ~= last_command_key then
                    last_command_key = key
                    StartGatherGroup(command)
                elseif command.type == "FELL_TREE" and command.guid == inst.GUID
                    and G.type(command.epoch) == "string" and G.type(command.id) == "number"
                    and G.type(command.target_guid) == "number"
                    and G.type(command.target_prefab) == "string"
                    and key ~= last_command_key then
                    last_command_key = key
                    StartFellTree(command)
                elseif (command.type == "EAT_BERRIES"
                    or command.type == "EAT_FOOD"
                    or command.type == "CRAFT_TORCH"
                    or command.type == "CRAFT_AXE"
                    or command.type == "BUILD_CAMPFIRE"
                    or command.type == "COOK_AT"
                    or command.type == "ADD_FUEL"
                    or command.type == "EQUIP_TORCH"
                    or command.type == "EQUIP_AXE"
                    or command.type == "UNEQUIP_TORCH")
                    and command.guid == inst.GUID
                    and G.type(command.epoch) == "string"
                    and G.type(command.id) == "number"
                    and (command.type ~= "COOK_AT" and command.type ~= "ADD_FUEL"
                        or G.type(command.target_guid) == "number")
                    and key ~= last_command_key then
                    last_command_key = key
                    StartUtility(command)
                elseif command.type == "STOP" and command.guid == inst.GUID
                    and G.type(command.epoch) == "string" and G.type(command.id) == "number"
                    and G.type(command.target_id) == "number"
                    and key ~= last_command_key then
                    last_command_key = key
                    if command.goal == nil then
                        survival_seen = false
                    end
                    local status = "no_active_action"
                    local locomotor = inst.components.locomotor
                    if active_move ~= nil and active_move.id == command.target_id
                        and active_move.status == "started" and locomotor ~= nil then
                        if active_move.owned_dest ~= nil
                            and locomotor.dest == active_move.owned_dest then
                            FinishMove(active_move, "stopped")
                            status = "stopped_move"
                        else
                            FinishMove(active_move, "released_or_arrived")
                            status = "already_released"
                        end
                    elseif active_pick ~= nil and active_pick.id == command.target_id
                        and active_pick.status == "started" and locomotor ~= nil then
                        StopPickMotion(active_pick)
                        SetPickStatus(active_pick, "stopped")
                        status = "stopped_pick"
                    elseif active_utility ~= nil and active_utility.id == command.target_id
                        and active_utility.status == "started" and locomotor ~= nil then
                        if inst:GetBufferedAction() == active_utility.action then
                            inst:ClearBufferedAction()
                            locomotor:Clear()
                            locomotor:Stop()
                            SetUtilityStatus(active_utility, "stopped")
                            status = "stopped_utility"
                        else
                            status = "already_released"
                        end
                    end
                    command_ack = {epoch = command.epoch, id = command.id, status = status}
                    SayIntent(command, "先停下来")
                    G.print("[Wilson P0] stop id=" .. command.id .. " target="
                        .. command.target_id .. " status=" .. status)
                end
            end
        end, "POST", body)
    end, 1)
end)
