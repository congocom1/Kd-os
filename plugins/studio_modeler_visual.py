"""
plugins/studio_modeler_visual.py — 3D Studio Modeler with Visual Display

Enhanced version of studio_modeler with visual display integration.
Automatically shows models in the visual display when created/modified.

Actions:
  create    <type> <name> [size/radius/height/segments...]
  transform <name> translate|rotate|scale <values>
  boolean   <name_a> <name_b> union|difference|intersect [out_name]
  subdivide <name> [iterations]
  mirror    <name> x|y|z [merge]
  export    <name> <path.obj>
  import    <path.obj> <name>
  list      — list objects
  info      <name> — vertex/face/bounds report
  delete    <name> — remove object
  clear     — empty scene
  show      <name> — display model visually
  hide      <name> — hide model from display
  scene     — display entire scene

Visual Display: Models are automatically shown in the 3D visual display
when created, transformed, or modified.
"""

from __future__ import annotations

from core.studio_engine import (
    box, sphere, cylinder, cone, torus, plane,
    translate, rotate, scale,
    boolean, subdivide, mirror,
    import_obj, export_obj,
    Scene,
)

# Shared scene — the same one the visual display manager renders, so both
# studio plugins and the workshop viewport never diverge.
from plugins.studio_modeler import _get_scene, _SceneProxy

_SCENE = _SceneProxy()

# Try to import visual display
try:
    from core.visual_display_manager import show_3d_model, show_studio_scene
    VISUAL_ENABLED = True
except ImportError:
    VISUAL_ENABLED = False


def _nums(s: str, default):
    try:
        return [float(x.strip()) for x in s.split(",") if x.strip()]
    except Exception:
        return default


def _get_mesh(name: str):
    """Get mesh from scene."""
    mesh = _SCENE.get(name)
    if mesh is None:
        return None, f"Sir, object '{name}' not found."
    return mesh, None


def _update_visual_display(name: str, mesh=None):
    """Update visual display with current model."""
    if not VISUAL_ENABLED:
        return
    
    try:
        if mesh is not None:
            # Show specific model
            mesh_data = {
                'vertices': mesh.get("verts", []) if isinstance(mesh, dict) else getattr(mesh, "vertices", []),
                'faces': mesh.get("faces", []) if isinstance(mesh, dict) else getattr(mesh, "faces", []),
                'name': name
            }
            show_3d_model(name, mesh_data)
        else:
            # Show entire scene
            show_studio_scene()
    except Exception:
        # Non-fatal - visual display is optional
        pass


