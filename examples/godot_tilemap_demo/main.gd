extends Node3D
## Loads a Game Level Architect tile-map package ("gla-export/1": level/<name>.glb + level/<name>.json) and lets you walk through it with WASD or the arrow
## keys. The JSON's walk rectangles are the only ground that can be stood on, so trees, walls, water and props block you without any physics. A level with
## two heights has a second floor (a raised platform) that can only be entered over its stairs.
##
##   godot --path . -- --level ink          the ink-on-paper dungeon (default: demo, the colour map)
##   godot --headless --path . -- --selftest [--level ink]      prints SELFTEST OK
##   godot --path . -- --shot out.png [--at x z]                saves a screenshot after a few frames (needs a display, e.g. xvfb-run)

const RADIUS: float = 0.35
const SPEED: float = 6.0

var level_name: String = "demo"
var rects: Array = []
var rects_upper: Array = []
var stairs: Array = []
var tile: float = 1.0
var level: int = 0
var player: Node3D
var camera: Camera3D
var package: Dictionary = {}


func _ready() -> void:
	_add_keys()
	var args: PackedStringArray = OS.get_cmdline_user_args()
	if "--level" in args:
		level_name = args[args.find("--level") + 1]
	var base: String = "res://level/" + level_name
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(base + ".json"))
	if typeof(parsed) != TYPE_DICTIONARY:
		push_error("cannot read " + base + ".json")
		get_tree().quit(1)
		return
	package = parsed
	var floors: Array = package["floors"]
	rects = floors[0]["walk_rects"]
	if floors.size() > 1:
		rects_upper = floors[1]["walk_rects"]
	stairs = package["stairs"]
	tile = float(package["tile_size"])
	var scene: PackedScene = load(base + ".glb")
	if scene != null:
		add_child(scene.instantiate())
	_add_light()
	player = _make_player()
	add_child(player)
	camera = Camera3D.new()
	camera.fov = 55.0
	add_child(camera)
	var start: Array = package["entrance"]["pos"]
	player.position = Vector3(float(start[0]), 0.0, float(start[2]))
	_follow()
	if "--selftest" in args:
		_selftest()
	elif "--shot" in args:
		if "--at" in args:                       # --at x z: put the player there (for screenshots)
			var i: int = args.find("--at")
			player.position = Vector3(float(args[i + 1]), 0.0, float(args[i + 2]))
			_follow()
		_shot(args[args.find("--shot") + 1])


func _add_keys() -> void:
	for pair: Array in [["ui_left", KEY_A], ["ui_right", KEY_D], ["ui_up", KEY_W], ["ui_down", KEY_S]]:
		var ev: InputEventKey = InputEventKey.new()
		ev.physical_keycode = pair[1] as Key
		InputMap.action_add_event(pair[0] as String, ev)


func _add_light() -> void:
	var sun: DirectionalLight3D = DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-55.0, -35.0, 0.0)
	sun.shadow_enabled = true
	sun.shadow_bias = 0.08
	sun.shadow_normal_bias = 2.5
	add_child(sun)
	var env: WorldEnvironment = WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_COLOR
	env.environment.background_color = Color(0.80, 0.81, 0.85) if level_name == "ink" else Color(0.55, 0.68, 0.85)
	env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.environment.ambient_light_color = Color(0.7, 0.7, 0.75)
	add_child(env)


func _make_player() -> Node3D:
	var body: Node3D = Node3D.new()
	var mesh: MeshInstance3D = MeshInstance3D.new()
	var cap: CapsuleMesh = CapsuleMesh.new()
	cap.radius = RADIUS
	cap.height = 1.4
	mesh.mesh = cap
	mesh.position.y = 0.7
	var mat: StandardMaterial3D = StandardMaterial3D.new()
	mat.albedo_color = Color(0.9, 0.3, 0.2)
	mesh.material_override = mat
	body.add_child(mesh)
	return body


func _in(list: Array, x: float, z: float) -> bool:
	for r: Array in list:
		if x >= float(r[0]) and x <= float(r[2]) and z >= float(r[1]) and z <= float(r[3]):
			return true
	return false


## The stairs tile under (x, z), or an empty dictionary.
func _stair_at(x: float, z: float) -> Dictionary:
	for st: Dictionary in stairs:
		var p: Array = st["pos"]
		if absf(x - float(p[0])) <= tile / 2.0 and absf(z - float(p[2])) <= tile / 2.0:
			return st
	return {}


## Unit vector (x, z) of the way up a flight of stairs; engine z is minus the blender y, so north is -z.
func _up_vec(st: Dictionary) -> Vector2:
	match String(st["up"]):
		"north":
			return Vector2(0.0, -1.0)
		"south":
			return Vector2(0.0, 1.0)
		"east":
			return Vector2(1.0, 0.0)
		_:
			return Vector2(-1.0, 0.0)


## One point may be stood on when it is on a stairs tile or inside the walk rectangles of the floor the player is on (both floors while on the stairs).
func _ok_point(x: float, z: float, on_stairs: bool) -> bool:
	if not _stair_at(x, z).is_empty():
		return true
	if on_stairs:
		return _in(rects, x, z) or _in(rects_upper, x, z)
	return _in(rects_upper if level == 1 else rects, x, z)


