"""Explicit geometry selection; never silently replace native PyTorch3D."""
from importlib import import_module


def get_backend(name: str = 'compat'):
    if name == 'compat':
        return import_module('core.pytorch3d_compat')
    if name != 'native':
        raise ValueError("Geometry backend must be 'compat' or 'native'")
    try:
        import_module('pytorch3d._C')
        return import_module('pytorch3d')
    except (ImportError, OSError) as exc:
        raise RuntimeError('Native PyTorch3D compiled extension is unavailable; '
                           'select compat explicitly or install a working native build') from exc


def sample_mesh(vertices, faces, num_samples=1000, backend='compat', device='cpu'):
    """Common sampling contract: return a (1, samples, 3) tensor."""
    selected = get_backend(backend)
    import torch
    vertices = torch.as_tensor(vertices, dtype=torch.float32, device=device)
    faces = torch.as_tensor(faces, dtype=torch.int64, device=device)
    if backend == 'native':
        from pytorch3d.structures import Meshes
        from pytorch3d.ops import sample_points_from_meshes
        return sample_points_from_meshes(Meshes([vertices], [faces]), num_samples)
    return selected.sample_points_from_meshes(selected.Meshes(vertices, faces), num_samples)