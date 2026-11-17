"""Stratification search: cells passing through a small square whose arbor is wide and lies in a target ChAT layer."""
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull

from .chat import fit_frame_from_sacs, query_points_for_disc


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def wquantile(x, w, q):
    if len(x) == 0:
        return np.nan
    o = np.argsort(x)
    x, w = x[o], w[o]
    c = np.cumsum(w)
    return float(np.interp(q * c[-1], c, x))


def arbor_features(P_um, W, frame, s, band=None):
    """Field span and area-weighted ChAT stratification of a point cloud (µm) with weights (membrane area)."""
    uvw = frame.to_uvw(P_um)
    d, cov = frame.depth(uvw)
    ipl = (d >= s.ipl_range[0]) & (d <= s.ipl_range[1])
    f = {"n_points": len(P_um), "n_ipl": int(ipl.sum())}
    W = np.asarray(W, float)
    if ipl.sum() >= 3:
        uv = uvw[ipl, :2]
        try:
            hull = ConvexHull(uv)
            hv = uv[hull.vertices]
            dd = np.sqrt(((hv[:, None, :] - hv[None, :, :])**2).sum(-1))
            f.update(field_diam_um=float(2 * np.sqrt(hull.volume / np.pi)), field_span_um=float(dd.max()), hull=hv)
        except Exception:
            f.update(field_diam_um=0.0, field_span_um=float(np.ptp(uv, axis=0).max()))
    m = ipl & cov
    f["covered"] = float(W[m].sum() / max(W[ipl].sum(), 1e-9)) if ipl.any() else 0.0
    if m.sum() >= 3:
        dm, wm = d[m], W[m]
        f.update(median=wquantile(dm, wm, 0.5), q10=wquantile(dm, wm, 0.1), q90=wquantile(dm, wm, 0.9))
        edges = np.arange(s.ipl_range[0], s.ipl_range[1] + s.bin / 2, s.bin)
        h, _ = np.histogram(dm, bins=edges, weights=wm)
        sm = np.convolve(h, [1, 2, 1], mode="same")
        f["peak"] = float(edges[np.argmax(sm)] + s.bin / 2)
        f["profile"] = h / max(h.sum(), 1e-9)
        if band is not None:
            inb = (dm >= band[0]) & (dm <= band[1])
            f["frac_in_band"] = float(wm[inb].sum() / wm.sum())
    return f


def mesh_points(meshes, rid, s):
    """Fallback point cloud from a mesh: sampled points, equal weights."""
    p = meshes.sample(rid, s.samples_per_um2_cell, max_n=30_000, keep=False)
    return p, np.ones(len(p))


# ---------------------------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------------------------
class SearchResult:
    pass


def reference_band(labels, ref_type, center_vox, n_ref, frame, point_fn, s, log=print, cancelled=lambda: False):
    """Target ChAT layer from the nearest labelled cells of a reference type: [median q10, median q90]."""
    vox = np.asarray(s.voxel_nm, float)
    refs = labels[labels.label == ref_type].copy()
    if len(refs) == 0:
        refs = labels[labels.any_type == ref_type].copy()
    if len(refs) == 0:
        raise ValueError(f"No cells labelled '{ref_type}'.")
    refs["dist_um"] = np.hypot(refs.x - center_vox[0], refs.y - center_vox[1]) * vox[0] / 1000
    refs = refs.nsmallest(n_ref, "dist_um")
    rows = []
    for rid in refs.root_id:
        if cancelled():
            break
        try:
            P, W = point_fn(rid)
            f = arbor_features(P, W, frame, s)
            if "median" in f:
                rows.append(dict(root_id=rid, median=f["median"], q10=f["q10"], q90=f["q90"]))
        except Exception as e:
            log(f"reference {rid}: {e}")
    r = pd.DataFrame(rows)
    if len(r) == 0:
        raise ValueError("Could not measure any reference cell.")
    band = (float(r.q10.median()), float(r.q90.median()))
    log(f"target layer from {len(r)} '{ref_type}' cells (nearest {refs.dist_um.max():.0f} µm): "
        f"ChAT {band[0]:.2f}–{band[1]:.2f} (median {r['median'].median():.2f})")
    return band, r


