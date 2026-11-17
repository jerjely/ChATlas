"""ChAT reference frame: depth axis and ON/OFF surfaces from starburst amacrine cells, plus cell features."""
import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator
from scipy.spatial import ConvexHull, Delaunay, cKDTree


# ---------------------------------------------------------------------------------------------
# SAC selection
# ---------------------------------------------------------------------------------------------
def sac_table(labels, name):
    m = (labels["manual_type"].fillna("") == name) | (labels["manual_type"].isna() & (labels["auto_type"].fillna("") == name))
    return labels[m]


def nearest_sacs(labels, name, xy_vox, k_per_point, max_n):
    """Union of the k nearest SACs (by soma) to every query point, most frequent first."""
    s = sac_table(labels, name)
    if len(s) == 0:
        return s
    t = cKDTree(s[["x", "y"]].to_numpy(float))
    xy_vox = np.atleast_2d(np.asarray(xy_vox, float))
    k = min(k_per_point, len(s))
    _, idx = t.query(xy_vox, k=k)
    idx, cnt = np.unique(np.ravel(idx), return_counts=True)
    return s.iloc[idx[np.argsort(-cnt)][:max_n]]


def query_points_for_disc(center_vox, radius_um, vox_nm, spacing_um=120.0):
    """Grid of points covering a disc (plus a margin), for SAC selection; spacing ~ a SAC dendritic radius."""
    r_um = radius_um + 60
    n = max(3, int(np.ceil(2 * r_um / spacing_um)) + 1)
    g = np.linspace(-r_um, r_um, n) * 1000 / vox_nm[0]
    gx, gy = np.meshgrid(g, g)
    r_vox = r_um * 1000 / vox_nm[0]
    m = gx**2 + gy**2 <= r_vox**2 * 1.05
    return np.column_stack([gx[m] + center_vox[0], gy[m] + center_vox[1]])


# ---------------------------------------------------------------------------------------------
# surface fit
# ---------------------------------------------------------------------------------------------
def _column_peaks(u, v, w, grid, min_pts, res=0.25):
    df = pd.DataFrame({"iu": np.floor(u / grid).astype(int), "iv": np.floor(v / grid).astype(int), "u": u, "v": v, "w": w})
    out = []
    for _, g in df.groupby(["iu", "iv"]):
        if len(g) < min_pts:
            continue
        ww = g.w.to_numpy()
        h, e = np.histogram(ww, bins=np.arange(ww.min(), ww.max() + 2 * res, res))
        h = np.convolve(h, [1, 2, 3, 2, 1], mode="same")
        out.append((g.u.mean(), g.v.mean(), e[np.argmax(h)] + res / 2))
    return np.array(out).reshape(-1, 3)


def _poly_design(u, v, deg, c0, scale):
    u, v = (u - c0[0]) / scale, (v - c0[1]) / scale
    return np.column_stack([u**(d - k) * v**k for d in range(deg + 1) for k in range(d + 1)])


def _robust_poly(c, deg, k=3.0, n_iter=10):
    c0, scale = c[:, :2].mean(0), max(np.ptp(c[:, 0]), np.ptp(c[:, 1]), 1e-6) / 2
    keep = np.ones(len(c), bool)
    for _ in range(n_iter):
        coef, *_ = np.linalg.lstsq(_poly_design(c[keep, 0], c[keep, 1], deg, c0, scale), c[keep, 2], rcond=None)
        r = c[:, 2] - _poly_design(c[:, 0], c[:, 1], deg, c0, scale) @ coef
        mad = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep])))
        new = np.abs(r) < k * max(mad, 0.1)
        if (new == keep).all():
            break
        keep = new
    return (lambda uu, vv: _poly_design(np.asarray(uu, float), np.asarray(vv, float), deg, c0, scale) @ coef), keep


def _local_surface(c, sigma, step):
    tree = cKDTree(c[:, :2])
    gu = np.arange(c[:, 0].min() - step, c[:, 0].max() + 2 * step, step)
    gv = np.arange(c[:, 1].min() - step, c[:, 1].max() + 2 * step, step)
    W = np.full((len(gu), len(gv)), np.nan)
    for i, uu in enumerate(gu):
        for j, vv in enumerate(gv):
            idx = tree.query_ball_point([uu, vv], 3 * sigma)
            if len(idx) < 6:
                continue
            p = c[idx]
            wt = np.sqrt(np.exp(-((p[:, 0] - uu)**2 + (p[:, 1] - vv)**2) / (2 * sigma**2)))
            A = np.column_stack([np.ones(len(p)), p[:, 0] - uu, p[:, 1] - vv]) * wt[:, None]
            W[i, j] = np.linalg.lstsq(A, p[:, 2] * wt, rcond=None)[0][0]
    return gu, gv, W


