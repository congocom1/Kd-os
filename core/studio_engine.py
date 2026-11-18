"""
JARVIS 3D Studio Engine — self-contained dev engine for designing 3D models.

Pure Python + numpy, no external 3D library required. Builds triangle meshes
from primitives, lets you transform / boolean / subdivide / mirror them, and
import/export Wavefront OBJ so you can open the results in Blender or any other
tool.

Coordinate system (right-handed): +x right, +y up, +z toward viewer.
All meshes are dicts: {"verts": (N,3) float32, "faces": (M,3) int32}.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

__all__ = [
    "new_mesh", "box", "sphere", "cylinder", "cone", "torus", "plane",
    "transform", "translate", "rotate", "scale",
    "boolean", "subdivide", "mirror",
    "import_obj", "export_obj",
    "Scene",
]


# ── core mesh helpers ────────────────────────────────────────────────────────

def new_mesh(verts, faces):
    """Return a mesh dict. verts (N,3), faces (M,3)."""
    return {
        "verts": np.asarray(verts, dtype=np.float32).reshape(-1, 3),
        "faces": np.asarray(faces, dtype=np.int32).reshape(-1, 3),
    }


def _cat(meshes):
    """Concatenate several meshes into one, offsetting face indices."""
    out_v, out_f = [], []
    off = 0
    for m in meshes:
        out_v.append(m["verts"])
        out_f.append(m["faces"] + off)
        off += len(m["verts"])
    return new_mesh(np.vstack(out_v), np.vstack(out_f))


# ── primitives ───────────────────────────────────────────────────────────────

def box(size=(1.0, 1.0, 1.0)):
    sx, sy, sz = (float(v) / 2 for v in size)
    v = np.array([
        [-sx, -sy, -sz], [ sx, -sy, -sz], [ sx,  sy, -sz], [-sx,  sy, -sz],
        [-sx, -sy,  sz], [ sx, -sy,  sz], [ sx,  sy,  sz], [-sx,  sy,  sz],
    ], dtype=np.float32)
    f = np.array([
        [0, 1, 2], [0, 2, 3],   # back
        [4, 5, 6], [4, 6, 7],   # front
        [0, 4, 5], [0, 5, 1],   # bottom
        [2, 3, 7], [2, 7, 6],   # top
        [0, 3, 7], [0, 7, 4],   # left
        [1, 5, 6], [1, 6, 2],   # right
    ], dtype=np.int32)
    return new_mesh(v, f)


def sphere(radius=1.0, segments=32, rings=16):
    radius = float(radius)
    segs = max(4, int(segments))
    rings = max(2, int(rings))
    verts, faces = [], []
    for ri in range(rings + 1):
        phi = math.pi * ri / rings
        for si in range(segs):
            theta = 2 * math.pi * si / segs
            x = radius * math.sin(phi) * math.cos(theta)
            y = radius * math.cos(phi)
            z = radius * math.sin(phi) * math.sin(theta)
            verts.append((x, y, z))
    def vid(r, s):
        return r * segs + s
    for ri in range(rings):
        for si in range(segs):
            s0 = si
            s1 = (si + 1) % segs
            faces.append([vid(ri, s0), vid(ri, s1), vid(ri + 1, s1)])
            faces.append([vid(ri, s0), vid(ri + 1, s1), vid(ri + 1, s0)])
    return new_mesh(verts, faces)


def cylinder(radius=1.0, height=1.0, segments=32, open_ends=False):
    radius = float(radius)
    height = float(height)
    segs = max(4, int(segments))
    verts, faces = [], []
    h2 = height / 2
    for si in range(segs):
        theta = 2 * math.pi * si / segs
        x = radius * math.cos(theta)
        z = radius * math.sin(theta)
        verts.append((x, -h2, z))   # bottom
        verts.append((x,  h2, z))   # top
    def b(s): return s * 2
    def t(s): return s * 2 + 1
    for si in range(segs):
        s0 = si
        s1 = (si + 1) % segs
        faces.append([b(s0), b(s1), t(s1)])
        faces.append([b(s0), t(s1), t(s0)])
    if not open_ends:
        cb = len(verts)
        verts.append((0.0, -h2, 0.0))
        for si in range(segs):
            s0 = si
            s1 = (si + 1) % segs
            faces.append([cb, b(s1), b(s0)])
        ct = len(verts)
        verts.append((0.0, h2, 0.0))
        for si in range(segs):
            s0 = si
            s1 = (si + 1) % segs
            faces.append([ct, t(s0), t(s1)])
    return new_mesh(verts, faces)


def cone(radius=1.0, height=1.0, segments=32, open_base=False):
    radius = float(radius)
    height = float(height)
    segs = max(4, int(segments))
    verts, faces = [], []
    for si in range(segs):
        theta = 2 * math.pi * si / segs
        x = radius * math.cos(theta)
        z = radius * math.sin(theta)
        verts.append((x, 0.0, z))
    apex_idx = len(verts)
    verts.append((0.0, height, 0.0))
    for si in range(segs):
        s0 = si
        s1 = (si + 1) % segs
        faces.append([s0, s1, apex_idx])
    if not open_base:
        base_center_idx = len(verts)
        verts.append((0.0, 0.0, 0.0))
        for si in range(segs):
            s0 = si
            s1 = (si + 1) % segs
            faces.append([base_center_idx, s0, s1])
    return new_mesh(verts, faces)


def torus(major_radius=1.0, minor_radius=0.3, major_segments=32, minor_segments=16):
    R = float(major_radius)
    r = float(minor_radius)
    ms = max(4, int(major_segments))
    ns = max(3, int(minor_segments))
    verts, faces = [], []
    for mi in range(ms):
        a = 2 * math.pi * mi / ms
        ca, sa = math.cos(a), math.sin(a)
        for ni in range(ns):
            b = 2 * math.pi * ni / ns
            cb, sb = math.cos(b), math.sin(b)
            x = (R + r * cb) * ca
            y = r * sb
            z = (R + r * cb) * sa
            verts.append((x, y, z))
    def vid(m, n):
        return m * ns + n
    for mi in range(ms):
        m0 = mi
        m1 = (mi + 1) % ms
        for ni in range(ns):
            n0 = ni
            n1 = (ni + 1) % ns
            faces.append([vid(m0, n0), vid(m0, n1), vid(m1, n1)])
            faces.append([vid(m0, n0), vid(m1, n1), vid(m1, n0)])
    return new_mesh(verts, faces)


def plane(size=(1.0, 1.0), segments=(1, 1)):
    sx, sy = float(size[0]), float(size[1])
    gsx, gsy = max(1, int(segments[0])), max(1, int(segments[1]))
    verts, faces = [], []
    hx, hy = sx / 2, sy / 2
    for iy in range(gsy + 1):
        y = -hy + sy * iy / gsy
        for ix in range(gsx + 1):
            x = -hx + sx * ix / gsx
            verts.append((x, y, 0.0))
    def vid(i, j):
        return i * (gsx + 1) + j
    for iy in range(gsy):
        for ix in range(gsx):
            v00 = vid(iy, ix)
            v01 = vid(iy, ix + 1)
            v10 = vid(iy + 1, ix)
            v11 = vid(iy + 1, ix + 1)
            faces.append([v00, v10, v01])
            faces.append([v01, v10, v11])
    return new_mesh(verts, faces)


# ── transforms ───────────────────────────────────────────────────────────────

def transform(mesh, matrix):
    """Apply a 4x4 matrix (translation + rotation + scale) to a mesh."""
    m = np.asarray(matrix, dtype=np.float32)
    v = mesh["verts"]
    ones = np.ones((len(v), 1), dtype=np.float32)
    hv = np.hstack([v, ones])
    out = (m @ hv.T).T[:, :3]
    return new_mesh(out, mesh["faces"])


def translate(mesh, dx, dy, dz):
    m = np.eye(4, dtype=np.float32)
    m[0, 3] = float(dx)
    m[1, 3] = float(dy)
    m[2, 3] = float(dz)
    return transform(mesh, m)


def rotate(mesh, ax, ay, az):
    """Rotate by angles in radians around X, Y, Z (applied in that order)."""
    ax, ay, az = float(ax), float(ay), float(az)
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=np.float32)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float32)
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=np.float32)
    r = rz @ ry @ rx
    m = np.eye(4, dtype=np.float32)
    m[:3, :3] = r
    return transform(mesh, m)


def scale(mesh, sx, sy, sz):
    m = np.eye(4, dtype=np.float32)
    m[0, 0] = float(sx)
    m[1, 1] = float(sy)
    m[2, 2] = float(sz)
    return transform(mesh, m)


# ── booleans (voxel-based, marching tetrahedra) ─────────────────────────────

def boolean(a, b, operation="union", resolution=64):
    """Voxel-based union / difference / intersection of two meshes.

    operation: "union" | "difference" (a - b) | "intersect".
    resolution: voxel grid size per axis (higher = more detail, slower).
    Returns a mesh.
    """
    op = operation.lower()
    if op not in ("union", "difference", "intersect"):
        raise ValueError("operation must be union, difference, or intersect")

    a_v, b_v = a["verts"], b["verts"]
    all_v = np.vstack([a_v, b_v])
    mn = all_v.min(axis=0)
    mx = all_v.max(axis=0)
    span = float((mx - mn).max())
    if span == 0:
        span = 1.0
    pad = span * 0.02
    mn = mn - pad
    mx = mx + pad

    # voxel grid
    xs = np.linspace(mn[0], mx[0], resolution)
    ys = np.linspace(mn[1], mx[1], resolution)
    zs = np.linspace(mn[2], mx[2], resolution)
    gx, gy, gz = np.meshgrid(xs, ys, zs, indexing="ij")
    pts = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1).astype(np.float32)

    def inside(mesh_verts, mesh_faces, p):
        # Ray casting along +x, count crossings per point (Möller–Trumbore).
        dir_ = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        inside_mask = np.zeros(len(p), dtype=bool)
        for tri in mesh_faces:
            t0 = mesh_verts[tri[0]]
            e1 = mesh_verts[tri[1]] - t0
            e2 = mesh_verts[tri[2]] - t0
            h = np.cross(dir_, e2)                    # (3,)
            a_det = float(np.dot(e1, h))
            if abs(a_det) < 1e-12:
                continue                              # ray parallel to triangle
            f_inv = 1.0 / a_det
            s = p - t0                                # (N,3)
            u = f_inv * (s @ h)                       # (N,)
            q = np.cross(s, e1)                       # (N,3)
            vv = f_inv * (q @ dir_)                   # (N,)
            t_hit = f_inv * (q @ e2)                  # (N,)
            hit = (u >= 0) & (vv >= 0) & (u + vv <= 1) & (t_hit > 1e-6)
            inside_mask ^= hit
        return inside_mask

    inside_a = inside(a_v, a["faces"], pts)
    inside_b = inside(b_v, b["faces"], pts)
    if op == "union":
        sel = inside_a | inside_b
    elif op == "difference":
        sel = inside_a & ~inside_b
    else:
        sel = inside_a & inside_b

    if not sel.any():
        return new_mesh(np.zeros((0, 3), dtype=np.float32),
                        np.zeros((0, 3), dtype=np.int32))

    sel_grid = sel.reshape(resolution, resolution, resolution)

    # Marching tetrahedra: split each cube into 6 tetrahedra, triangulate each.
    TETS = [
        (0, 1, 2, 5), (0, 2, 3, 5), (0, 5, 6, 7), (0, 4, 5, 6),
        (0, 1, 5, 6), (1, 2, 5, 6),
    ]
    verts, faces = [], []
    for ix in range(resolution - 1):
        for iy in range(resolution - 1):
            for iz in range(resolution - 1):
                cube = np.array([
                    sel_grid[ix, iy, iz],
                    sel_grid[ix + 1, iy, iz],
                    sel_grid[ix + 1, iy + 1, iz],
                    sel_grid[ix, iy + 1, iz],
                    sel_grid[ix, iy, iz + 1],
                    sel_grid[ix + 1, iy, iz + 1],
                    sel_grid[ix + 1, iy + 1, iz + 1],
                    sel_grid[ix, iy + 1, iz + 1],
                ], dtype=bool)
                if not cube.any() or cube.all():
                    continue
                cpos = np.array([
                    [xs[ix],     ys[iy],     zs[iz]],
                    [xs[ix + 1], ys[iy],     zs[iz]],
                    [xs[ix + 1], ys[iy + 1], zs[iz]],
                    [xs[ix],     ys[iy + 1], zs[iz]],
                    [xs[ix],     ys[iy],     zs[iz + 1]],
                    [xs[ix + 1], ys[iy],     zs[iz + 1]],
                    [xs[ix + 1], ys[iy + 1], zs[iz + 1]],
                    [xs[ix],     ys[iy + 1], zs[iz + 1]],
                ], dtype=np.float32)
                for tet in TETS:
                    tc = cube[list(tet)]
                    n_in = int(tc.sum())
                    if n_in == 0 or n_in == 4:
                        continue
                    tpos = cpos[list(tet)]
                    ep = {}
                    def ept(i, j):
                        key = (i, j) if i < j else (j, i)
                        if key not in ep:
                            ep[key] = (tpos[i] + tpos[j]) / 2
                        return ep[key]
                    if n_in == 1:
                        in_i = int(np.where(tc)[0][0])
                        outs = [j for j in range(4) if j != in_i]
                        pts3 = [ept(in_i, outs[0]), ept(in_i, outs[1]), ept(in_i, outs[2])]
                        verts.extend(pts3)
                        idx = len(verts) - 3
                        faces.append([idx, idx + 1, idx + 2])
                    elif n_in == 3:
                        out_i = int(np.where(~tc)[0][0])
                        ins = [j for j in range(4) if j != out_i]
                        pts3 = [ept(out_i, ins[0]), ept(out_i, ins[2]), ept(out_i, ins[1])]
                        verts.extend(pts3)
                        idx = len(verts) - 3
                        faces.append([idx, idx + 1, idx + 2])
                    else:
                        ins = [j for j in range(4) if tc[j]]
                        outs = [j for j in range(4) if not tc[j]]
                        p00 = ept(ins[0], outs[0])
                        p01 = ept(ins[0], outs[1])
                        p10 = ept(ins[1], outs[0])
                        p11 = ept(ins[1], outs[1])
                        verts.extend([p00, p01, p11, p10])
                        idx = len(verts) - 4
                        faces.append([idx, idx + 1, idx + 2])
                        faces.append([idx, idx + 2, idx + 3])

    if not verts:
        return new_mesh(np.zeros((0, 3), dtype=np.float32),
                        np.zeros((0, 3), dtype=np.int32))
    return new_mesh(np.array(verts, dtype=np.float32),
                    np.array(faces, dtype=np.int32))


# ── subdivide (Loop-style: split each triangle into 4) ───────────────────────

def subdivide(mesh, iterations=1):
    """Split each triangle into 4, new vertices at edge midpoints.
    iterations = how many times to repeat (each round 4x the faces)."""
    v = mesh["verts"].copy().tolist()
    f = [tuple(map(int, tri)) for tri in mesh["faces"]]
    for _ in range(max(0, int(iterations))):
        edge_mid = {}
        new_faces = []
        for (a, b, c) in f:
            mids = {}
            for (x, y) in ((a, b), (b, c), (c, a)):
                key = (x, y) if x < y else (y, x)
                if key not in edge_mid:
                    edge_mid[key] = len(v)
                    v.append(((v[x][0] + v[y][0]) / 2,
                              (v[x][1] + v[y][1]) / 2,
                              (v[x][2] + v[y][2]) / 2))
                mids[(x, y)] = edge_mid[key]
            ab = mids[(a, b)]
            bc = mids[(b, c)]
            ca = mids[(c, a)]
            new_faces.append((a, ab, ca))
            new_faces.append((ab, b, bc))
            new_faces.append((ca, bc, c))
            new_faces.append((ab, bc, ca))
        f = new_faces
    return new_mesh(v, f)


# ── mirror ───────────────────────────────────────────────────────────────────

def mirror(mesh, axis="x", merge=False):
    """Mirror across the plane perpendicular to `axis` (x/y/z)."""
    axis = axis.lower()
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    v = mesh["verts"].copy()
    v[:, idx] = -v[:, idx]
    f = mesh["faces"].copy()
    # flip winding so normals stay outward
    f = f[:, [0, 2, 1]]
    mirrored = new_mesh(v, f)
    if merge:
        return _cat([mesh, mirrored])
    return mirrored


# ── import / export OBJ ──────────────────────────────────────────────────────

def import_obj(path):
    """Import a Wavefront OBJ file into a mesh dict.

    Robust against malformed files: skips bad lines instead of crashing,
    handles negative OBJ indices (per spec), and never raises on valid
    or mostly-valid OBJ input.
    """
    from pathlib import Path as _Path

    p = _Path(path)
    if not p.exists():
        raise FileNotFoundError(f"OBJ file not found: {path}")

    verts, faces = [], []
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:
        raise IOError(f"Could not read OBJ file '{path}': {e}") from e

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            if parts[0] == "v":
                if len(parts) < 4:
                    continue  # malformed vertex line — skip
                verts.append(
                    (float(parts[1]), float(parts[2]), float(parts[3]))
                )
            elif parts[0] == "f":
                face = []
                for tok in parts[1:]:
                    # OBJ face token can be: v, v/vt, v//vn, v/vt/vn
                    idx_str = tok.split("/")[0]
                    if not idx_str:
                        continue
                    idx = int(idx_str)
                    # OBJ indices are 1-based; negative values count from the end
                    if idx < 0:
                        idx = len(verts) + idx   # -1 → last vertex, -3 → third-to-last
                    else:
                        idx = idx - 1            # 1 → first vertex
                    if 0 <= idx < len(verts):
                        face.append(idx)
                    # else: silently drop out-of-range references
                if len(face) == 3:
                    faces.append(face)
                elif len(face) > 3:
                    # fan triangulate
                    for i in range(1, len(face) - 1):
                        faces.append([face[0], face[i], face[i + 1]])
        except (ValueError, IndexError):
            # Skip any line we can't parse — never crash on a bad OBJ line
            continue

    if not verts:
        # Return an empty-but-valid mesh rather than crashing downstream
        return new_mesh([], [])
    return new_mesh(verts, faces)


def export_obj(mesh, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    lines = ["# JARVIS 3D Studio export"]
    for v in mesh["verts"]:
        lines.append(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")
    lines.append("")
    for f in mesh["faces"]:
        lines.append(f"f {f[0]+1} {f[1]+1} {f[2]+1}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ── scene ────────────────────────────────────────────────────────────────────

class Scene:
    """Named collection of meshes the user can build up across calls."""

    def __init__(self):
        self.objects: dict[str, dict] = {}

    def add(self, name, mesh):
        self.objects[name] = mesh

    def get(self, name):
        return self.objects.get(name)

    def list_names(self):
        return sorted(self.objects.keys())

    def remove(self, name):
        self.objects.pop(name, None)

    def clear(self):
        self.objects.clear()

    def info(self, name):
        m = self.objects.get(name)
        if m is None:
            return None
        verts = m["verts"]
        if len(verts) == 0:
            return {
                "name": name,
                "vertices": 0,
                "faces": 0,
                "bounds_min": [0.0, 0.0, 0.0],
                "bounds_max": [0.0, 0.0, 0.0],
            }
        return {
            "name": name,
            "vertices": int(len(verts)),
            "faces": int(len(m["faces"])),
            "bounds_min": verts.min(axis=0).tolist(),
            "bounds_max": verts.max(axis=0).tolist(),
        }