## True when a circle of RADIUS around (x, z) may be stood on (each corner of its bounding square is tested).
func can_stand(x: float, z: float) -> bool:
	var on_stairs: bool = not _stair_at(player.position.x, player.position.z).is_empty() if player != null else false
	for off: Vector2 in [Vector2(-RADIUS, -RADIUS), Vector2(RADIUS, -RADIUS), Vector2(RADIUS, RADIUS), Vector2(-RADIUS, RADIUS)]:
		if not _ok_point(x + off.x, z + off.y, on_stairs):
			return false
	return true


## Moves the player by (dx, dz) one axis at a time, then settles the floor and the height (the stairs rise smoothly).
func try_move(dx: float, dz: float) -> void:
	var p: Vector3 = player.position
	if dx != 0.0 and can_stand(p.x + dx, p.z):
		p.x += dx
		player.position = p
	if dz != 0.0 and can_stand(p.x, p.z + dz):
		p.z += dz
		player.position = p
	_settle()


func _settle() -> void:
	var p: Vector3 = player.position
	var st: Dictionary = _stair_at(p.x, p.z)
	var rise: float = float(package["floors"][1]["y"]) if package["floors"].size() > 1 else 0.0
	if not st.is_empty():
		var c: Array = st["pos"]
		var t: float = clampf(((Vector2(p.x - float(c[0]), p.z - float(c[2]))).dot(_up_vec(st)) / tile) + 0.5, 0.0, 1.0)
		p.y = float(st["rise"]) * t
	else:
		if _in(rects_upper, p.x, p.z):
			level = 1
		elif _in(rects, p.x, p.z):
			level = 0
		p.y = rise if level == 1 else 0.0
	player.position = p


func _process(delta: float) -> void:
	var dir: Vector2 = Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	var step: Vector2 = dir * SPEED * delta
	try_move(step.x, step.y)
	_follow()


func _follow() -> void:
	camera.position = player.position + Vector3(0.0, 16.0, 11.0)
	camera.look_at(player.position, Vector3.UP)


func _selftest() -> void:
	var ok: bool = true
	var e: Array = package["entrance"]["pos"]
	var x: Array = package["exit"]["pos"]
	if not can_stand(float(e[0]), float(e[2])):
		print("FAIL entrance is not standable")
		ok = false
	if not can_stand(float(x[0]), float(x[2])):
		print("FAIL exit is not standable")
		ok = false
	for pr: Dictionary in package["props"]:
		var pos: Array = pr["pos"]
		if can_stand(float(pos[0]), float(pos[2])):
			print("FAIL a prop sits on walkable ground: ", pr["kind"])
			ok = false
			break
	var blocked: int = 0
	for t: Array in package["trees"]:
		if not can_stand(float(t[0]), float(t[2])):
			blocked += 1
	print("rects ", rects.size(), "  upper rects ", rects_upper.size(), "  stairs ", stairs.size(), "  props ", package["props"].size(), "  trees ", package["trees"].size(), "  trees on blocked ground ", blocked)
	if not stairs.is_empty():
		# walk a flight of stairs from the tile below it to the platform above it: the floor changes and the height is the platform's
		var st: Dictionary = stairs[0]
		var c: Array = st["pos"]
		var up: Vector2 = _up_vec(st)
		player.position = Vector3(float(c[0]) - up.x * tile * 1.0, 0.0, float(c[2]) - up.y * tile * 1.0)
		level = 0
		for i: int in 40:
			try_move(up.x * 0.1, up.y * 0.1)
		var rise: float = float(st["rise"])
		if level != 1 or absf(player.position.y - rise) > 0.01:
			print("FAIL the stairs do not lead up: level ", level, " y ", player.position.y)
			ok = false
		else:
			print("stairs lead up to the platform at y ", player.position.y)
		# the cliff blocks: three tiles beside the stairs the platform edge cannot be climbed
		var side: Vector2 = Vector2(-up.y, up.x)
		for sign: float in [1.0, -1.0]:
			var sx: float = float(c[0]) - up.x * tile + side.x * 3.0 * tile * sign
			var sz: float = float(c[2]) - up.y * tile + side.y * 3.0 * tile * sign
			level = 0
			player.position = Vector3(sx, 0.0, sz)
			if can_stand(sx, sz) and _in(rects_upper, sx + up.x * tile * 2.0, sz + up.y * tile * 2.0):
				player.position = Vector3(sx, 0.0, sz)
				level = 0
				for i: int in 40:
					try_move(up.x * 0.1, up.y * 0.1)
				if level != 0 or player.position.y > 0.01:
					print("FAIL the platform edge can be climbed without stairs")
					ok = false
				else:
					print("the platform edge beside the stairs blocks")
				break
	print("SELFTEST OK" if ok else "SELFTEST FAILED")
	get_tree().quit(0 if ok else 1)


## Saves a screenshot after a few frames (needs a display, e.g. under xvfb-run) and quits.
func _shot(path: String) -> void:
	for i: int in 6:
		await get_tree().process_frame
	get_viewport().get_texture().get_image().save_png(path)
	get_tree().quit(0)
