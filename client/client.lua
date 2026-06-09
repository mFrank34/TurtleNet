local CONFIG = {
    host      = "192.168.10.2:8000",
    node_id   = os.getComputerLabel() or tostring(os.getComputerID()),
    node_type = "turtle",
}

local function wait_for_server()
    while true do
        local ok = http.get("http://" .. CONFIG.host .. "/health")
        if ok then
            ok.close()
            print("[TurtleNet] Server is up, connecting...")
            return
        end
        print("[TurtleNet] Server unavailable, retrying in 5s...")
        sleep(5)
    end
end

local function get_inventory()
    local inv = {}
    for slot = 1, 16 do
        local item = turtle.getItemDetail(slot)
        if item then
            inv[tostring(slot)] = {
                name  = item.name,
                count = item.count,
            }
        end
    end
    return inv
end

local function connect()
    local ws, err = http.websocket(
        "ws://" .. CONFIG.host .. "/api/v1/workers/ws/" .. CONFIG.node_id
    )
    if not ws then
        print("[TurtleNet] Failed to connect: " .. tostring(err))
        return nil
    end
    print("[TurtleNet] Connected as " .. CONFIG.node_id)
    ws.send(textutils.serialiseJSON({
        status    = "connected",
        fuel      = turtle.getFuelLevel(),
        inventory = get_inventory(),
    }))
    return ws
end

local function handle_command(data)
    local cmd = data.command

    -- Movement
    if cmd == "move_forward" then
        return turtle.forward()
    elseif cmd == "move_back" then
        return turtle.back()
    elseif cmd == "move_up" then
        return turtle.up()
    elseif cmd == "move_down" then
        return turtle.down()
    elseif cmd == "turn_left" then
        return turtle.turnLeft()
    elseif cmd == "turn_right" then
        return turtle.turnRight()

    -- Mining
    elseif cmd == "dig" then
        return turtle.dig()
    elseif cmd == "dig_up" then
        return turtle.digUp()
    elseif cmd == "dig_down" then
        return turtle.digDown()

    -- Suck
    elseif cmd == "suck" then
        return turtle.suck()
    elseif cmd == "suck_up" then
        return turtle.suckUp()
    elseif cmd == "suck_down" then
        return turtle.suckDown()

    -- Drop (Fixed with tonumber)
    elseif cmd == "drop" then
        local drop_count = tonumber(data.count) or 64
        return turtle.drop(drop_count)
    elseif cmd == "drop_up" then
        local drop_count = tonumber(data.count) or 64
        return turtle.dropUp(drop_count)
    elseif cmd == "drop_down" then
        local drop_count = tonumber(data.count) or 64
        return turtle.dropDown(drop_count)

    -- Equip
    elseif cmd == "equip_left" then
        return turtle.equipLeft()
    elseif cmd == "equip_right" then
        return turtle.equipRight()

    -- Inspect
    elseif cmd == "inspect" then
        local ok, _ = turtle.inspect()
        return ok
    elseif cmd == "inspect_up" then
        local ok, _ = turtle.inspectUp()
        return ok
    elseif cmd == "inspect_down" then
        local ok, _ = turtle.inspectDown()
        return ok

    -- Place
    elseif cmd == "place" then
        return turtle.place()
    elseif cmd == "place_up" then
        return turtle.placeUp()
    elseif cmd == "place_down" then
        return turtle.placeDown()

    -- Inventory (Fixed slot with tonumber)
    elseif cmd == "select_slot" then
        local slot = tonumber(data.slot)
        if slot and slot >= 1 and slot <= 16 then
            return turtle.select(slot)
        else
            print("[TurtleNet] Invalid slot: " .. tostring(data.slot))
            return false
        end
    elseif cmd == "refuel" then
        return turtle.refuel()
    elseif cmd == "scan_inventory" then
        return true
    end

    print("[TurtleNet] Unknown command: " .. tostring(cmd))
    return false
end

local function run()
    wait_for_server()

    while true do
        local ws = connect()

        if ws then
            while true do
                local ok, msg = pcall(ws.receive, 30)

                if not ok then
                    print("[TurtleNet] WebSocket error, reconnecting...")
                    break
                end

                if msg then
                    local data = textutils.unserialiseJSON(msg)

                    if data then
                        if data.type == "ping" then
                            -- ignore keepalive
                        elseif data.command then
                            print("[TurtleNet] Command: " .. data.command)
                            local result = handle_command(data)

                            local inspect_data = nil
                            if data.command == "inspect" then
                                local _, block = turtle.inspect()
                                inspect_data = block
                            elseif data.command == "inspect_up" then
                                local _, block = turtle.inspectUp()
                                inspect_data = block
                            elseif data.command == "inspect_down" then
                                local _, block = turtle.inspectDown()
                                inspect_data = block
                            end

                            ws.send(textutils.serialiseJSON({
                                status    = result and "ok" or "failed",
                                command   = data.command,
                                fuel      = turtle.getFuelLevel(),
                                inventory = get_inventory(),
                                block     = inspect_data,
                            }))
                        end
                    end
                end
            end

            pcall(ws.close)
        end

        print("[TurtleNet] Reconnecting in 5s...")
        sleep(5)
    end
end

run()