def _fit_surface(P, s):
    u, v, w = P.T
    poly, _ = _robust_poly(_column_peaks(u, v, w, s.grid_um, s.min_pts_per_bin), s.poly_deg)
    near = np.abs(w - poly(u, v)) < s.band_half_um
    c2 = _column_peaks(u[near], v[near], w[near], s.grid_um, s.min_pts_per_bin)
    _, keep2 = _robust_poly(c2, s.poly_deg)
    c2 = c2[keep2]
    gu, gv, W = _local_surface(c2, s.smooth_um, s.grid_um)
    GU, GV = np.meshgrid(gu, gv, indexing="ij")
    W = np.where(np.isnan(W), poly(GU.ravel(), GV.ravel()).reshape(W.shape), W)
    interp = RegularGridInterpolator((gu, gv), W, bounds_error=False, fill_value=None)
    surf = lambda uu, vv: interp(np.column_stack([np.ravel(uu), np.ravel(vv)]))
    resid = c2[:, 2] - surf(c2[:, 0], c2[:, 1])
    return surf, c2, float(np.sqrt(np.mean(resid**2)))


class ChatFrame:
    """Retinal frame: u, v in the plane (≈ x, y, absolute µm), w = depth toward GCL; ON/OFF ChAT surfaces."""

    def __init__(self, on_pts_um, off_pts_um, s):
        allp = np.vstack([on_pts_um, off_pts_um])
        self.origin = allp.mean(axis=0)
        # principal axes from the 3x3 covariance (tiny eigenproblem instead of an SVD of millions of points)
        X = allp - self.origin
        cov = (X.T @ X) / len(X)
        evals, evecs = np.linalg.eigh(cov)                 # ascending
        sv = np.sqrt(np.maximum(evals[::-1], 0) * len(X))
        e3 = evecs[:, 0]
        if np.median((on_pts_um - self.origin) @ e3) < np.median((off_pts_um - self.origin) @ e3):
            e3 = -e3
        e1 = np.array([1.0, 0, 0]) - e3[0] * e3
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(e3, e1)
        if e2[1] < 0:
            e2 = -e2
        self.R = np.vstack([e1, e2, e3])
        self.offset = np.array([self.origin @ e1, self.origin @ e2, 0.0])
        self.singular_values = sv
        self.surf_on, self.cols_on, self.rms_on = _fit_surface(self.to_uvw(on_pts_um), s)
        self.surf_off, self.cols_off, self.rms_off = _fit_surface(self.to_uvw(off_pts_um), s)
        self._tri_on, self._tri_off = Delaunay(self.cols_on[:, :2]), Delaunay(self.cols_off[:, :2])

    def to_uvw(self, P):
        return (np.asarray(P, float) - self.origin) @ self.R.T + self.offset

    def from_uvw(self, Q):
        return (np.asarray(Q, float) - self.offset) @ self.R + self.origin

    def covered(self, u, v):
        q = np.column_stack([np.ravel(u), np.ravel(v)])
        return (self._tri_on.find_simplex(q) >= 0) & (self._tri_off.find_simplex(q) >= 0)

    def depth(self, P_uvw):
        u, v, w = np.asarray(P_uvw).T
        lo, hi = self.surf_off(u, v), self.surf_on(u, v)
        return (w - lo) / (hi - lo), self.covered(u, v)

    def surface_grid(self, umin, umax, vmin, vmax, n=120):
        gu, gv = np.meshgrid(np.linspace(umin, umax, n), np.linspace(vmin, vmax, n))
        mask = ~self.covered(gu.ravel(), gv.ravel()).reshape(gu.shape)
        out = {}
        for name, surf in (("OFF", self.surf_off), ("ON", self.surf_on)):
            gw = surf(gu.ravel(), gv.ravel()).reshape(gu.shape)
            gw[mask] = np.nan
            out[name] = (gu, gv, gw)
        return out

    def summary(self):
        return f"ChAT surfaces: OFF rms {self.rms_off:.2f} µm, ON rms {self.rms_on:.2f} µm, {len(self.cols_on)} / {len(self.cols_off)} columns"


