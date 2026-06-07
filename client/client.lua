local CONFIG = {
    host      = "http://127.0.0.1:8000",
    node_id   = os.getComputerLabel() or tostring(os.getComputerID()),
    node_type = "turtle", -- or "computer"
    interval  = 10,
}

local function ping()
    local body = '{"node_id":"' .. CONFIG.node_id .. '","node_type":"' .. CONFIG.node_type .. '"}'

    local response = http.post(
        CONFIG.host .. "/api/v1/workers/ping",
        body,
        { ["Content-Type"] = "application/json" }
    )

    if response then
        print("[TurtleNet] Ping OK - " .. textutils.formatTime(os.time()))
        response.close()
    else
        print("[TurtleNet] Ping failed")
    end
end

print("[TurtleNet] " .. CONFIG.node_id .. " starting...")
while true do
    local ok, err = pcall(ping)
    if not ok then
        print("[TurtleNet] Error: " .. tostring(err))
    end
    sleep(CONFIG.interval)
end