local CONFIG = {
	host = "192.168.10.2:8000",
	node_id = os.getComputerLabel() or tostring(os.getComputerID()),
	node_type = turtle and "turtle" or "computer",
}

local function wait_for_server()
	while true do
		local ok = http.get("http://" .. CONFIG.host .. "/health")
		if ok then
			ok.close()
			print("[TurtleNet] Server is up, connecting...")
			sleep(0.1)
			return
		end
		print("[TurtleNet] Server unavailable, retrying in 5s...")
		sleep(5)
	end
end

local function get_inventory()
	local inv = {}
	if not turtle then
		return { note = "Standard computer terminal - no internal inventory slots" }
	end

	for slot = 1, 16 do
		local item = turtle.getItemDetail(slot)
		if item then
			inv[tostring(slot)] = {
				name = item.name,
				count = item.count,
			}
		end
	end
	return inv
end

local function get_safe_fuel()
	if turtle then
		return turtle.getFuelLevel()
	end
	return "infinite"
end

local function get_location()
	local modem = peripheral.find("modem", function(name, m)
		return m.isWireless()
	end)

	if not modem then
		return nil, "no wireless modem found"
	end

	local x, y, z = gps.locate(5)

	if not x then
		return nil, "no gps signal"
	end

	return { x = x, y = y, z = z }
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

	local success, send_err = pcall(function()
		ws.send(textutils.serialiseJSON({
			status = "connected",
			fuel = get_safe_fuel(),
			inventory = get_inventory(),
		}))
	end)

	if not success then
		print("[TurtleNet] Handshake transmission failed: " .. tostring(send_err))
		pcall(ws.close)
		return nil
	end

	return ws
end

local function handle_command(data)
	local cmd = data.command

	if turtle then
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

		-- Drop
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

		-- Inventory
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
		end
	end

	-- Global commands accessible by ALL node types
	if cmd == "scan_inventory" then
		return true

	elseif cmd == "scan_peripherals" then
		local peripherals = {}
		for _, side in ipairs({"left", "right", "top", "bottom", "front", "back"}) do
			local p = peripheral.getType(side)
			if p then
				peripherals[side] = p
			end
		end
		return true, peripherals

	elseif cmd == "get_location" then
		local loc, err = get_location()
		if loc then
			return true, loc
		else
			print("[TurtleNet] GPS failed: " .. tostring(err))
			return false
		end
	end

	print("[TurtleNet] Command unavailable or unknown on this node type: " .. tostring(cmd))
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
							ws.send(textutils.serialiseJSON({
								status = "ok",
								fuel = get_safe_fuel(),
								inventory = get_inventory(),
							}))
						elseif data.command then
							print("[TurtleNet] Command: " .. data.command)

							local result, extra_data = handle_command(data)

							local inspect_data = nil
							if turtle then
								if data.command == "inspect" then
									local success, block = turtle.inspect()
									inspect_data = success and block or { error = block }
								elseif data.command == "inspect_up" then
									local success, block = turtle.inspectUp()
									inspect_data = success and block or { error = block }
								elseif data.command == "inspect_down" then
									local success, block = turtle.inspectDown()
									inspect_data = success and block or { error = block }
								end
							end

							ws.send(textutils.serialiseJSON({
								status = result and "ok" or "failed",
								command = data.command,
								fuel = get_safe_fuel(),
								inventory = get_inventory(),
								block = inspect_data,
								peripherals = data.command == "scan_peripherals" and extra_data or nil,
								location = data.command == "get_location" and extra_data or nil,
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