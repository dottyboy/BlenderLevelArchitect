# Minimal offline mock of the `bpy` module -- lets WFC_Level_Solver and
# plain-Python mesh-building helpers (walls/stairs/doors/props) run and be
# stress-tested (hundreds of seeded trials in seconds) without launching a
# real Blender process at all. Used throughout this project's development
# for fast solver/connectivity iteration before ever touching real Blender.
#
# Scope is deliberately narrow: it fakes bpy.data (meshes/objects/materials
# /lights/collections), bpy.types.Operator/Panel/Scene, and bpy.props enough
# for the addon module to import and for its plain-Python mesh builders to
# run -- it does NOT model Geometry Nodes at all (no node types, no
# modifier evaluation). Anything that touches the GN graph (Blueprint's
# floor mesh, the Color Rooms/Corridors material switch, Add Ceiling, etc.)
# needs real Blender -- see tests/blender_headless_test.py /
# run_blender_tests.sh for that half of verification.
#
# Usage: put this directory on sys.path, `import stub_bpy` BEFORE importing
# the addon module (it registers itself into sys.modules on import), then
# load the addon via importlib as usual:
#
#   import sys, importlib.util
#   sys.path.insert(0, "tests")
#   import stub_bpy
#   spec = importlib.util.spec_from_file_location(
#       "levelArchitect_v2", "levelArchitect_v2.py"
#   )
#   addon = importlib.util.module_from_spec(spec)
#   spec.loader.exec_module(addon)
#   solver = addon.WFC_Level_Solver(width=20, length=20, height=2, ...)
#   solver.solve()

import sys
import types