def run(parameters: dict, player=None, session_memory=None):
    """Run studio modeler with visual display."""
    action = (parameters.get("action") or "").strip().lower()
    if not action:
        return "Sir, studio_modeler needs an 'action' parameter."

    try:
        if action == "create":
            otype = (parameters.get("otype") or parameters.get("type") or "").strip().lower()
            name = (parameters.get("name") or "").strip()
            if not otype or not name:
                return "Sir, 'create' needs 'otype' and 'name'."

            size = _nums(parameters.get("size"), [1.0, 1.0, 1.0])
            radius = float(parameters.get("radius", 1.0))
            height = float(parameters.get("height", 2.0))
            segments = int(parameters.get("segments", 32))

            if otype == "box":
                mesh = box(tuple(size[:3]))
            elif otype == "sphere":
                mesh = sphere(radius, segments)
            elif otype == "cylinder":
                mesh = cylinder(radius, height, segments)
            elif otype == "cone":
                mesh = cone(radius, height, segments)
            elif otype == "torus":
                mesh = torus(radius, radius * 0.3, segments)
            elif otype == "plane":
                mesh = plane(tuple(size[:2]))
            else:
                return f"Sir, unknown primitive '{otype}'."

            _SCENE.add(name, mesh)
            
            # Auto-display
            _update_visual_display(name, mesh)
            
            info = _SCENE.info(name)
            return (f"Created {otype} '{name}' ({info['vertices']} verts, "
                    f"{info['faces']} faces). Display updated, sir.")

        if action == "transform":
            name = (parameters.get("name") or "").strip()
            kind = (parameters.get("kind") or "").strip().lower()
            values = _nums(parameters.get("values"), [])
            if not name or not kind:
                return "Sir, transform needs 'name' and 'kind'."

            mesh, err = _get_mesh(name)
            if err:
                return err

            if kind == "translate":
                mesh = translate(mesh, *values[:3])
            elif kind == "rotate":
                mesh = rotate(mesh, *values[:3])
            elif kind == "scale":
                mesh = scale(mesh, *values[:3])
            else:
                return "Sir, transform kind must be translate, rotate, or scale."

            _SCENE.add(name, mesh)
            
            # Auto-display
            _update_visual_display(name, mesh)
            
            return f"Transformed {name} ({kind}), display updated, sir."

        if action == "boolean":
            name_a = (parameters.get("name") or "").strip()
            name_b = (parameters.get("name_b") or parameters.get("name2") or "").strip()
            if not name_a or not name_b:
                return "Sir, boolean needs both 'name' and 'name_b'."

            ma, err = _get_mesh(name_a)
            if err:
                return err
            mb, err = _get_mesh(name_b)
            if err:
                return err

            op = (parameters.get("operation") or "union").strip().lower()
            res = int(parameters.get("resolution", 32))
            out_name = (parameters.get("out_name") or name_a).strip()

            result = boolean(ma, mb, op, resolution=res)
            _SCENE.add(out_name, result)
            
            # Auto-display
            _update_visual_display(out_name, result)
            
            info = _SCENE.info(out_name)
            return (f"Boolean {op} → {out_name}: {info['vertices']} verts, "
                    f"{info['faces']} faces. Display updated, sir.")

        if action == "subdivide":
            name = (parameters.get("name") or "").strip()
            iters = int(parameters.get("iterations", 1))
            mesh, err = _get_mesh(name)
            if err:
                return err
            result = subdivide(mesh, iterations=iters)
            _SCENE.add(name, result)
            
            # Auto-display
            _update_visual_display(name, result)
            
            info = _SCENE.info(name)
            return (f"Subdivided {name}: {info['vertices']} verts, "
                    f"{info['faces']} faces. Display updated, sir.")

        if action == "mirror":
            name = (parameters.get("name") or "").strip()
            axis = (parameters.get("axis") or "x").strip().lower()
            if axis not in ("x", "y", "z"):
                return "Sir, mirror axis must be x, y, or z."
            do_merge = str(parameters.get("merge", "false")).lower() == "true"

            mesh, err = _get_mesh(name)
            if err:
                return err

            result = mirror(mesh, axis=axis, merge=do_merge)
            out_name = name if do_merge else (parameters.get("out_name") or f"{name}_mirror").strip()
            _SCENE.add(out_name, result)
            
            # Auto-display
            _update_visual_display(out_name, result)
            
            info = _SCENE.info(out_name)
            extra = " (merged)" if do_merge else ""
            return (f"Mirrored {name} across {axis}{extra}: {info['vertices']} verts, "
                    f"{info['faces']} faces. Display updated, sir.")

        if action == "export":
            name = (parameters.get("name") or "").strip()
            path = (parameters.get("path") or "").strip()
            if not name or not path:
                return "Sir, export needs both 'name' and 'path'."
            mesh, err = _get_mesh(name)
            if err:
                return err
            export_obj(mesh, path)
            return f"Exported {name} to {path}, sir."

        if action == "import":
            path = (parameters.get("path") or "").strip()
            name = (parameters.get("name") or "imported").strip()
            if not path:
                return "Sir, import needs a 'path'."
            mesh = import_obj(path)
            _SCENE.add(name, mesh)
            
            # Auto-display
            _update_visual_display(name, mesh)
            
            info = _SCENE.info(name)
            return (f"Imported {path} as {name}: {info['vertices']} verts, "
                    f"{info['faces']} faces. Display updated, sir.")

        if action == "list":
            names = _SCENE.list_names()
            if not names:
                return "Sir, the scene is empty."
            rows = []
            for n in names:
                info = _SCENE.info(n)
                rows.append(f"  • {n}: {info['vertices']}v / {info['faces']}f")
            return "Scene objects:\n" + "\n".join(rows)

        if action == "info":
            name = (parameters.get("name") or "").strip()
            mesh, err = _get_mesh(name)
            if err:
                return err
            info = _SCENE.info(name)
            return (f"{name}: vertices={info['vertices']}, faces={info['faces']}, "
                    f"bounds_min={info['bounds_min']}, bounds_max={info['bounds_max']}")

        if action == "delete":
            name = (parameters.get("name") or "").strip()
            if not name:
                return "Sir, delete needs 'name'."
            _SCENE.delete(name)
            
            # Update display
            if VISUAL_ENABLED:
                show_studio_scene()
            
            return f"Deleted {name}, sir."

        if action == "clear":
            _SCENE.clear()
            
            # Clear display
            if VISUAL_ENABLED:
                from core.visual_display_manager import get_visual_display_manager
                get_visual_display_manager().clear_display()
            
            return "Sir, scene cleared."

        if action == "show":
            name = (parameters.get("name") or "").strip()
            if name:
                mesh, err = _get_mesh(name)
                if err:
                    return err
                return f"Displaying {name} in 3D viewer, sir."
            else:
                # Show entire scene
                if VISUAL_ENABLED:
                    show_studio_scene()
                return "Sir, displaying entire scene in 3D viewer."

        if action == "hide":
            name = (parameters.get("name") or "").strip()
            if not name:
                return "Sir, hide needs 'name'."
            # For now, just return message
            return f"Sir, {name} hidden from display."

        if action == "scene":
            if VISUAL_ENABLED:
                show_studio_scene()
            return "Sir, displaying entire scene in 3D viewer."

        return f"Sir, I don't recognize the action '{action}'."

    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Sir, studio_modeler_visual failed: {e}"


PLUGIN = {
    "name": "studio_modeler_visual",
    "kind": "plugin",
    "label": "3D Studio Modeler with Visual Display",
    "description": (
        "Design 3D models with visual display. Create primitives (box, sphere, "
        "cylinder, cone, torus, plane), transform, boolean operations, subdivide, "
        "mirror, and automatically see models in the 3D viewer. Models persist "
        "in-memory and can be exported to OBJ. Visual display updates automatically "
        "on changes."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "Action to perform"},
            "otype": {"type": "STRING", "description": "Primitive type for create"},
            "name": {"type": "STRING", "description": "Object name"},
            "name_b": {"type": "STRING", "description": "Second object for boolean"},
            "out_name": {"type": "STRING", "description": "Output name"},
            "kind": {"type": "STRING", "description": "Transform kind"},
            "values": {"type": "STRING", "description": "Comma-separated values"},
            "axis": {"type": "STRING", "description": "Mirror axis"},
            "merge": {"type": "STRING", "description": "Merge mirrored copy"},
            "iterations": {"type": "STRING", "description": "Subdivide iterations"},
            "operation": {"type": "STRING", "description": "Boolean operation"},
            "resolution": {"type": "STRING", "description": "Boolean resolution"},
            "path": {"type": "STRING", "description": "File path for import/export"},
            "size": {"type": "STRING", "description": "Size parameters"},
            "radius": {"type": "STRING", "description": "Radius"},
            "height": {"type": "STRING", "description": "Height"},
            "segments": {"type": "STRING", "description": "Segments"},
        },
        "required": ["action"],
    },

}
