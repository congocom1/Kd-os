"""Regression tests for the explicitly limited tensor geometry backend."""
import pytest

torch = pytest.importorskip('torch')

from core import pytorch3d_compat as geometry


@pytest.fixture(params=['cpu', 'cuda'])
def device(request):
    if request.param == 'cuda' and not torch.cuda.is_available():
        pytest.skip('CUDA unavailable')
    return request.param


def triangle(device='cpu'):
    vertices = torch.tensor([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]], device=device)
    faces = torch.tensor([[0, 1, 2]], device=device)
    return vertices, faces


def test_batched_sampling_normals_and_gradients(device):
    torch.manual_seed(7)
    v, f = triangle(device)
    v.requires_grad_()
    mesh = geometry.Meshes([v, v + 2], [f, f])
    points, normals = geometry.sample_points_from_meshes(mesh, 50, True)
    assert points.shape == normals.shape == (2, 50, 3)
    assert torch.allclose(normals[..., 2], torch.ones_like(normals[..., 2]))
    assert torch.all(points[0, :, :2] >= 0)
    assert torch.all(points[0, :, :2].sum(-1) <= 1)
    assert torch.allclose(points[1, :, 2], torch.full_like(points[1, :, 2], 2))
    points.sum().backward()
    assert torch.isfinite(v.grad).all()


def test_tensor_batch_and_invalid_meshes():
    v, f = triangle()
    mesh = geometry.Meshes(torch.stack([v, v]), torch.stack([f, f]))
    assert len(mesh) == 2
    assert mesh.verts_packed.shape == (6, 3)
    with pytest.raises(ValueError):
        geometry.Meshes([v], [f, f])
    with pytest.raises(ValueError):
        geometry.sample_points_from_meshes(geometry.Meshes(v * 0, f), 10)


def test_axis_angle_batches_and_zero_gradient(device):
    angles = torch.zeros(2, 4, 3, dtype=torch.float64, device=device, requires_grad=True)
    matrices = geometry.axis_angle_to_matrix(angles)
    assert matrices.shape == (2, 4, 3, 3)
    assert torch.allclose(matrices, torch.eye(3, device=device, dtype=angles.dtype).expand_as(matrices))
    assert torch.autograd.gradcheck(geometry.axis_angle_to_matrix, (angles,))


def test_se3_coupling_roundtrip(device):
    tangent = torch.tensor([[1., 0., 0., 0., 0., torch.pi / 2],
                            [1., 2., 3., 0., 0., 0.]], dtype=torch.float64, device=device)
    matrix = geometry.se3_exp_map(tangent)
    expected = torch.tensor([2 / torch.pi, 2 / torch.pi, 0.], dtype=tangent.dtype, device=device)
    assert torch.allclose(matrix[0, :3, 3], expected)
    assert torch.allclose(geometry.se3_log_map(matrix), tangent, atol=1e-7)


def test_io_detaches_gradient_input(tmp_path):
    pytest.importorskip("trimesh")
    v, f = triangle()
    mesh = geometry.Meshes(v.requires_grad_(), f)
    path = tmp_path / 'triangle.obj'
    geometry.save_obj(mesh, path)
    restored = geometry.load_obj(path)
    assert restored.verts_packed.shape == (3, 3)
    assert restored.faces_packed.shape == (1, 3)


def test_camera_look_at_device(device):
    eye = torch.tensor([0., 0., 2.], device=device)
    R, T = geometry.look_at(eye, torch.zeros_like(eye))
    assert torch.allclose(R @ eye + T, torch.zeros_like(eye))


def test_explicit_backend_and_manager_integration():
    from core.geometry_backend import get_backend
    from core.visual_display_manager import VisualDisplayManager
    v, f = triangle()
    manager = VisualDisplayManager()
    points = manager.sample_model_surface({'verts': v, 'faces': f}, 12)
    assert points.shape == (1, 12, 3)
    with pytest.raises(ValueError):
        get_backend('automatic')