class _Vec3:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z

    def __getitem__(self, key):
        return (self.x, self.y, self.z)[key]

    def _set(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Vert:
    def __init__(self, co):
        self.co = co


class _AttrItem:
    def __init__(self):
        self.value = None


class _AttrDataList(list):
    def foreach_set(self, prop_name, values):
        for item, v in zip(self, values):
            setattr(item, prop_name, v)

    def foreach_get(self, prop_name, out):
        for i, item in enumerate(self):
            out[i] = getattr(item, prop_name)


class _Attr:
    def __init__(self, n, domain='POINT'):
        self.data = _AttrDataList(_AttrItem() for _ in range(n))
        self.domain = domain


class _AttrCollection:
    def __init__(self, mesh):
        self._store = {}
        self._mesh = mesh

    def new(self, name, type, domain):
        n = len(self._mesh.polygons) if domain == 'FACE' else len(self._mesh.vertices)
        a = _Attr(n, domain)
        self._store[name] = a
        return a

    def get(self, name):
        return self._store.get(name)

    def __getitem__(self, name):
        return self._store[name]


class _Polygon:
    def __init__(self, index, vertices):
        self.index = index
        self.vertices = list(vertices)
        self.material_index = 0


class _VertexList(list):
    def foreach_get(self, prop_name, out):
        if prop_name == "co":
            for i, v in enumerate(self):
                out[i * 3], out[i * 3 + 1], out[i * 3 + 2] = v.co.x, v.co.y, v.co.z
        else:
            for i, v in enumerate(self):
                out[i] = getattr(v, prop_name)


class _FakeMesh:
    def __init__(self, name):
        self.name = name
        self.vertices = []
        self.polygons = []
        self.materials = []
        self.attributes = _AttrCollection(self)
        self.users = 0

    def from_pydata(self, verts, edges, faces):
        self.vertices = _VertexList(_Vert(_Vec3(*v)) for v in verts)
        self.polygons = [_Polygon(i, f) for i, f in enumerate(faces)]

    def update(self):
        pass


class _FakeMeshes:
    def __init__(self):
        self._all = []

    def new(self, name):
        m = _FakeMesh(name)
        self._all.append(m)
        return m

    def remove(self, mesh):
        if mesh in self._all:
            self._all.remove(mesh)


class _FakeMatrix:
    def copy(self):
        return self


class _FakeLight:
    def __init__(self, name, type):
        self.name = name
        self.type = type
        self.energy = 1000.0
        self.color = (1.0, 1.0, 1.0)
        self.shadow_soft_size = 0.25
        self.users = 0


class _FakeLights:
    def __init__(self):
        self._store = {}

    def new(self, name, type):
        light = _FakeLight(name, type)
        self._store[name] = light
        return light

    def get(self, name):
        return self._store.get(name)

    def remove(self, light):
        self._store.pop(light.name, None)

    def __iter__(self):
        return iter(list(self._store.values()))


class _FakeObject:
    def __init__(self, name, data):
        self.name = name
        self.data = data
        self.type = 'LIGHT' if isinstance(data, _FakeLight) else 'MESH'
        self.modifiers = types.SimpleNamespace(new=lambda **k: None, remove=lambda m: None)
        self.matrix_world = _FakeMatrix()
        self._location = _Vec3(0.0, 0.0, 0.0)
        self._rotation_euler = _Vec3(0.0, 0.0, 0.0)
        self._selected = False

    def select_set(self, v):
        self._selected = v

    # Real Blender's obj.location/.rotation_euler are Vector-like
    # properties: assigning a plain (x, y, z) tuple copies component-wise
    # into the existing Vector rather than replacing the attribute, so
    # obj.location.x etc. keeps working afterward -- these properties
    # mirror that instead of just clobbering with whatever's assigned.
    @property
    def location(self):
        return self._location

    @location.setter
    def location(self, value):
        self._location._set(*value)

    @property
    def rotation_euler(self):
        return self._rotation_euler

    @rotation_euler.setter
    def rotation_euler(self, value):
        self._rotation_euler._set(*value)


class _FakeObjects:
    def __init__(self):
        self._store = {}

    def new(self, name, data):
        obj = _FakeObject(name, data)
        return obj

    def get(self, name):
        return self._store.get(name)

    def __contains__(self, name):
        return name in self._store

    def __getitem__(self, name):
        return self._store[name]

    def __iter__(self):
        return iter(list(self._store.values()))

    def remove(self, obj, do_unlink=True):
        if obj.name in self._store:
            del self._store[obj.name]

    def link(self, obj):
        self._store[obj.name] = obj


class _FakeNodeTree:
    def __init__(self):
        self.nodes = []
        self.links = types.SimpleNamespace(new=lambda a, b: None)


class _FakeMaterial:
    def __init__(self, name):
        self.name = name
        self.diffuse_color = None
        self.node_tree = None
        self._use_nodes = False

    @property
    def use_nodes(self):
        return self._use_nodes

    @use_nodes.setter
    def use_nodes(self, v):
        self._use_nodes = v
        if v and self.node_tree is None:
            self.node_tree = _FakeNodeTree()


class _FakeMaterials:
    def __init__(self):
        self._store = {}

    def new(self, name):
        m = _FakeMaterial(name)
        self._store[name] = m
        return m

    def get(self, name):
        return self._store.get(name)

    def remove(self, mat):
        self._store.pop(mat.name, None)

    def __iter__(self):
        return iter(list(self._store.values()))


class _FakeCollectionChildren(list):
    def link(self, child):
        if child not in self:
            self.append(child)

    def __contains__(self, item):
        if isinstance(item, str):
            return any(c.name == item for c in self)
        return list.__contains__(self, item)


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        # Real Blender's bpy.data.objects is one flat registry regardless
        # of which collection an object is linked into -- sharing the
        # same _objects store here mirrors that, and means every test
        # lookup via stub_bpy._objects.get(...) keeps working regardless
        # of which collection wrapper an object went through.
        self.objects = _objects
        self.children = _FakeCollectionChildren()


class _FakeCollections:
    def __init__(self):
        self._store = {}

    def new(self, name):
        c = _FakeCollection(name)
        self._store[name] = c
        return c

    def get(self, name):
        return self._store.get(name)

    def remove(self, collection):
        self._store.pop(collection.name, None)

    def __iter__(self):
        return iter(list(self._store.values()))


_objects = _FakeObjects()

bpy = types.ModuleType("bpy")
bpy.data = types.SimpleNamespace(
    meshes=_FakeMeshes(),
    objects=_objects,
    materials=_FakeMaterials(),
    lights=_FakeLights(),
    collections=_FakeCollections(),
    node_groups=types.SimpleNamespace(new=lambda **k: None, remove=lambda g: None),
)


class _Operator:
    def report(self, level_set, message):
        print(f"[report] {level_set}: {message}")


bpy.types = types.SimpleNamespace(
    Operator=_Operator, Panel=object, Scene=types.SimpleNamespace(),
    PropertyGroup=object, UIList=object,
)
bpy.utils = types.SimpleNamespace(register_class=lambda c: None, unregister_class=lambda c: None)
bpy.props = types.ModuleType("bpy.props")
for name in (
    "IntProperty", "EnumProperty", "BoolProperty", "FloatProperty", "FloatVectorProperty",
    "StringProperty", "CollectionProperty",
):
    setattr(bpy.props, name, lambda *a, **k: None)
sys.modules["bpy"] = bpy
sys.modules["bpy.props"] = bpy.props
sys.modules["bpy.types"] = bpy.types
sys.modules["bpy.utils"] = bpy.utils


class FakeContext:
    def __init__(self):
        self.collection = types.SimpleNamespace(objects=_objects, children=_FakeCollectionChildren())
        self.view_layer = types.SimpleNamespace(objects=types.SimpleNamespace(active=None))
        self.active_object = None


class FakeScene:
    """Plain attribute bag standing in for context.scene -- Blender's real
    Scene exposes registered properties as attributes, which is all this
    test needs."""
    pass
