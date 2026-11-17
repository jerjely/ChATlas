"""Synapse-partner pipeline: Neuroglancer line annotations on one cell -> partners, types, ChAT depth."""
import json

import numpy as np
import pandas as pd

from .chat import features, fit_frame_from_sacs, profile_bins, qc_flags


# ---------------------------------------------------------------------------------------------
# Neuroglancer state
# ---------------------------------------------------------------------------------------------
def parse_state(text):
    """Parse a Neuroglancer JSON state (extra text before the first '{' is ignored)."""
    start = text.index("{")
    state, _ = json.JSONDecoder().raw_decode(text[start:])
    ann_layers = [l for l in state.get("layers", []) if l.get("type") == "annotation"]
    if not ann_layers:
        raise ValueError("No annotation layer in this state.")
    al = max(ann_layers, key=lambda l: len(l.get("annotations", [])))
    src = al.get("source", {})
    dims = (src.get("transform", {}).get("outputDimensions") if isinstance(src, dict) else None) or state["dimensions"]
    res_nm = np.array([dims[a][0] * 1e9 for a in ("x", "y", "z")])
    lines = [a for a in al.get("annotations", []) if a.get("type") == "line"]
    pts = [a for a in al.get("annotations", []) if a.get("type") == "point"]
    seg_ids = []
    for l in state.get("layers", []):
        if l.get("type") == "segmentation":
            seg_ids += [int(str(x).lstrip("!")) for x in l.get("segments", [])]
    df = pd.DataFrame({"annotation_id": [a.get("id") for a in lines],
                       "Ax": [a["pointA"][0] for a in lines], "Ay": [a["pointA"][1] for a in lines], "Az": [a["pointA"][2] for a in lines],
                       "Bx": [a["pointB"][0] for a in lines], "By": [a["pointB"][1] for a in lines], "Bz": [a["pointB"][2] for a in lines]})
    return dict(lines=df, res_nm=res_nm, segments=seg_ids, n_points=len(pts), layer=al.get("name", "annotation"))


# ---------------------------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------------------------
class PartnerResult:
    pass