# ---------------------------------------------------------------------------------------------
# features of one cell
# ---------------------------------------------------------------------------------------------
def profile_bins(s):
    edges = np.arange(s.ipl_range[0], s.ipl_range[1] + s.bin / 2, s.bin)
    centres = edges[:-1] + s.bin / 2
    return edges, centres, [f"p{c:+.2f}" for c in centres]


def features(P_uvw, frame, s):
    edges, centres, cols = profile_bins(s)
    d, cov = frame.depth(P_uvw)
    sel = (d >= s.ipl_range[0]) & (d <= s.ipl_range[1])
    f = {"n_ipl_pts": int(sel.sum()), "covered": float(cov[sel].mean()) if sel.any() else np.nan}
    h, _ = np.histogram(d[sel], bins=edges)
    prof = h / max(h.sum(), 1)
    f.update(dict(zip(cols, prof)))
    if sel.sum() >= 10:
        sm = np.convolve(prof, [1, 2, 1], mode="same")
        ip = int(np.argmax(sm))
        thr = s.terminal_frac * sm[ip]
        lo_i, hi_i = ip, ip
        while lo_i > 0 and sm[lo_i - 1] > thr:
            lo_i -= 1
        while hi_i < len(sm) - 1 and sm[hi_i + 1] > thr:
            hi_i += 1
        term = sel & (d >= edges[lo_i]) & (d <= edges[hi_i + 1])
        ds = d[term]
        f.update(peak=float(centres[ip]), median=float(np.median(ds)), q10=float(np.quantile(ds, 0.1)),
                 q90=float(np.quantile(ds, 0.9)), thickness=float(np.quantile(ds, 0.9) - np.quantile(ds, 0.1)))
        uv = np.asarray(P_uvw)[term][:, :2]
        try:
            hull = ConvexHull(uv)
            f.update(term_area_um2=float(hull.volume), term_diam_um=float(2 * np.sqrt(hull.volume / np.pi)),
                     term_u=float(uv[:, 0].mean()), term_v=float(uv[:, 1].mean()), hull=uv[hull.vertices])
        except Exception:
            pass
    return f


def qc_flags(df, s, max_diam_um="default", min_covered=None):
    """max_diam_um: None = no size limit (e.g. ganglion / amacrine cells); "default" = settings (bipolar terminals)."""
    q = pd.Series("ok", index=df.index)
    max_d = s.max_terminal_diam_um if max_diam_um == "default" else max_diam_um
    min_c = s.min_covered if min_covered is None else min_covered
    if "covered" in df:
        q[df.covered < min_c] = "outside SAC coverage"
    if "term_diam_um" in df and max_d:
        q[df.term_diam_um > max_d] = "too large (merge?)"
    if "n_ipl_pts" in df:
        q[df.n_ipl_pts < s.min_terminal_pts] = "no terminal (fragment?)"
    return q


def fit_frame_from_sacs(labels, query_xy_vox, meshes, s, log=None, progress=None, cancelled=lambda: False,
                        k_per_point=None, max_per_layer=None):
    """Pick SACs near the query points, download, sample and fit the ChAT frame."""
    k = k_per_point or s.sacs_per_point
    mx = max_per_layer or s.max_sacs_per_layer
    on = nearest_sacs(labels, "ON SAC", query_xy_vox, k, mx)
    off = nearest_sacs(labels, "OFF SAC", query_xy_vox, k, mx)
    if len(on) == 0 or len(off) == 0:
        raise RuntimeError("No labelled ON or OFF SACs found (check the label names 'ON SAC' / 'OFF SAC').")
    if log:
        log(f"SACs for the ChAT surfaces: ON {len(on)}, OFF {len(off)}")
    avail = meshes.ensure(list(on.root_id) + list(off.root_id), progress=progress, log=log, cancelled=cancelled)
    on_pts, off_pts = [], []
    n_all = len(avail)
    for k, r in enumerate(list(on.root_id) + list(off.root_id)):
        if cancelled():
            raise RuntimeError("cancelled")
        if r in avail:
            p = meshes.sample(r, s.samples_per_um2_sac, max_n=s.max_samples_sac, keep=False)
            (on_pts if k < len(on) else off_pts).append(p)
        if progress:
            progress(k + 1, len(on) + len(off), "sampling starburst meshes")
    on_pts, off_pts = np.vstack(on_pts), np.vstack(off_pts)
    if log:
        log(f"SAC surface points: ON {len(on_pts):,}, OFF {len(off_pts):,}")
    if progress:
        progress(0, 0, "fitting ChAT surfaces")
    frame = ChatFrame(on_pts, off_pts, s)
    if log:
        log(frame.summary())
    return frame
