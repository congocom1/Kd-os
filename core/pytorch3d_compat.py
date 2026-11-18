"""
PyTorch3D Compatibility Layer
=============================

Provides PyTorch3D-like API using trimesh, open3d, and native PyTorch.
This allows the codebase to use 3D mesh operations without requiring
the actual PyTorch3D package. This is NOT a drop-in replacement.
Containers expose properties, quaternions use xyzw, and transforms act on
column vectors. CPU trimesh/Open3D operations detach gradients explicitly;
only native tensor operations preserve autograd. No differentiable renderer
is provided. Native installation must be verified separately.

Available operations:
- Mesh loading/saving (OBJ, PLY, STL, GLTF/GLB)
- Mesh transformations (rotate, translate, scale)
- Point cloud operations
- Mesh sampling
- Normal computation
- Mesh smoothing/simplification
- Ray-mesh intersection
- Distance queries
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any, Optional, Tuple, Union

import numpy as np
import torch

# Optional imports with graceful fallback
try:
    import trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False
    trimesh = None

try:
    import open3d as o3d
    OPEN3D_AVAILABLE = True
except ImportError:
    OPEN3D_AVAILABLE = False
    o3d = None

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Type aliases
# ─────────────────────────────────────────────────────────────────────────────

Device = Union[str, torch.device]
Tensor = torch.Tensor

# ─────────────────────────────────────────────────────────────────────────────
# Device utilities
# ─────────────────────────────────────────────────────────────────────────────

def get_device(device: Optional[Device] = None) -> torch.device:
    """Get torch device, defaulting to CUDA if available."""
    if device is None:
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device)


def to_device(x: Any, device: Device) -> Any:
    """Move tensor or dict of tensors to device."""
    if isinstance(x, torch.Tensor):
        return x.to(device)
    if isinstance(x, dict):
        return {k: to_device(v, device) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return type(x)(to_device(v, device) for v in x)
    return x


# ─────────────────────────────────────────────────────────────────────────────
# Mesh data structures (PyTorch3D-like)
# ─────────────────────────────────────────────────────────────────────────────

class Meshes:
    """
    PyTorch3D-like Meshes container.
    
    Stores a batch of meshes with vertices and faces.
    """
    
    def __init__(
        self,
        verts: Union[Tensor, list[Tensor]],
        faces: Union[Tensor, list[Tensor]],
        textures: Any = None,
    ):
        if isinstance(verts, torch.Tensor):
            verts = list(verts.unbind(0)) if verts.ndim == 3 else [verts]
        if isinstance(faces, torch.Tensor):
            faces = list(faces.unbind(0)) if faces.ndim == 3 else [faces]
        if not verts or len(verts) != len(faces):
            raise ValueError("Expected matching, nonempty vertex and face batches")
        for v, f in zip(verts, faces):
            if v.ndim != 2 or v.shape[-1] != 3 or f.ndim != 2 or f.shape[-1] != 3:
                raise ValueError("Vertices and faces must have shape (N, 3)")
            if not v.is_floating_point() or f.dtype != torch.int64:
                raise ValueError("Vertices must be floating point and faces int64")
            if f.numel() and (f.min() < 0 or f.max() >= len(v)):
                raise ValueError("Face indices outside vertex range")
        self.device = verts[0].device
        self._verts_list = [v.to(self.device) for v in verts]
        self._faces_list = [f.to(self.device) for f in faces]
        self._num_meshes = len(verts)

        self.textures = textures
    
    @property
    def verts_packed(self) -> Tensor:
        """All vertices concatenated into a single tensor."""
        return torch.cat(self._verts_list, dim=0)
    
    @property
    def faces_packed(self) -> Tensor:
        """All faces concatenated with vertex offsets applied."""
        offset = 0
        packed_faces = []
        for v, f in zip(self._verts_list, self._faces_list):
            packed_faces.append(f + offset)
            offset += v.shape[0]
        return torch.cat(packed_faces, dim=0)
    
    @property
    def verts_list(self) -> list[Tensor]:
        return self._verts_list
    
    @property
    def faces_list(self) -> list[Tensor]:
        return self._faces_list
    
    def __len__(self) -> int:
        return self._num_meshes
    
    def to(self, device: Device) -> "Meshes":
        return Meshes(
            [v.to(device) for v in self._verts_list],
            [f.to(device) for f in self._faces_list],
            self.textures,
        )
    
    def clone(self) -> "Meshes":
        return Meshes(
            [v.clone() for v in self._verts_list],
            [f.clone() for f in self._faces_list],
            self.textures,
        )


class Pointclouds:
    """PyTorch3D-like Pointclouds container."""
    
    def __init__(self, points: Union[Tensor, list[Tensor]]):
        self.device = get_device(points[0].device if isinstance(points, list) else points.device)
        
        if isinstance(points, list):
            self._points_list = [p.to(self.device) for p in points]
        else:
            self._points_list = [points.to(self.device)]
        self._num_clouds = len(self._points_list)
    
    @property
    def points_packed(self) -> Tensor:
        return torch.cat(self._points_list, dim=0)
    
    @property
    def points_list(self) -> list[Tensor]:
        return self._points_list
    
    def __len__(self) -> int:
        return self._num_clouds
    
    def to(self, device: Device) -> "Pointclouds":
        return Pointclouds([p.to(device) for p in self._points_list])


# ─────────────────────────────────────────────────────────────────────────────
# IO operations
# ─────────────────────────────────────────────────────────────────────────────

def load_obj(
    path: Union[str, Path],
    device: Optional[Device] = None,
    load_textures: bool = False,
) -> Meshes:
    """Load a mesh from OBJ file (and optionally MTL textures)."""
    if not TRIMESH_AVAILABLE:
        raise RuntimeError("trimesh required for load_obj. Install with: pip install trimesh")
    
    device = get_device(device)
    path = Path(path)
    
    scene = trimesh.load(str(path), force="mesh")
    
    if isinstance(scene, trimesh.Scene):
        # Combine all meshes in scene
        meshes = list(scene.geometry.values())
        if not meshes:
            raise ValueError("No meshes found in OBJ file")
        
        verts_list = []
        faces_list = []
        for mesh in meshes:
            verts_list.append(torch.tensor(mesh.vertices, dtype=torch.float32, device=device))
            faces_list.append(torch.tensor(mesh.faces, dtype=torch.int64, device=device))
        
        return Meshes(verts_list, faces_list)
    
    elif isinstance(scene, trimesh.Trimesh):
        verts = torch.tensor(scene.vertices, dtype=torch.float32, device=device)
        faces = torch.tensor(scene.faces, dtype=torch.int64, device=device)
        return Meshes(verts, faces)
    
    else:
        raise ValueError(f"Unexpected mesh type: {type(scene)}")


def load_ply(
    path: Union[str, Path],
    device: Optional[Device] = None,
) -> Union[Meshes, Pointclouds]:
    """Load mesh or point cloud from PLY file."""
    if not OPEN3D_AVAILABLE:
        raise RuntimeError("open3d required for load_ply. Install with: pip install open3d")
    
    device = get_device(device)
    path = Path(path)
    
    o3d_mesh = o3d.io.read_triangle_mesh(str(path))
    
    if o3d_mesh.has_triangles():
        verts = torch.tensor(np.asarray(o3d_mesh.vertices), dtype=torch.float32, device=device)
        faces = torch.tensor(np.asarray(o3d_mesh.triangles), dtype=torch.int64, device=device)
        return Meshes(verts, faces)
    else:
        # Point cloud
        pcd = o3d.io.read_point_cloud(str(path))
        points = torch.tensor(np.asarray(pcd.points), dtype=torch.float32, device=device)
        return Pointclouds(points)


def save_obj(
    meshes: Meshes,
    path: Union[str, Path],
    decimal_places: int = 6,
) -> None:
    """Save mesh(es) to OBJ file."""
    if not TRIMESH_AVAILABLE:
        raise RuntimeError("trimesh required for save_obj. Install with: pip install trimesh")
    
    path = Path(path)
    
    for i, (verts, faces) in enumerate(zip(meshes.verts_list, meshes.faces_list)):
        mesh = trimesh.Trimesh(
            vertices=verts.detach().cpu().numpy(),
            faces=faces.detach().cpu().numpy(),
        )
        out_path = path if i == 0 else path.with_stem(f"{path.stem}_{i}")
        mesh.export(str(out_path), file_type="obj")


def save_ply(
    meshes: Meshes,
    path: Union[str, Path],
    ascii: bool = False,
) -> None:
    """Save mesh to PLY file."""
    if not OPEN3D_AVAILABLE:
        raise RuntimeError("open3d required for save_ply. Install with: pip install open3d")
    
    path = Path(path)
    
    # For simplicity, save first mesh
    verts = meshes.verts_list[0].detach().cpu().numpy()
    faces = meshes.faces_list[0].detach().cpu().numpy()
    
    o3d_mesh = o3d.geometry.TriangleMesh()
    o3d_mesh.vertices = o3d.utility.Vector3dVector(verts)
    o3d_mesh.triangles = o3d.utility.Vector3iVector(faces)
    
    o3d.io.write_triangle_mesh(str(path), o3d_mesh, write_ascii=ascii)


# ─────────────────────────────────────────────────────────────────────────────
# Mesh operations
# ─────────────────────────────────────────────────────────────────────────────

def scale_verts(meshes: Meshes, scale: Union[float, Tensor]) -> Meshes:
    """Scale mesh vertices."""
    if isinstance(scale, (int, float)):
        scale = torch.tensor(scale, device=meshes.device, dtype=torch.float32)
    
    new_verts = [v * scale for v in meshes.verts_list]
    return Meshes(new_verts, meshes.faces_list, meshes.textures)


def translate_verts(meshes: Meshes, translation: Tensor) -> Meshes:
    """Translate mesh vertices."""
    translation = translation.to(meshes.device)
    new_verts = [v + translation for v in meshes.verts_list]
    return Meshes(new_verts, meshes.faces_list, meshes.textures)


def rotate_verts(
    meshes: Meshes,
    R: Tensor,  # (3, 3) rotation matrix
) -> Meshes:
    """Rotate mesh vertices."""
    R = R.to(meshes.device)
    new_verts = [v @ R.T for v in meshes.verts_list]
    return Meshes(new_verts, meshes.faces_list, meshes.textures)


def compute_vertex_normals(meshes: Meshes) -> Tensor:
    """Compute per-vertex normals."""
    if not TRIMESH_AVAILABLE:
        raise RuntimeError("trimesh required for compute_vertex_normals")
    
    # Use trimesh for robust normal computation
    normals_list = []
    for verts, faces in zip(meshes.verts_list, meshes.faces_list):
        mesh = trimesh.Trimesh(
            vertices=verts.detach().cpu().numpy(),
            faces=faces.detach().cpu().numpy(),
            process=False,
        )
        normals = torch.tensor(mesh.vertex_normals, dtype=torch.float32, device=meshes.device)
        normals_list.append(normals)
    
    return torch.cat(normals_list, dim=0)


def compute_face_normals(meshes: Meshes) -> Tensor:
    """Compute per-face normals."""
    normals_list = []
    for verts, faces in zip(meshes.verts_list, meshes.faces_list):
        v0 = verts[faces[:, 0]]
        v1 = verts[faces[:, 1]]
        v2 = verts[faces[:, 2]]
        
        edge1 = v1 - v0
        edge2 = v2 - v0
        face_normals = torch.cross(edge1, edge2, dim=1)
        face_normals = torch.nn.functional.normalize(face_normals, dim=1)
        normals_list.append(face_normals)
    
    return torch.cat(normals_list, dim=0)


def sample_points_from_meshes(
    meshes: Meshes,
    num_samples: int = 10000,
    return_normals: bool = False,
) -> Union[Tensor, Tuple[Tensor, Tensor]]:
    """Area-weighted samples of shape (batch, samples, 3), with autograd.

    Face selection is discrete; gradients flow through sampled vertices.
    Empty or entirely degenerate surfaces are rejected explicitly.
    """
    if num_samples <= 0:
        raise ValueError("num_samples must be positive")
    samples, normals = [], []
    for verts, faces in zip(meshes.verts_list, meshes.faces_list):
        triangles = verts[faces]
        cross = torch.cross(triangles[:, 1] - triangles[:, 0],
                            triangles[:, 2] - triangles[:, 0], dim=-1)
        areas = torch.linalg.vector_norm(cross, dim=-1)
        if not torch.isfinite(areas).all() or areas.sum() <= 0:
            raise ValueError("Cannot sample an empty, nonfinite or degenerate mesh")
        indices = torch.multinomial(areas.detach(), num_samples, replacement=True)
        uv = torch.rand(num_samples, 2, device=verts.device, dtype=verts.dtype)
        root = uv[:, 0].sqrt()
        weights = torch.stack((1 - root, root * (1 - uv[:, 1]), root * uv[:, 1]), -1)
        samples.append((triangles[indices] * weights[..., None]).sum(1))
        normals.append(torch.nn.functional.normalize(cross, dim=-1)[indices])
    points = torch.stack(samples)
    return (points, torch.stack(normals)) if return_normals else points


def subdivide_meshes(meshes: Meshes, num_subdivisions: int = 1) -> Meshes:
    """Subdivide mesh using Loop subdivision."""
    if not OPEN3D_AVAILABLE:
        raise RuntimeError("open3d required for subdivide_meshes")
    
    new_verts_list = []
    new_faces_list = []
    
    for verts, faces in zip(meshes.verts_list, meshes.faces_list):
        o3d_mesh = o3d.geometry.TriangleMesh()
        o3d_mesh.vertices = o3d.utility.Vector3dVector(verts.detach().cpu().numpy())
        o3d_mesh.triangles = o3d.utility.Vector3iVector(faces.detach().cpu().numpy())
        
        for _ in range(num_subdivisions):
            o3d_mesh = o3d_mesh.subdivide_loop()
        
        new_verts_list.append(torch.tensor(
            np.asarray(o3d_mesh.vertices), dtype=torch.float32, device=meshes.device
        ))
        new_faces_list.append(torch.tensor(
            np.asarray(o3d_mesh.triangles), dtype=torch.int64, device=meshes.device
        ))
    
    return Meshes(new_verts_list, new_faces_list, meshes.textures)


def simplify_meshes(meshes: Meshes, target_faces: int) -> Meshes:
    """Simplify mesh to target number of faces using quadric decimation."""
    if not OPEN3D_AVAILABLE:
        raise RuntimeError("open3d required for simplify_meshes")
    
    new_verts_list = []
    new_faces_list = []
    
    for verts, faces in zip(meshes.verts_list, meshes.faces_list):
        o3d_mesh = o3d.geometry.TriangleMesh()
        o3d_mesh.vertices = o3d.utility.Vector3dVector(verts.detach().cpu().numpy())
        o3d_mesh.triangles = o3d.utility.Vector3iVector(faces.detach().cpu().numpy())
        
        o3d_mesh = o3d_mesh.simplify_quadric_decimation(target_faces)
        
        new_verts_list.append(torch.tensor(
            np.asarray(o3d_mesh.vertices), dtype=torch.float32, device=meshes.device
        ))
        new_faces_list.append(torch.tensor(
            np.asarray(o3d_mesh.triangles), dtype=torch.int64, device=meshes.device
        ))
    
    return Meshes(new_verts_list, new_faces_list, meshes.textures)


def smooth_meshes(meshes: Meshes, lambda_: float = 0.5, iterations: int = 10) -> Meshes:
    """Laplacian mesh smoothing."""
    if not OPEN3D_AVAILABLE:
        raise RuntimeError("open3d required for smooth_meshes")
    
    new_verts_list = []
    new_faces_list = []
    
    for verts, faces in zip(meshes.verts_list, meshes.faces_list):
        o3d_mesh = o3d.geometry.TriangleMesh()
        o3d_mesh.vertices = o3d.utility.Vector3dVector(verts.detach().cpu().numpy())
        o3d_mesh.triangles = o3d.utility.Vector3iVector(faces.detach().cpu().numpy())
        
        o3d_mesh = o3d_mesh.filter_smooth_laplacian(number_of_iterations=iterations, lambda_=lambda_)
        
        new_verts_list.append(torch.tensor(
            np.asarray(o3d_mesh.vertices), dtype=torch.float32, device=meshes.device
        ))
        new_faces_list.append(torch.tensor(
            np.asarray(o3d_mesh.triangles), dtype=torch.int64, device=meshes.device
        ))
    
    return Meshes(new_verts_list, new_faces_list, meshes.textures)


# ─────────────────────────────────────────────────────────────────────────────
# Point cloud operations
# ─────────────────────────────────────────────────────────────────────────────

def estimate_pointcloud_normals(
    pointclouds: Pointclouds,
    neighborhood_size: int = 30,
) -> Tensor:
    """Estimate normals for point cloud using Open3D."""
    if not OPEN3D_AVAILABLE:
        raise RuntimeError("open3d required for estimate_pointcloud_normals")
    
    all_normals = []
    for points in pointclouds.points_list:
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(points.detach().cpu().numpy())
        pcd.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamKNN(neighborhood_size)
        )
        normals = torch.tensor(
            np.asarray(pcd.normals), dtype=torch.float32, device=pointclouds.device
        )
        all_normals.append(normals)
    
    return torch.cat(all_normals, dim=0)


def pointcloud_to_mesh(
    pointclouds: Pointclouds,
    method: str = "poisson",
    depth: int = 8,
) -> Meshes:
    """Reconstruct mesh from point cloud using Poisson or Ball Pivoting."""
    if not OPEN3D_AVAILABLE:
        raise RuntimeError("open3d required for pointcloud_to_mesh")
    
    all_verts = []
    all_faces = []
    
    for points in pointclouds.points_list:
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(points.detach().cpu().numpy())
        pcd.estimate_normals()
        
        if method == "poisson":
            mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
                pcd, depth=depth
            )
        elif method == "ball_pivoting":
            radii = [0.01, 0.02, 0.04, 0.08]
            mesh = o3d.geometry.TriangleMesh.create_from_point_cloud_ball_pivoting(
                pcd, o3d.utility.DoubleVector(radii)
            )
        else:
            raise ValueError(f"Unknown method: {method}")
        
        all_verts.append(torch.tensor(
            np.asarray(mesh.vertices), dtype=torch.float32, device=pointclouds.device
        ))
        all_faces.append(torch.tensor(
            np.asarray(mesh.triangles), dtype=torch.int64, device=pointclouds.device
        ))
    
    return Meshes(all_verts, all_faces)


# ─────────────────────────────────────────────────────────────────────────────
# Ray-mesh intersection (basic)
# ─────────────────────────────────────────────────────────────────────────────

def ray_mesh_intersection(
    meshes: Meshes,
    ray_origins: Tensor,  # (N, 3)
    ray_directions: Tensor,  # (N, 3)
) -> Tuple[Tensor, Tensor, Tensor]:
    """
    Compute ray-mesh intersections.
    
    Returns:
        hit: (N,) bool tensor indicating hit
        distances: (N,) float tensor of hit distances
        face_indices: (N,) int tensor of hit face indices (-1 for miss)
    """
    if not TRIMESH_AVAILABLE:
        raise RuntimeError("trimesh required for ray_mesh_intersection")
    
    # Use first mesh for intersection (batch not fully supported)
    verts = meshes.verts_list[0].detach().cpu().numpy()
    faces = meshes.faces_list[0].detach().cpu().numpy()
    
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    
    ray_origins_np = ray_origins.detach().cpu().numpy()
    ray_directions_np = ray_directions.detach().cpu().numpy()
    
    locations, index_ray, index_tri = mesh.ray.intersects_location(
        ray_origins_np, ray_directions_np, multiple_hits=False
    )
    
    hit = torch.zeros(ray_origins.shape[0], dtype=torch.bool, device=meshes.device)
    distances = torch.full((ray_origins.shape[0],), float('inf'), device=meshes.device)
    face_indices = torch.full((ray_origins.shape[0],), -1, dtype=torch.int64, device=meshes.device)
    
    if len(locations) > 0:
        hit[index_ray] = True
        dists = np.linalg.norm(locations - ray_origins_np[index_ray], axis=1)
        distances[index_ray] = torch.tensor(dists, device=meshes.device)
        face_indices[index_ray] = torch.tensor(index_tri, device=meshes.device)
    
    return hit, distances, face_indices


# ─────────────────────────────────────────────────────────────────────────────
# Distance queries
# ─────────────────────────────────────────────────────────────────────────────

def point_to_mesh_distance(
    points: Tensor,  # (N, 3)
    meshes: Meshes,
) -> Tuple[Tensor, Tensor]:
    """
    Compute signed distance from points to mesh surface.
    
    Returns:
        distances: (N,) signed distances (negative inside)
        closest_points: (N, 3) closest point on mesh
    """
    if not TRIMESH_AVAILABLE:
        raise RuntimeError("trimesh required for point_to_mesh_distance")
    
    # Use first mesh
    verts = meshes.verts_list[0].detach().cpu().numpy()
    faces = meshes.faces_list[0].detach().cpu().numpy()
    
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    points_np = points.detach().cpu().numpy()
    
    # Query closest point and distance
    closest_points, distances, triangle_ids = trimesh.proximity.closest_point(mesh, points_np)
    
    # Determine inside/outside using ray casting
    inside = mesh.contains(points_np)
    signed_distances = np.where(inside, -distances, distances)
    
    return (
        torch.tensor(signed_distances, dtype=torch.float32, device=points.device),
        torch.tensor(closest_points, dtype=torch.float32, device=points.device),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Transform utilities
# ─────────────────────────────────────────────────────────────────────────────

def euler_angles_to_matrix(euler_angles: Tensor, convention: str = "XYZ") -> Tensor:
    """Convert Euler angles to rotation matrix."""
    # euler_angles: (..., 3) in radians
    x, y, z = euler_angles.unbind(-1)
    
    if convention == "XYZ":
        Rx = torch.stack([
            torch.ones_like(x), torch.zeros_like(x), torch.zeros_like(x),
            torch.zeros_like(x), torch.cos(x), -torch.sin(x),
            torch.zeros_like(x), torch.sin(x), torch.cos(x),
        ], dim=-1).reshape(*x.shape, 3, 3)
        
        Ry = torch.stack([
            torch.cos(y), torch.zeros_like(y), torch.sin(y),
            torch.zeros_like(y), torch.ones_like(y), torch.zeros_like(y),
            -torch.sin(y), torch.zeros_like(y), torch.cos(y),
        ], dim=-1).reshape(*y.shape, 3, 3)
        
        Rz = torch.stack([
            torch.cos(z), -torch.sin(z), torch.zeros_like(z),
            torch.sin(z), torch.cos(z), torch.zeros_like(z),
            torch.zeros_like(z), torch.zeros_like(z), torch.ones_like(z),
        ], dim=-1).reshape(*z.shape, 3, 3)
        
        return Rz @ Ry @ Rx
    
    raise NotImplementedError(f"Convention {convention} not implemented")


def quaternion_to_matrix(q: Tensor) -> Tensor:
    """Convert quaternion (x, y, z, w) to rotation matrix."""
    x, y, z, w = q.unbind(-1)
    return torch.stack([
        1 - 2*y*y - 2*z*z, 2*x*y - 2*z*w, 2*x*z + 2*y*w,
        2*x*y + 2*z*w, 1 - 2*x*x - 2*z*z, 2*y*z - 2*x*w,
        2*x*z - 2*y*w, 2*y*z + 2*x*w, 1 - 2*x*x - 2*y*y,
    ], dim=-1).reshape(*q.shape[:-1], 3, 3)


def _skew(vector: Tensor) -> Tensor:
    x, y, z = vector.unbind(-1)
    zero = torch.zeros_like(x)
    return torch.stack((zero, -z, y, z, zero, -x, -y, x, zero), -1).reshape(*vector.shape[:-1], 3, 3)


def axis_angle_to_matrix(axis_angle: Tensor) -> Tensor:
    """Batched Rodrigues map, including differentiable zero rotations."""
    return torch.matrix_exp(_skew(axis_angle))


def se3_exp_map(log_transform: Tensor) -> Tensor:
    """True SE(3) exponential, column-vector convention (not PyTorch3D's).

    Input (..., 6) contains translation tangent then rotation tangent.
    """
    algebra = log_transform.new_zeros(*log_transform.shape[:-1], 4, 4)
    algebra[..., :3, :3] = _skew(log_transform[..., 3:])
    algebra[..., :3, 3] = log_transform[..., :3]
    return torch.matrix_exp(algebra)


def se3_log_map(T: Tensor) -> Tensor:
    """Principal SE(3) logarithm; rotations at pi are explicitly unsupported."""
    R = T[..., :3, :3]
    skew = R - R.transpose(-2, -1)
    vee = torch.stack((skew[..., 2, 1], skew[..., 0, 2], skew[..., 1, 0]), -1) / 2
    sine = torch.linalg.vector_norm(vee, dim=-1)
    cosine = ((R.diagonal(dim1=-2, dim2=-1).sum(-1) - 1) / 2).clamp(-1, 1)
    theta = torch.atan2(sine, cosine)
    if torch.any(theta > torch.pi - 1e-5):
        raise ValueError("SE(3) logarithm is ambiguous at pi")
    scale = torch.where(sine > 1e-7, theta / sine.clamp_min(1e-7), 1 + theta.square() / 6)
    rotation = vee * scale[..., None]
    # Recover the left Jacobian without unstable small-angle divisions.
    K = _skew(rotation)
    block = T.new_zeros(*T.shape[:-2], 6, 6)
    block[..., :3, :3] = K
    block[..., :3, 3:] = torch.eye(3, device=T.device, dtype=T.dtype)
    jacobian = torch.matrix_exp(block)[..., :3, 3:]
    translation = torch.linalg.solve(jacobian, T[..., :3, 3, None]).squeeze(-1)
    return torch.cat((translation, rotation), -1)


# ─────────────────────────────────────────────────────────────────────────────
# Camera utilities
# ─────────────────────────────────────────────────────────────────────────────

class PerspectiveCameras:
    """PyTorch3D-like perspective cameras."""
    
    def __init__(
        self,
        focal_length: Union[float, Tensor] = 1.0,
        principal_point: Optional[Tensor] = None,
        R: Optional[Tensor] = None,
        T: Optional[Tensor] = None,
        device: Optional[Device] = None,
        image_size: Optional[Tuple[int, int]] = None,
    ):
        self.device = get_device(device)
        
        self.focal_length = torch.tensor(focal_length, device=self.device, dtype=torch.float32)
        if isinstance(focal_length, (int, float)):
            self.focal_length = self.focal_length.expand(1)
        
        self.principal_point = principal_point
        if principal_point is not None:
            self.principal_point = principal_point.to(self.device)
        
        self.R = R
        if R is not None:
            self.R = R.to(self.device)
        else:
            self.R = torch.eye(3, device=self.device).unsqueeze(0)
        
        self.T = T
        if T is not None:
            self.T = T.to(self.device)
        else:
            self.T = torch.zeros(1, 3, device=self.device)
        
        self.image_size = image_size
    
    def get_world_to_view_transform(self) -> Tensor:
        """Get 4x4 world-to-view transform matrix."""
        R = self.R if self.R.dim() == 3 else self.R.unsqueeze(0)
        T = self.T if self.T.dim() == 2 else self.T.unsqueeze(0)
        
        RT = torch.eye(4, device=self.device, dtype=R.dtype).expand(R.shape[0], 4, 4).clone()
        RT[:, :3, :3] = R
        RT[:, :3, 3] = T
        return RT
    
    def get_projection_transform(self) -> Tensor:
        """Get 4x4 projection matrix."""
        # Simple perspective projection
        f = self.focal_length
        if self.principal_point is not None:
            cx, cy = self.principal_point.unbind(-1)
        else:
            cx = cy = 0
        
        if self.image_size is not None:
            w, h = self.image_size
        else:
            w = h = 1
        
        P = torch.zeros(f.shape[0], 4, 4, device=self.device, dtype=f.dtype)
        P[:, 0, 0] = f * 2 / w
        P[:, 1, 1] = f * 2 / h
        P[:, 0, 2] = 2 * cx / w - 1
        P[:, 1, 2] = 2 * cy / h - 1
        P[:, 2, 2] = -1
        P[:, 2, 3] = -1
        P[:, 3, 2] = 1
        return P
    
    def transform_points(self, points: Tensor) -> Tensor:
        """Transform points from world to camera space."""
        RT = self.get_world_to_view_transform()
        points_h = torch.cat([points, torch.ones_like(points[..., :1])], dim=-1)
        return (points_h @ RT.transpose(-2, -1))[..., :3]
    
    def to(self, device: Device) -> "PerspectiveCameras":
        return PerspectiveCameras(
            focal_length=self.focal_length,
            principal_point=self.principal_point,
            R=self.R,
            T=self.T,
            device=device,
            image_size=self.image_size,
        )


def look_at(
    eye: Tensor,  # (3,) or (N, 3)
    at: Tensor,   # (3,) or (N, 3)
    up: Tensor = torch.tensor([0.0, 1.0, 0.0]),
) -> Tuple[Tensor, Tensor]:
    """Compute camera R, T from look-at parameters."""
    eye = eye.to(torch.float32)
    at = at.to(torch.float32)
    up = up.to(device=eye.device, dtype=torch.float32).expand_as(eye)
    
    if eye.dim() == 1:
        eye = eye.unsqueeze(0)
        at = at.unsqueeze(0)
        up = up.unsqueeze(0)
        squeeze = True
    else:
        squeeze = False
    
    z = torch.nn.functional.normalize(at - eye, dim=-1)
    x = torch.nn.functional.normalize(torch.cross(up, z, dim=-1), dim=-1)
    y = torch.cross(z, x, dim=-1)
    
    R = torch.stack([x, y, z], dim=-2)  # (N, 3, 3)
    T = -R @ eye.unsqueeze(-1)
    
    if squeeze:
        R = R.squeeze(0)
        T = T.squeeze(0)
    
    return R, T.squeeze(-1)


# ─────────────────────────────────────────────────────────────────────────────
# Availability checks
# ─────────────────────────────────────────────────────────────────────────────

def check_dependencies() -> dict:
    """Check which optional dependencies are available."""
    return {
        "trimesh": TRIMESH_AVAILABLE,
        "open3d": OPEN3D_AVAILABLE,
        "torch": True,
        "numpy": True,
    }


def warn_missing_deps(required: list[str]) -> None:
    """Warn about missing optional dependencies."""
    deps = check_dependencies()
    missing = [d for d in required if not deps.get(d, False)]
    if missing:
        warnings.warn(
            f"Missing optional dependencies: {missing}. "
            f"Some functionality will be unavailable. "
            f"Install with: pip install {' '.join(missing)}",
            UserWarning,
            stacklevel=2,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Re-export for compatibility
# ─────────────────────────────────────────────────────────────────────────────

__all__ = [
    # Mesh/Pointcloud containers
    "Meshes",
    "Pointclouds",
    # IO
    "load_obj",
    "load_ply",
    "save_obj",
    "save_ply",
    # Mesh ops
    "scale_verts",
    "translate_verts",
    "rotate_verts",
    "compute_vertex_normals",
    "compute_face_normals",
    "sample_points_from_meshes",
    "subdivide_meshes",
    "simplify_meshes",
    "smooth_meshes",
    # Point cloud ops
    "estimate_pointcloud_normals",
    "pointcloud_to_mesh",
    # Queries
    "ray_mesh_intersection",
    "point_to_mesh_distance",
    # Transforms
    "euler_angles_to_matrix",
    "quaternion_to_matrix",
    "axis_angle_to_matrix",
    "se3_exp_map",
    "se3_log_map",
    # Cameras
    "PerspectiveCameras",
    "look_at",
    # Utils
    "get_device",
    "to_device",
    "check_dependencies",
    "warn_missing_deps",
]