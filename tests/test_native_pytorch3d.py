"""Compiled CPU kernels and differentiable rasterization, not just imports."""
import pytest
import torch


def test_native_kernels_and_render_gradients():
    pytest.importorskip('pytorch3d._C')
    from pytorch3d.ops import knn_points
    from pytorch3d.renderer.mesh.rasterize_meshes import rasterize_meshes
    from pytorch3d.structures import Meshes

    points = torch.tensor([[[0., 0., 0.], [1., 0., 0.]]], requires_grad=True)
    result = knn_points(points, points + 0.1)
    result.dists.sum().backward()
    assert torch.isfinite(points.grad).all()

    verts = torch.tensor([[-0.7, -0.7, 1.], [0.7, -0.7, 1.], [0., 0.7, 1.]], requires_grad=True)
    mesh = Meshes([verts], [torch.tensor([[0, 1, 2]])])
    pix, zbuf, bary, distances = rasterize_meshes(mesh, image_size=16, faces_per_pixel=1, bin_size=0)
    visible = pix >= 0
    assert visible.any()
    zbuf[visible].sum().backward()
    assert torch.isfinite(verts.grad).all()
    assert verts.grad.abs().sum() > 0