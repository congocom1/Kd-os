"""Export only the assembled GLB reactor for the HUD's native renderer.

Run: blender --background --python scripts/export_reactor_bundle.py
The original bundle is never modified. Blender is needed only for this export.
"""
import json
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "arc-reactor-bundle/source/arc reactor unassembled+assembled.glb"
OUTPUT = ROOT / "assets/models/arc_reactor_assembled.obj"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(SOURCE))
root = bpy.data.objects.get("arc reactor assembled")
if root is None:
    raise RuntimeError("The bundle has no 'arc reactor assembled' node")
meshes = [obj for obj in root.children_recursive if obj.type == "MESH"]
if not meshes:
    raise RuntimeError("The assembled reactor contains no meshes")

# Bake world transforms, then center the assembly. Its shallowest dimension
# is the face normal; rotate that axis to Z for the existing HUD camera.
points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
center = (low + high) / 2
axis = min(range(3), key=lambda i: high[i] - low[i])
normal = Vector(tuple(float(i == axis) for i in range(3)))
rotation = normal.rotation_difference(Vector((0, 0, 1))).to_matrix().to_4x4()
bpy.ops.object.select_all(action="DESELECT")
materials = {}
for obj in meshes:
    obj.data = obj.data.copy()
    transform = obj.matrix_world.copy()
    transform.translation -= center
    obj.data.transform(rotation @ transform)
    obj.matrix_world.identity()
    obj.select_set(True)
    for mat in obj.data.materials:
        if mat is None or mat.name in materials:
            continue
        shader = next((n for n in mat.node_tree.nodes
                       if n.type == "BSDF_PRINCIPLED"), None) if mat.use_nodes else None
        color = list(mat.diffuse_color)
        emission = [0.0, 0.0, 0.0]
        if shader:
            color = list(shader.inputs["Base Color"].default_value)
            emission = list(shader.inputs["Emission Color"].default_value)[:3]
            strength = shader.inputs["Emission Strength"].default_value
            emission = [v * strength for v in emission]
        elif mat.use_nodes:
            # glTF unlit materials import as an Emission shader, not Principled.
            light = next((n for n in mat.node_tree.nodes
                          if n.type == "EMISSION"), None)
            if light:
                color = list(light.inputs["Color"].default_value)
                emission = [v * light.inputs["Strength"].default_value
                            for v in color[:3]]
        # OBJ replaces spaces with underscores in material identifiers.
        materials[mat.name.replace(" ", "_")] = {
            "color": color, "emission": emission,
        }

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.obj_export(
    filepath=str(OUTPUT), export_selected_objects=True,
    export_triangulated_mesh=True, export_normals=True, export_uv=False,
    export_materials=True, forward_axis="Y", up_axis="Z",
)
OUTPUT.with_suffix(".json").write_text(json.dumps(materials, indent=2) + "\n")
print(f"EXPORTED {len(meshes)} assembled parts to {OUTPUT}; face axis={axis}")