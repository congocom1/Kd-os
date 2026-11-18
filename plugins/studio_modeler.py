"""
3D Studio Modeler — JARVIS plugin for designing 3D models with the app's own
dev engine (core.studio_engine). Pure Python + numpy, no external 3D library.

Actions:
  create    <type> <name> [size/radius/height/segments...]  — box, sphere, cylinder, cone, torus, plane
  transform <name> translate|rotate|scale <values>          — move/resize/rotate an object
  boolean   <name_a> <name_b> union|difference|intersect [out_name]
  subdivide <name> [iterations]
  mirror    <name> x|y|z [merge]
  export    <name> <path.obj>
  import    <path.obj> <name>
  list                                              — list objects in the scene
  info    <name>                                    — vertex/face/bounds report
  delete  <name>                                    — remove an object
  clear                                             — empty the scene

Models persist in-memory for the session. Export to OBJ to open in Blender.
"""

from __future__ import annotations

from core.studio_engine import (
    box, sphere, cylinder, cone, torus, plane,
    translate, rotate, scale,
    boolean, subdivide, mirror,
    import_obj, export_obj,
    Scene,
)

PLUGIN = {
    "name": "studio_modeler",
    "description": (
        "Design 3D models with JARVIS's own 3D dev engine. Create primitives "
        "(box, sphere, cylinder, cone, torus, plane), then transform, boolean "
        "(union/difference/intersect), subdivide, mirror, and export to OBJ. "
        "Use 'create' to add an object, 'list'/'info' to inspect, 'export' to "
        "write a .obj file you can open in Blender. No external 3D library needed."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "'create', 'transform', 'boolean', 'subdivide', "
                               "'mirror', 'export', 'import', 'list', 'info', 'delete', 'clear'",
            },
            "otype": {
                "type": "STRING",
                "description": "Primitive type for create: box, sphere, cylinder, cone, torus, plane",
            },
            "name": {
                "type": "STRING",
                "description": "Name of the object to create or modify",
            },
            "out_name": {
                "type": "STRING",
                "description": "Result name for boolean (defaults to name_a)",
            },
            "kind": {
                "type": "STRING",
                "description": "For transform: 'translate', 'rotate', or 'scale'",
            },
            "values": {
                "type": "STRING",
                "description": "Comma-separated numbers (e.g. '1,0,0' or '0,0.5,0')",
            },
            "axis": {
                "type": "STRING",
                "description": "Mirror axis: x, y, or z",
            },
            "merge": {
                "type": "STRING",
                "description": "For mirror: 'true' to merge mirrored copy into original",
            },
            "iterations": {
                "type": "STRING",
                "description": "Subdivide iterations (default 1)",
            },
            "operation": {
                "type": "STRING",
                "description": "Boolean: union, difference, or intersect",
            },
            "resolution": {
                "type": "STRING",
                "description": "Boolean voxel resolution (default 32)",
            },
            "path": {
                "type": "STRING",
                "description": "File path for export/import (.obj)",
            },
            "size": {
                "type": "STRING",
                "description": "Box size as 'x,y,z' (default '1,1,1')",
            },
            "radius": {
                "type": "STRING",
                "description": "Sphere/cylinder/cone radius (default 1)",
            },
            "height": {
                "type": "STRING",
                "description": "Cylinder/cone height (default 1)",
            },
            "segments": {
                "type": "STRING",
                "description": "Segment count (default 32)",
            },
        },
        "required": ["action"],
    },
}

def _test_engine(values: dict) -> tuple[bool, str]:
    """Quick smoke test of the 3D engine."""
    from core.studio_engine import box, sphere, boolean

    try:
        res = int(values.get("default_resolution", 32) or 32)
        c = box((2, 2, 2))
        s = sphere(0.8, 16, 8)
        diff = boolean(c, s, "difference", resolution=min(res, 48))
        if len(diff["verts"]) == 0:
            return False, "Engine produced empty mesh."
        return True, f"Engine OK — {len(diff['verts'])} verts, {len(diff['faces'])} faces."
    except Exception as e:
        return False, f"Engine error: {e}"


# ── Plugin settings (shown in ⚙ → PLUGINS → studio_modeler) ────────────────
PLUGIN_SETTINGS = {
    "namespace": "studio_modeler",
    "title": "3D Studio Modeler",
    "fields": [
        {
            "key": "default_resolution",
            "label": "Default boolean voxel resolution",
            "type": "number",
            "default": 32,
            "placeholder": "32",
        },
        {
            "key": "default_output_dir",
            "label": "Default export directory",
            "type": "text",
            "default": "",
            "placeholder": "/home/user/3d_models",
        },
    ],
    "action": {
        "label": "TEST ENGINE",
        "run": _test_engine,
    },
}


