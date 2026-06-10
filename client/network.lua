-- gps_host.lua

print("Can't locate self — enter coords manually:")
io.write("X: ") x = tonumber(io.read())
io.write("Y: ") y = tonumber(io.read())
io.write("Z: ") z = tonumber(io.read())

print(string.format("Hosting at %d, %d, %d", x, y, z))
shell.run("gps", "host", x, y, z)