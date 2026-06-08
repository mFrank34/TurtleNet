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

local function connect()
    local ws, err = http.websocket("ws://" .. CONFIG.host .. "/api/v1/workers/ws/" .. CONFIG.node_id)
    if not ws then
        print("[TurtleNet] Failed to connect: " .. tostring(err))
        return nil
    end
    print("[TurtleNet] Connected as " .. CONFIG.node_id)
    return ws
end

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
    else
        print("[TurtleNet] Unknown command: " .. tostring(cmd))
        return false
    end
end

local function get_inventory()
    local inv = {}
    for slot = 1, 16 do
        local item = turtle.getItemDetail(slot)
        if item then
            inv[slot] = {
                name  = item.name,
                count = item.count,
            }
        end
    end
    return inv
end

local function run()
    wait_for_server()
    while true do
        local ws = connect()
        if ws then
            while true do
                local ok, msg = pcall(ws.receive, 30)
                if not ok or not msg then
                    print("[TurtleNet] Connection lost, reconnecting...")
                    pcall(ws.close)
                    break
                end

                local data = textutils.unserialiseJSON(msg)
                if data and data.type == "ping" then
                    -- ignore keepalive
                elseif data and data.command then
                    print("[TurtleNet] Command: " .. data.command)
                    local result = handle_command(data)
                    local gps = peripheral.find("gpsSensor")
                    local pos = gps and gps.getCoordinates() or {}
                    ws.send(textutils.serialiseJSON({
                        status    = result and "ok" or "failed",
                        command   = data.command,
                        fuel      = turtle.getFuelLevel(),
                        inventory = get_inventory(),
                        x         = pos.x,
                        y         = pos.y,
                        z         = pos.z,
                    }))
                end
            end
        end
        print("[TurtleNet] Retrying in 5s...")
        sleep(5)
    end
end

run()