# One scene lives for the session so objects persist across plugin calls —
# and it is the visual display manager's scene, so the 3D workshop viewport
# always shows what the assistant just built (no mirrored copies to drift).
_FALLBACK_SCENE = None


def _get_scene() -> Scene:
    global _FALLBACK_SCENE
    try:
        from core.visual_display_manager import get_visual_display_manager
        scene = get_visual_display_manager().get_scene()
        if scene is not None:
            return scene
    except Exception:
        pass
    if _FALLBACK_SCENE is None:
        _FALLBACK_SCENE = Scene()
    return _FALLBACK_SCENE


def _push_visual(name: str | None = None):
    """Refresh the 3D workshop viewport after a mutation (best-effort)."""
    try:
        from core.visual_display_manager import get_visual_display_manager
        mgr = get_visual_display_manager()
        mgr._push_scene()
        mgr.set_current_view("3d_studio")
    except Exception:
        pass


class _SceneProxy:
    """Attribute-style shim so existing `_SCENE.add(...)` call sites read
    unchanged while the real scene lives in the display manager."""

    def __getattr__(self, item):
        return getattr(_get_scene(), item)


_SCENE = _SceneProxy()


def _nums(text, default=None):
    if text is None or str(text).strip() == "":
        return default
    try:
        return [float(t) for t in str(text).split(",")]
    except ValueError:
        return default