def run_search(p, cave, meshes, s, log=print, progress=None, cancelled=lambda: False,
               labels=None, candidates=None, point_fn=None):
    """
    p: dict(center_vox, square_um, sac_radius_um, band_mode ('reference'|'manual'), ref_type, n_ref, band,
            depth_margin, whole_ipl, min_span_um, min_frac, min_points, classes, max_candidates)
    candidates / point_fn / labels can be injected (offline tests).
    """
    R = SearchResult()
    R.params = p
    vox = np.asarray(s.voxel_nm, float)
    if labels is None:
        if progress:
            progress(0, 0, "loading cell-type tables")
        labels = cave.labels()
    R.labels = labels
    cx, cy = p["center_vox"]

    # 1. ChAT frame around the square
    qp = query_points_for_disc((cx, cy), p["sac_radius_um"], s.voxel_nm, s.sac_spacing_um)
    frame = fit_frame_from_sacs(labels, qp, meshes, s, log=log, progress=progress, cancelled=cancelled,
                                k_per_point=1, max_per_layer=max(s.max_sacs_per_layer, len(qp)))
    R.frame = frame

    if point_fn is None:
        def point_fn(rid):
            try:
                return cave.l2_points(rid)
            except Exception:
                meshes.ensure([rid])
                return mesh_points(meshes, rid, s)

    # 2. target layer
    if p["band_mode"] == "reference":
        if progress:
            progress(0, 0, f"measuring reference '{p['ref_type']}' cells")
        band, R.ref_table = reference_band(labels, p["ref_type"], (cx, cy), p["n_ref"], frame, point_fn, s, log, cancelled)
    else:
        band, R.ref_table = tuple(p["band"]), None
        log(f"target layer (manual): ChAT {band[0]:.2f}–{band[1]:.2f}")
    R.band = band

    # 3. segments in the square
    c_um = np.array([cx, cy, 0]) * vox / 1000
    cu = frame.to_uvw(c_um[None, :])[0]
    half = p["square_um"] / 2
    R.square_uv = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]) * half + cu[:2]
    if candidates is None:
        g = np.arange(-half, half + 1e-6, 1.0)
        gu, gv = np.meshgrid(g + cu[0], g + cu[1])
        gu, gv = gu.ravel(), gv.ravel()
        lo, hi = (s.ipl_range if p["whole_ipl"] else (band[0] - p["depth_margin"], band[1] + p["depth_margin"]))
        levels = np.arange(lo, hi + 1e-6, 0.1)
        off, on = frame.surf_off(gu, gv), frame.surf_on(gu, gv)
        pts = np.vstack([np.column_stack([gu, gv, off + dl * (on - off)]) for dl in levels])
        log(f"sampling the segmentation: {len(gu)} positions × {len(levels)} depths ({lo:.2f}–{hi:.2f}) = {len(pts):,} points")
        if progress:
            progress(0, 0, "looking up segments in the square")
        xyz_nm = frame.from_uvw(pts) * 1000
        sv = cave.supervoxels_at_nm(xyz_nm, radius_vox=0)
        roots = cave.roots(sv)
        occ = pd.Series(roots[roots != 0]).value_counts().rename_axis("root_id").reset_index(name="square_hits")
        R.extracellular = float(np.mean(roots == 0))
    else:
        occ = pd.DataFrame({"root_id": list(candidates), "square_hits": 1})
        R.extracellular = np.nan
    occ = occ.merge(labels[["root_id", "cls", "label", "auto_type", "any_type"]], on="root_id", how="left")
    occ["cls"] = occ["cls"].fillna("not in tables")
    log(f"{len(occ)} segments pass through the square")
    keep = occ[occ.cls.isin(p["classes"])].copy()
    keep = keep.sort_values("square_hits", ascending=False).head(p["max_candidates"])
    log(f"{len(keep)} candidates after the class filter ({', '.join(p['classes'])})")

    # 4. measure candidates
    rows = []
    ids = list(keep.root_id)

    def measure(rid):
        P, W = point_fn(rid)
        return rid, arbor_features(P, W, frame, s, band)

    with ThreadPoolExecutor(max(1, int(s.threads))) as ex:
        futs = {ex.submit(measure, r): r for r in ids}
        for k, fu in enumerate(as_completed(futs), 1):
            if cancelled():
                ex.shutdown(cancel_futures=True)
                break
            try:
                rid, f = fu.result()
                rows.append({"root_id": rid, **f})
            except Exception as e:
                rows.append({"root_id": futs[fu], "error": str(e)[:80]})
            if progress:
                progress(k, len(ids), "measuring candidates")
    F = pd.DataFrame(rows)
    T = keep.merge(F, on="root_id", how="left")
    for c in ("field_span_um", "field_diam_um", "frac_in_band", "median", "peak", "q10", "q90", "covered", "n_points"):
        if c not in T:
            T[c] = np.nan
    T["is_wide"] = T.field_span_um >= p["min_span_um"]
    T["in_layer"] = T.frac_in_band >= p["min_frac"]
    T["big_enough"] = T.n_points >= p["min_points"]
    T["hit"] = T.is_wide & T.in_layer & T.big_enough
    T["score"] = T.frac_in_band.fillna(0) * np.log1p(T.field_span_um.fillna(0))
    T = T.sort_values(["hit", "score"], ascending=False).reset_index(drop=True)
    R.table = T
    log(f"hits: {int(T.hit.sum())} (wide ≥ {p['min_span_um']:.0f} µm: {int(T.is_wide.sum())}, "
        f"≥ {p['min_frac']:.0%} in layer: {int(T.in_layer.sum())})")
    return R
