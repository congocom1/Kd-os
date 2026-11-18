"""Headless Blender export of the Arc Reactor model to OBJ.

Run:  blender --background --python scripts/export_reactor.py

Produces assets/models/arc_reactor.obj (+ .mtl) — committed to the repo so
builds and end users never need Blender installed.
"""
import bpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "arc_reactor_model" / "ArcReactor.blend"
OUT = ROOT / "assets" / "models" / "arc_reactor.obj"

bpy.ops.wm.open_mainfile(filepath=str(SRC))

# Drop boolean cutters / set dressing that are not part of the reactor itself.
CUTTER_NAMES = {"Plane", "SolderingBit", "HOleWheel", "Holer", "Cube"}
for obj in list(bpy.context.scene.objects):
    if obj.name in CUTTER_NAMES or obj.hide_render:
        bpy.data.objects.remove(obj, do_unlink=True)

# Apply transforms so the OBJ is ready to render as-is.
for obj in bpy.context.scene.objects:
    obj.select_set(True)
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

OUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.obj_export(
    filepath=str(OUT),
    export_selected_objects=False,
    export_materials=True,
    export_triangulated_mesh=True,
    export_normals=True,
    export_uv=False,
    apply_modifiers=True,
)
print(f"EXPORTED {OUT}")