def _primitive(otype, **kw):
    otype = (otype or "box").lower()
    if otype == "box":
        size = _nums(kw.get("size"), [1.0, 1.0, 1.0])
        return box(tuple(size))
    if otype == "sphere":
        return sphere(radius=_nums(kw.get("radius"), [1.0])[0],
                      segments=int(_nums(kw.get("segments"), [32])[0]))
    if otype == "cylinder":
        return cylinder(radius=_nums(kw.get("radius"), [1.0])[0],
                        height=_nums(kw.get("height"), [1.0])[0],
                        segments=int(_nums(kw.get("segments"), [32])[0]),
                        open_ends=str(kw.get("open_ends", "")).lower() == "true")
    if otype == "cone":
        return cone(radius=_nums(kw.get("radius"), [1.0])[0],
                    height=_nums(kw.get("height"), [1.0])[0],
                    segments=int(_nums(kw.get("segments"), [32])[0]),
                    open_base=str(kw.get("open_base", "")).lower() == "true")
    if otype == "torus":
        return torus(major_radius=_nums(kw.get("major_radius"), [1.0])[0],
                     minor_radius=_nums(kw.get("minor_radius"), [0.3])[0],
                     major_segments=int(_nums(kw.get("major_segments"), [32])[0]),
                     minor_segments=int(_nums(kw.get("minor_segments"), [16])[0]))
    if otype == "plane":
        size = _nums(kw.get("size"), [1.0, 1.0])
        segs = _nums(kw.get("segments"), [1, 1])
        return plane(tuple(size), tuple(int(s) for s in segs))
    raise ValueError(f"unknown primitive type: {otype}")


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "").strip().lower()
    if not action:
        return "Sir, please specify an action: create, transform, boolean, subdivide, mirror, export, import, list, info, delete, or clear."

    try:
        if action == "list":
            names = _SCENE.list_names()
            if not names:
                return "The studio scene is empty, sir."
            lines = []
            for n in names:
                info = _SCENE.info(n)
                lines.append(f"• {n}: {info['vertices']} verts, {info['faces']} faces")
            return "Studio objects:\\n" + "\\n".join(lines)

        if action == "clear":
            _SCENE.clear()
            _push_visual()
            return "Studio scene cleared, sir."

        if action == "create":
            otype = parameters.get("otype") or parameters.get("type") or "box"
            name = (parameters.get("name") or otype).strip()
            if not name:
                return "Sir, please give the object a name."
            kwargs = dict(parameters)
            kwargs.pop("otype", None)
            kwargs.pop("type", None)
            mesh = _primitive(otype, **kwargs)
            _SCENE.add(name, mesh)
            _push_visual(name)
            info = _SCENE.info(name)
            return (f"Created {name} ({otype}): {info['vertices']} verts, "
                    f"{info['faces']} faces.")

        if action == "info":
            name = (parameters.get("name") or "").strip()
            if not name:
                return "Sir, please specify a name."
            info = _SCENE.info(name)
            if info is None:
                return f"No object named '{name}' in the scene."
            bmin = [round(v, 3) for v in info["bounds_min"]]
            bmax = [round(v, 3) for v in info["bounds_max"]]
            return (f"{name}: {info['vertices']} vertices, {info['faces']} faces; "
                    f"bounds {bmin} to {bmax}.")

        if action == "delete":
            name = (parameters.get("name") or "").strip()
            if not name:
                return "Sir, please specify a name."
            if _SCENE.get(name) is None:
                return f"No object named '{name}' in the scene."
            _SCENE.remove(name)
            _push_visual()
            return f"Deleted {name}, sir."

        mesh = _SCENE.get((parameters.get("name") or "").strip())
        if mesh is None and action != "import":
            return (f"No object named '{parameters.get('name')}' in the scene. "
                    f"Use 'list' to see available objects.")

        if action == "transform":
            kind = (parameters.get("kind") or "").strip().lower()
            vals = _nums(parameters.get("values"), [0.0, 0.0, 0.0])
            if len(vals) != 3:
                return "Sir, transform needs three comma-separated values."
            if kind == "translate":
                mesh = translate(mesh, *vals)
            elif kind == "rotate":
                mesh = rotate(mesh, *vals)
            elif kind == "scale":
                mesh = scale(mesh, *vals)
            else:
                return "Sir, transform kind must be translate, rotate, or scale."
            name = (parameters.get("name") or "").strip()
            _SCENE.add(name, mesh)
            _push_visual(name)
            return f"Transformed {name} ({kind} {vals}), sir."

        if action == "boolean":
            name_a = (parameters.get("name") or "").strip()
            name_b = (parameters.get("name_b") or parameters.get("name2") or "").strip()
            if not name_a or not name_b:
                return "Sir, boolean needs both 'name' and 'name_b'."
            ma = _SCENE.get(name_a)
            mb = _SCENE.get(name_b)
            if ma is None or mb is None:
                return "Sir, both boolean operands must exist in the scene."
            op = (parameters.get("operation") or "union").strip().lower()
            res = int(_nums(parameters.get("resolution"), [32])[0])
            out_name = (parameters.get("out_name") or name_a).strip()
            result = boolean(ma, mb, op, resolution=res)
            _SCENE.add(out_name, result)
            _push_visual(out_name)
            info = _SCENE.info(out_name)
            return (f"Boolean {op} → {out_name}: {info['vertices']} verts, "
                    f"{info['faces']} faces, sir.")

        if action == "subdivide":
            name = (parameters.get("name") or "").strip()
            iters = int(_nums(parameters.get("iterations"), [1])[0])
            result = subdivide(mesh, iterations=iters)
            _SCENE.add(name, result)
            _push_visual(name)
            info = _SCENE.info(name)
            return (f"Subdivided {name} ({iters}x): {info['vertices']} verts, "
                    f"{info['faces']} faces, sir.")

        if action == "mirror":
            name = (parameters.get("name") or "").strip()
            axis = (parameters.get("axis") or "x").strip().lower()
            if axis not in ("x", "y", "z"):
                return "Sir, mirror axis must be x, y, or z."
            do_merge = str(parameters.get("merge", "false")).lower() == "true"
            result = mirror(mesh, axis=axis, merge=do_merge)
            out_name = name if do_merge else (parameters.get("out_name") or f"{name}_mirror").strip()
            _SCENE.add(out_name, result)
            _push_visual(out_name)
            info = _SCENE.info(out_name)
            extra = " (merged)" if do_merge else ""
            return f"Mirrored {name} across {axis}{extra}: {info['vertices']} verts, {info['faces']} faces, sir."

        if action == "export":
            name = (parameters.get("name") or "").strip()
            path = (parameters.get("path") or "").strip()
            if not name or not path:
                return "Sir, export needs both 'name' and 'path'."
            export_obj(mesh, path)
            return f"Exported {name} to {path}, sir."

        if action == "import":
            path = (parameters.get("path") or "").strip()
            name = (parameters.get("name") or "imported").strip()
            if not path:
                return "Sir, import needs a 'path'."
            mesh = import_obj(path)
            _SCENE.add(name, mesh)
            _push_visual(name)
            info = _SCENE.info(name)
            return (f"Imported {path} as {name}: {info['vertices']} verts, "
                    f"{info['faces']} faces, sir.")

        return f"Sir, I don't recognize the action '{action}'."

    except Exception as e:
        return f"Sir, studio_modeler failed: {e}"
