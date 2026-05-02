from __future__ import annotations

import numpy as np
import open3d as o3d

from .config import AnalysisConfig


def prepare_o3d_topology_input(
    cloud_xyz_mm: np.ndarray,
    scan_index_plot: np.ndarray,
    cfg: AnalysisConfig,
) -> tuple[int, float, np.ndarray]:
    """
    Build Open3D-derived topology input and metrics.

    Returns
    -------
    n_points_o3d: int
    voxel_count_o3d: float
    topo_input: np.ndarray with columns [x_m, y_m, z_click]
    """
    if cloud_xyz_mm.size == 0:
        return 0, float("nan"), np.empty((0, 3), dtype=float)

    pts_m = cloud_xyz_mm.astype(np.float32) / 1000.0
    pc_o3d = o3d.geometry.PointCloud()
    pc_o3d.points = o3d.utility.Vector3dVector(pts_m)
    inlier_idx = np.arange(pts_m.shape[0], dtype=int)

    if cfg.use_o3d_sor and pts_m.shape[0] > 0:
        pc_o3d, inlier_idx = pc_o3d.remove_statistical_outlier(
            nb_neighbors=cfg.o3d_sor_nb_neighbors,
            std_ratio=cfg.o3d_sor_std_ratio,
        )

    inlier_idx = np.asarray(inlier_idx, dtype=int)
    n_points_o3d = int(inlier_idx.size)
    voxel_count_o3d = float("nan")

    pc_for_topo = pc_o3d
    if cfg.use_o3d_voxel and n_points_o3d > 0 and cfg.o3d_voxel_size_mm > 0:
        voxel_size_m = cfg.o3d_voxel_size_mm / 1000.0
        pc_for_topo = pc_o3d.voxel_down_sample(voxel_size_m)
        voxel_count_o3d = float(len(pc_for_topo.points))

    coords_topo_m = np.asarray(pc_for_topo.points)
    if coords_topo_m.size == 0:
        return n_points_o3d, voxel_count_o3d, np.empty((0, 3), dtype=float)

    if pc_for_topo is pc_o3d:
        idx_for_z = inlier_idx
    else:
        sor_coords = np.asarray(pc_o3d.points)
        if sor_coords.shape[0] == 0:
            idx_for_z = np.empty((0,), dtype=int)
        else:
            kdtree = o3d.geometry.KDTreeFlann(pc_o3d)
            idx_list = []
            for pt in coords_topo_m:
                _, idx, _ = kdtree.search_knn_vector_3d(pt, 1)
                idx_list.append(idx[0])
            idx_for_z = inlier_idx[np.asarray(idx_list, dtype=int)]

    z_clicks_filtered = scan_index_plot[idx_for_z]
    topo_input = np.column_stack([coords_topo_m[:, 0], coords_topo_m[:, 1], z_clicks_filtered])
    return n_points_o3d, voxel_count_o3d, topo_input
