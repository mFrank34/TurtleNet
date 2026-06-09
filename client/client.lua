local CONFIG = {
    host      = "192.168.10.2:8000",
    node_id   = os.getComputerLabel() or tostring(os.getComputerID()),
    node_type = "turtle",
}

-- Wait until server is reachable
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

-- Connect websocket
local function connect()
    local ws, err = http.websocket(
        "ws://" .. CONFIG.host .. "/api/v1/workers/ws/" .. CONFIG.node_id
    )

    if not ws then
        print("[TurtleNet] Failed to connect: " .. tostring(err))
        return nil
    end

    print("[TurtleNet] Connected as " .. CONFIG.node_id)
    return ws
end

-- Inventory scan
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

-- Command handler
local function handle_command(data)
    local cmd = data.command

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

    elseif cmd == "dig" then
        return turtle.dig()

    elseif cmd == "select_slot" then
        local slot = data.slot
        if slot and slot >= 1 and slot <= 16 then
            return turtle.select(slot)
        else
            print("[TurtleNet] Invalid slot: " .. tostring(slot))
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

-- Main loop
local function run()
    wait_for_server()

    while true do
        local ws = connect()

        if ws then
            local running = true

            while running do
                local ok, msg = pcall(ws.receive, 30)

                -- REAL connection error → reconnect
                if not ok then
                    print("[TurtleNet] WebSocket error, reconnecting...")
                    break
                end

                -- timeout → just continue waiting
                if msg then
                    local data = textutils.unserialiseJSON(msg)

                    if data then
                        if data.type == "ping" then
                            -- ignore keepalive

                        elseif data.command then
                            print("[TurtleNet] Command: " .. data.command)

                            local result = handle_command(data)

                            ws.send(textutils.serialiseJSON({
                                status    = result and "ok" or "failed",
                                command   = data.command,
                                fuel      = turtle.getFuelLevel(),
                                inventory = get_inventory(),
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