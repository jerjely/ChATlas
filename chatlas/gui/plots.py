"""Matplotlib figures used by the dialogs."""
import numpy as np
import matplotlib
matplotlib.use("QtAgg")
from matplotlib.figure import Figure
from matplotlib.patches import Polygon


def _c(col):
    return col


def depth_figure(R, colors, types, s, edges_centres):
    edges, centres = edges_centres
    fig = Figure(figsize=(13, 6), layout="constrained")
    ax1, ax2 = fig.add_subplot(1, 2, 1), fig.add_subplot(1, 2, 2)
    tf = R.target_features
    if tf:
        prof = np.array([tf[k] for k in tf if k.startswith("p") and k[1] in "+-"])
        ax1.fill_betweenx(centres, 0, prof / s.bin, color="#00c864", alpha=0.4, step="mid", label="target cell membrane")
    a = R.ann[(R.ann.partner != 0) & R.ann.syn_covered]
    h, _ = np.histogram(a.syn_depth, bins=edges)
    ax1.plot(h / max(h.sum(), 1) / s.bin, centres, color="k", lw=2, drawstyle="steps-mid", label=f"annotations (n={len(a)})")
    for y in (0, 1):
        ax1.axhline(y, color="k", ls="--", lw=0.8)
    ax1.set_ylim(s.ipl_range[1], s.ipl_range[0])
    ax1.set_xlabel("density"); ax1.set_ylabel("ChAT depth (0 = OFF band, 1 = ON band)")
    ax1.set_title("Target stratification and annotation depth"); ax1.legend()
    rng = np.random.default_rng(0)
    for i, t in enumerate(types):
        d = a[a.best_type == t].syn_depth
        ax2.scatter(rng.normal(i, 0.08, len(d)), d, s=12, color=colors.get(t, "grey"))
    ax2.set_xticks(range(len(types))); ax2.set_xticklabels(types, rotation=60, ha="right", fontsize=8)
    for y in (0, 1):
        ax2.axhline(y, color="k", ls="--", lw=0.8)
    ax2.invert_yaxis(); ax2.set_ylabel("annotation ChAT depth"); ax2.set_title("Annotation depth by partner type")
    return fig


def distance_figure(A, colors, types, min_n=3, col="dist3d_um", label="3D distance from origin (µm)"):
    a = A[(A.partner != 0) & A.best_type.isin(types)].dropna(subset=[col])
    order = [t for t in a.groupby("best_type")[col].median().sort_values().index if (a.best_type == t).sum() >= min_n]
    fig = Figure(figsize=(16, 11), layout="constrained")
    rng = np.random.default_rng(0)
    ax = fig.add_subplot(2, 2, 1)
    for i, t in enumerate(order):
        d = a[a.best_type == t][col]
        ax.boxplot(d, positions=[i], widths=0.6, showfliers=False, medianprops=dict(color="k"))
        ax.scatter(rng.normal(i, 0.08, len(d)), d, s=12, color=colors.get(t, "grey"), zorder=3)
    ax.set_xticks(range(len(order))); ax.set_xticklabels([f"{t}\n(n={(a.best_type == t).sum()})" for t in order], rotation=60, ha="right", fontsize=8)
    ax.set_ylabel(label); ax.set_title("Distance per partner type")
    ax = fig.add_subplot(2, 2, 2)
    for t in order:
        d = np.sort(a[a.best_type == t][col])
        ax.step(d, np.arange(1, len(d) + 1) / len(d), where="post", color=colors.get(t, "grey"), label=t)
    ax.set_xlabel(label); ax.set_ylabel("cumulative fraction"); ax.legend(fontsize=7, ncol=2)
    ax.set_title("Cumulative distributions")
    ax = fig.add_subplot(2, 2, 3)
    for t in order:
        s_ = a[a.best_type == t]
        ax.scatter(s_.du, s_.dv, s=14, color=colors.get(t, "grey"), edgecolor="k", lw=0.2, label=t)
    ax.plot(0, 0, marker="*", color="red", ms=18, mec="k")
    ax.set_aspect("equal"); ax.set_xlabel("Δu ≈ Δx (µm)"); ax.set_ylabel("Δv ≈ Δy (µm)"); ax.set_title("Around the origin (retinal plane)")
    ax = fig.add_subplot(2, 2, 4)
    for t in order:
        s_ = a[a.best_type == t]
        ax.scatter(s_[col], s_.syn_depth, s=14, color=colors.get(t, "grey"), edgecolor="k", lw=0.2)
    for y in (0, 1):
        ax.axhline(y, color="k", ls="--", lw=0.8)
    ax.invert_yaxis(); ax.set_xlabel(label); ax.set_ylabel("ChAT depth")
    ax.set_title("Depth vs distance")
    return fig, order