def run_partner_pipeline(parsed, cave, meshes, s, log=print, progress=None, cancelled=lambda: False,
                         labels=None, roots_AB=None):
    """Returns a PartnerResult. `labels` / `roots_AB` can be passed in (for offline tests)."""
    R = PartnerResult()
    ann = parsed["lines"].copy()
    res = parsed["res_nm"]
    vox_nm = np.asarray(s.voxel_nm, float)
    if len(ann) == 0:
        raise ValueError("The annotation layer has no line annotations.")
    log(f"{len(ann)} line annotations")

    # 1. roots at both ends
    if roots_AB is None:
        if progress:
            progress(0, 0, "looking up segments at both ends of every line")
        A_nm = ann[["Ax", "Ay", "Az"]].to_numpy(float) * res
        B_nm = ann[["Bx", "By", "Bz"]].to_numpy(float) * res
        sv = cave.supervoxels_at_nm(np.vstack([A_nm, B_nm]))
        roots = cave.roots(sv)
        ann["root_A"], ann["root_B"] = roots[:len(ann)], roots[len(ann):]
    else:
        ann["root_A"], ann["root_B"] = roots_AB
    target = int(pd.concat([ann.root_A, ann.root_B]).replace(0, np.nan).dropna().mode()[0])
    on_A, on_B = ann.root_A == target, ann.root_B == target
    ann["partner"] = np.where(on_A & ~on_B, ann.root_B, np.where(on_B & ~on_A, ann.root_A, 0)).astype("int64")
    ann["target_end"] = np.where(on_A & ~on_B, "A", np.where(on_B & ~on_A, "B", ""))
    xyz = np.where((ann.target_end == "B").to_numpy()[:, None], ann[["Bx", "By", "Bz"]].to_numpy(float),
                   ann[["Ax", "Ay", "Az"]].to_numpy(float))
    syn_nm = xyz * res
    ann[["sx", "sy", "sz"]] = syn_nm / vox_nm          # synapse position in table voxels
    R.target = target
    log(f"target cell (most frequent end): {target}; A on target {on_A.sum()}, B on target {on_B.sum()}, "
        f"partners {ann.loc[ann.partner != 0, 'partner'].nunique()}")
    if parsed.get("segments"):
        log(f"segment(s) in the link: {parsed['segments']}")

    # 2. labels
    if labels is None:
        if progress:
            progress(0, 0, "loading cell-type tables")
        labels = cave.labels()
    lab = labels
    partners = (ann[ann.partner != 0].groupby("partner")
                .agg(n_annotations=("partner", "size")).reset_index().rename(columns={"partner": "root_id"}))
    partners = partners.merge(lab[["root_id", "cls", "label", "manual_type", "auto_type", "x", "y", "z"]], on="root_id", how="left")
    partners["cls"] = partners["cls"].fillna("not in tables")

    # 3. ChAT frame from SACs around the annotations
    query_xy = ann[["sx", "sy"]].to_numpy(float)
    frame = fit_frame_from_sacs(lab, query_xy, meshes, s, log=log, progress=progress, cancelled=cancelled)
    R.frame = frame
    syn_uvw = frame.to_uvw(syn_nm / 1000)
    ann["syn_depth"], ann["syn_covered"] = frame.depth(syn_uvw)
    ann[["su", "sv", "sw"]] = syn_uvw
    log(f"annotations inside SAC coverage: {ann.syn_covered.mean():.0%}")

    # 4. bipolar-like partners + reference bipolars -> features
    is_bcish = partners.cls.str.contains("BC") | (partners.cls == "not in tables")
    bc_partners = partners[is_bcish]
    from scipy.spatial import cKDTree
    tree = cKDTree(query_xy)
    bc_lab = lab[lab.cls.fillna("").str.contains("BC") & lab.label.notna()].copy()
    bc_lab["dist_um"] = tree.query(bc_lab[["x", "y"]].to_numpy(float))[0] * vox_nm[0] / 1000
    refs = bc_lab[bc_lab.dist_um <= s.ref_radius_um].sort_values("dist_um").groupby("label").head(s.ref_per_type)
    refs = refs[~refs.root_id.isin(partners.root_id)]
    log(f"bipolar-like partners: {len(bc_partners)} | reference bipolars: {len(refs)}")
    ids = [target] + list(bc_partners.root_id) + list(refs.root_id)
    avail = meshes.ensure(ids, progress=progress, log=log, cancelled=cancelled)

    def measure(df):
        rows = []
        for k, r in enumerate(df.root_id):
            if cancelled():
                break
            if r in avail:
                rows.append({"root_id": r, **features(frame.to_uvw(meshes.sample(r, s.samples_per_um2_cell)), frame, s)})
            if progress:
                progress(k + 1, len(df), "measuring stratification")
        out = pd.DataFrame(rows)
        if len(out):
            out["qc"] = qc_flags(out, s)
        return out

    pf = bc_partners.merge(measure(bc_partners), on="root_id", how="inner") if len(bc_partners) else pd.DataFrame()
    rf = refs.merge(measure(refs), on="root_id", how="inner") if len(refs) else pd.DataFrame()
    R.target_features = features(frame.to_uvw(meshes.sample(target, s.samples_per_um2_cell)), frame, s) if target in avail else None

    # 5. classifier on labelled bipolars
    _, _, PROFILE_COLS = profile_bins(s)
    FEATS = PROFILE_COLS + ["median", "q10", "q90", "thickness", "term_diam_um"]
    pred = pd.DataFrame(columns=["root_id", "predicted", "p", "second", "p2"])
    R.cv_accuracy, R.cv_report = np.nan, ""
    if len(pf):
        ok_p = pf[pf.qc == "ok"]
        ok_r = rf[rf.qc == "ok"] if len(rf) else rf
        lab_all = pd.concat([ok_p[ok_p.label.notna()], ok_r]) if len(ok_r) else ok_p[ok_p.label.notna()]
        lab_all = lab_all.dropna(subset=FEATS)
        counts = lab_all.label.value_counts()
        keep = counts[counts >= s.min_cells_per_type].index
        train = lab_all[lab_all.label.isin(keep)]
        if len(keep) >= 2:
            from sklearn.linear_model import LogisticRegression
            from sklearn.metrics import classification_report
            from sklearn.model_selection import StratifiedKFold, cross_val_predict
            from sklearn.pipeline import make_pipeline
            from sklearn.preprocessing import StandardScaler
            model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=5000, C=0.5))
            n_splits = int(min(5, train.label.value_counts().min()))
            cvp = cross_val_predict(model, train[FEATS], train.label, cv=StratifiedKFold(n_splits, shuffle=True, random_state=0))
            R.cv_accuracy = float((cvp == train.label).mean())
            R.cv_report = classification_report(train.label, cvp, zero_division=0)
            log(f"classifier: {len(train)} labelled bipolars, {len(keep)} types, cross-validated accuracy {R.cv_accuracy:.0%}")
            model.fit(train[FEATS], train.label)
            todo = ok_p[ok_p.label.isna() | (ok_p.label != ok_p.auto_type)].dropna(subset=FEATS)
            if len(todo):
                P = model.predict_proba(todo[FEATS])
                top = np.argsort(-P, axis=1)
                pred = pd.DataFrame({"root_id": todo.root_id.to_numpy(), "predicted": model.classes_[top[:, 0]],
                                     "p": P[np.arange(len(P)), top[:, 0]], "second": model.classes_[top[:, 1]],
                                     "p2": P[np.arange(len(P)), top[:, 1]]})
        else:
            log("classifier skipped: fewer than 2 bipolar types with enough labelled cells nearby")
        R.reference = rf

    # 6. final table
    final = partners.copy()
    if len(pf):
        final = final.merge(pf[["root_id", "qc", "median", "q10", "q90", "thickness", "term_diam_um"]], on="root_id", how="left")
    final = final.merge(pred, on="root_id", how="left")
    final["best_type"] = final["label"]
    final["best_type"] = final["best_type"].fillna(final["predicted"].where(final["p"] >= 0.6))
    final["best_type"] = final["best_type"].fillna(final["auto_type"].where(final.cls != "not in tables"))
    final["best_type"] = final["best_type"].fillna("unknown")
    final["source"] = np.where(final.label.notna(), "manual",
                      np.where(final.predicted.notna() & (final.p >= 0.6) & final.label.isna(), "classifier",
                      np.where(final.auto_type.notna(), "machine", "none")))
    final["class"] = final["cls"]
    final.loc[(final["class"] == "not in tables") & (final.source == "classifier"), "class"] = "BC (predicted)"
    final = final.sort_values("n_annotations", ascending=False).reset_index(drop=True)

    ann = ann.merge(final[["root_id", "best_type", "class"]], left_on="partner", right_on="root_id", how="left").drop(columns="root_id")
    ann["best_type"] = ann["best_type"].fillna("no partner")
    R.ann, R.partners, R.labels = ann, final, lab
    R.syn_uvw = ann[["su", "sv", "sw"]].to_numpy(float)
    log("done")
    return R


def distances_from(R, origin_vox, s):
    """Add straight-line distance (µm) from an origin (table voxels) to every annotation."""
    vox_nm = np.asarray(s.voxel_nm, float)
    o_um = np.asarray(origin_vox, float) * vox_nm / 1000
    a_um = R.ann[["sx", "sy", "sz"]].to_numpy(float) * vox_nm / 1000
    A = R.ann.copy()
    A["dist3d_um"] = np.linalg.norm(a_um - o_um, axis=1)
    ou = R.frame.to_uvw(o_um[None, :])[0]
    au = R.syn_uvw
    A["dist_plane_um"] = np.hypot(au[:, 0] - ou[0], au[:, 1] - ou[1])
    A["angle_deg"] = np.degrees(np.arctan2(au[:, 1] - ou[1], au[:, 0] - ou[0])) % 360
    A["du"], A["dv"] = au[:, 0] - ou[0], au[:, 1] - ou[1]
    return A
