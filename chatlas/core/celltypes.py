"""Cells of one type around a point."""
import numpy as np
import pandas as pd


def type_catalog(labels, source="manual+machine"):
    """Counts per class and type."""
    col = "label" if source == "manual" else "any_type"
    cls = labels["manual_class"].fillna(labels["auto_class"]) if source != "manual" else labels["manual_class"]
    df = pd.DataFrame({"class": cls.fillna("unclassified"), "type": labels[col]}).dropna(subset=["type"])
    df = df[df["type"].astype(str).str.len() > 0]
    return df.groupby(["class", "type"]).size().rename("n").reset_index().sort_values(["class", "n"], ascending=[True, False])


def cells_of_type(labels, cell_type, center_vox, radius_um, vox_nm, source="manual+machine"):
    col = "label" if source == "manual" else "any_type"
    sel = labels[labels[col] == cell_type].copy()
    d = np.hypot(sel.x - center_vox[0], sel.y - center_vox[1]) * vox_nm[0] / 1000
    sel["dist_um"] = d
    sel = sel[d <= radius_um].sort_values("dist_um")
    sel["label_source"] = np.where(sel.label == cell_type, "manual", "machine")
    return sel


def context_cells(labels, center_vox, radius_um, vox_nm):
    d = np.hypot(labels.x - center_vox[0], labels.y - center_vox[1]) * vox_nm[0] / 1000
    out = labels[d <= radius_um].copy()
    out["dist_um"] = d[d <= radius_um]
    return out