def path_vs_straight_figure(A, colors, types):
    a = A[(A.partner != 0) & A.best_type.isin(types)].dropna(subset=["dist_path_um"])
    fig = Figure(figsize=(13, 5.5), layout="constrained")
    ax = fig.add_subplot(1, 2, 1)
    for t in types:
        s_ = a[a.best_type == t]
        ax.scatter(s_.dist3d_um, s_.dist_path_um, s=14, color=colors.get(t, "grey"), edgecolor="k", lw=0.2, label=t)
    m = np.nanmax([a.dist3d_um.max(), a.dist_path_um.max()]) if len(a) else 1
    ax.plot([0, m], [0, m], "k--", lw=0.8, label="path = straight")
    ax.set_xlabel("straight 3D distance (µm)"); ax.set_ylabel("path distance along the cell (µm)")
    ax.set_title("Path vs straight distance"); ax.legend(fontsize=7, ncol=2)
    ax2 = fig.add_subplot(1, 2, 2)
    tort = (a.dist_path_um / a.dist3d_um.clip(lower=1)).clip(upper=5)
    ax2.hist(tort, bins=40, color="#4cc9f0")
    ax2.set_xlabel("path / straight (tortuosity)"); ax2.set_ylabel("annotations")
    ax2.set_title(f"Tortuosity (median {np.nanmedian(tort):.2f})")
    return fig


def polar_figure(A, colors, order):
    n = max(len(order), 1)
    ncol = min(5, n); nrow = int(np.ceil(n / ncol))
    fig = Figure(figsize=(3.2 * ncol, 3.2 * nrow), layout="constrained")
    a = A[A.partner != 0]
    rmax = a.dist_plane_um.max() * 1.05 if len(a) else 1
    for k, t in enumerate(order):
        ax = fig.add_subplot(nrow, ncol, k + 1, projection="polar")
        s_ = a[a.best_type == t]
        ax.scatter(np.radians(s_.angle_deg), s_.dist_plane_um, s=10, color=colors.get(t, "grey"))
        ax.set_ylim(0, rmax); ax.set_title(f"{t} (n={len(s_)})", fontsize=9); ax.tick_params(labelsize=6)
    fig.suptitle("Direction and distance from the origin, per partner type")
    return fig


def nn_stats(uv):
    """Nearest-neighbour distance (mean, SD) and regularity index (mean / SD) of soma positions."""
    from scipy.spatial import cKDTree
    uv = np.asarray(uv, float)
    if len(uv) < 3:
        return np.nan, np.nan, np.nan
    d, _ = cKDTree(uv).query(uv, k=2)
    nn = d[:, 1]
    return float(nn.mean()), float(nn.std()), float(nn.mean() / nn.std()) if nn.std() > 0 else np.nan


def strat_figure(feat, centres, s, title, square=None, somata_uv=None):
    fig = Figure(figsize=(16, 6.5), layout="constrained")
    ax1 = fig.add_subplot(1, 3, 1)
    cols = [c for c in feat.columns if c.startswith("p") and c[1:2] in "+-"]
    for _, r in feat.iterrows():
        ax1.plot(r[cols].to_numpy(float) / s.bin, centres, color="#e8590c", alpha=0.3, lw=1)
    if len(feat):
        ax1.plot(feat[cols].mean().to_numpy() / s.bin, centres, color="k", lw=2.5, label="mean")
    for y in (0, 1):
        ax1.axhline(y, color="k", ls="--", lw=0.8)
    ax1.set_ylim(s.ipl_range[1], s.ipl_range[0]); ax1.set_xlabel("density"); ax1.set_ylabel("ChAT depth (0 = OFF, 1 = ON)")
    ax1.set_title(f"{title} (n={len(feat)})"); ax1.legend()
    ax2 = fig.add_subplot(1, 3, 2)
    many = len(feat) > 25
    for _, r in feat.iterrows():
        h = r.get("hull")
        if isinstance(h, np.ndarray):
            if many:      # many / large overlapping arbors: thin outlines only, so the somata stay visible
                ax2.add_patch(Polygon(h, closed=True, fill=False, edgecolor="#e8590c", alpha=0.25, lw=0.6))
            else:
                ax2.add_patch(Polygon(h, closed=True, facecolor="#e8590c", alpha=0.25, edgecolor="#e8590c"))
    if square is not None:
        ax2.add_patch(square)
    t2 = "Outlines at main depth"
    if somata_uv is not None and len(somata_uv):
        ax2.scatter(somata_uv[:, 0], somata_uv[:, 1], s=18, color="k", edgecolor="white", lw=0.6, zorder=5, label="somata")
        m, sd, ri = nn_stats(somata_uv)
        if not np.isnan(m):
            t2 = f"Somata (n={len(somata_uv)}) + outlines\nNN {m:.0f} ± {sd:.0f} µm · regularity {ri:.1f}"
        ax2.legend(loc="lower right", fontsize=8)
    ax2.autoscale_view(); ax2.set_aspect("equal"); ax2.set_xlabel("u ≈ x (µm)"); ax2.set_ylabel("v ≈ y (µm)")
    ax2.set_title(t2, fontsize=10)
    ax3 = fig.add_subplot(1, 3, 3)
    ax3.scatter(feat.get("term_diam_um", []), feat.get("median", []), s=25, color="#e8590c", edgecolor="k", lw=0.3)
    for y in (0, 1):
        ax3.axhline(y, color="k", ls="--", lw=0.8)
    ax3.invert_yaxis(); ax3.set_xlabel("diameter (µm)"); ax3.set_ylabel("median ChAT depth")
    ax3.set_title("Depth vs size")
    return fig
