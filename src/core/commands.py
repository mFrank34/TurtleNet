# core/commands.py

class Move:
    FORWARD = "move_forward"
    BACK = "move_back"
    UP = "move_up"
    DOWN = "move_down"
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"


class Dig:
    FORWARD = "dig"
    UP = "dig_up"
    DOWN = "dig_down"


class Inspect:
    FORWARD = "inspect"
    UP = "inspect_up"
    DOWN = "inspect_down"


class Place:
    FORWARD = "place"
    UP = "place_up"
    DOWN = "place_down"


class Suck:
    FORWARD = "suck"
    UP = "suck_up"
    DOWN = "suck_down"


class Drop:
    FORWARD = "drop"
    UP = "drop_up"
    DOWN = "drop_down"


class Equip:
    LEFT = "equip_left"
    RIGHT = "equip_right"


class Inventory:
    SCAN = "scan_inventory"
    SELECT = "select_slot"
    REFUEL = "refuel"


class Peripheral:
    SCAN = "scan_peripherals"


class GPS:
    LOCATE = "get_location"
