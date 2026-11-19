extends Node3D
## Loads a Game Level Architect tile-map package (level/demo.glb + level/demo.json, "gla-export/1") and lets you walk through it
## with WASD or the arrow keys. The JSON's walk rectangles are the only ground that can be stood on, so trees, walls, water and
## props block you without any physics. Run with `-- --selftest` for a headless check that prints SELFTEST OK.

const PACKAGE: String = "res://level/demo"
const RADIUS: float = 0.35
const SPEED: float = 6.0

var rects: Array = []
var player: Node3D
var camera: Camera3D
var package: Dictionary = {}


func _ready() -> void:
	_add_keys()
	var text: String = FileAccess.get_file_as_string(PACKAGE + ".json")
	var parsed: Variant = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		push_error("cannot read " + PACKAGE + ".json")
		get_tree().quit(1)
		return
	package = parsed
	var floors: Array = package["floors"]
	rects = floors[0]["walk_rects"]
	var scene: PackedScene = load(PACKAGE + ".glb")
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
	var args: PackedStringArray = OS.get_cmdline_user_args()
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
	env.environment.background_color = Color(0.55, 0.68, 0.85)
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


## True when a circle of RADIUS around (x, z) lies inside the union of the walk rectangles (each corner of its bounding square is tested).
func can_stand(x: float, z: float) -> bool:
	for off: Vector2 in [Vector2(-RADIUS, -RADIUS), Vector2(RADIUS, -RADIUS), Vector2(RADIUS, RADIUS), Vector2(-RADIUS, RADIUS)]:
		if not _in_rects(x + off.x, z + off.y):
			return false
	return true


func _in_rects(x: float, z: float) -> bool:
	for r: Array in rects:
		if x >= float(r[0]) and x <= float(r[2]) and z >= float(r[1]) and z <= float(r[3]):
			return true
	return false


func _process(delta: float) -> void:
	var dir: Vector2 = Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	var step: Vector2 = dir * SPEED * delta
	var p: Vector3 = player.position
	if step.x != 0.0 and can_stand(p.x + step.x, p.z):
		p.x += step.x
	if step.y != 0.0 and can_stand(p.x, p.z + step.y):
		p.z += step.y
	player.position = p
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
	print("rects ", rects.size(), "  props ", package["props"].size(), "  trees ", package["trees"].size(), "  trees on blocked ground ", blocked)
	print("SELFTEST OK" if ok else "SELFTEST FAILED")
	get_tree().quit(0 if ok else 1)


## Saves a screenshot after a few frames (needs a display, e.g. under xvfb-run) and quits.
func _shot(path: String) -> void:
	for i: int in 6:
		await get_tree().process_frame
	get_viewport().get_texture().get_image().save_png(path)
	get_tree().quit(0)
