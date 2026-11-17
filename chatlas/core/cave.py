"""Access to CAVE: labels, root IDs, segmentation lookups."""
from collections import Counter
from datetime import datetime, timezone

import numpy as np
import pandas as pd


class Cave:
    def __init__(self, settings):
        self.s = settings
        self._client = None
        self._cv = None
        self._labels = None
        self.now = datetime.now(timezone.utc)

    # --- connections -------------------------------------------------------------
    @property
    def client(self):
        if self._client is None:
            from caveclient import CAVEclient
            self._client = CAVEclient(self.s.datastack, server_address=self.s.server)
        return self._client

    @property
    def cv(self):
        if self._cv is None:
            from cloudvolume import CloudVolume
            src = self.client.info.segmentation_source().replace("middleauth+", "")
            self._cv = CloudVolume(src, use_https=True, secrets=self.client.auth.token,
                                   progress=False, agglomerate=False, fill_missing=True)
        return self._cv

    def refresh_time(self):
        self.now = datetime.now(timezone.utc)

    # --- labels ------------------------------------------------------------------
    def _get_table(self, table):
        try:
            df = self.client.materialize.live_query(table, timestamp=self.now)
        except Exception:
            df = self.client.materialize.query_table(table)
        if "valid" in df:
            df = df[df["valid"].astype(bool)]
        pos = np.vstack(df["pt_position"].to_numpy())
        return pd.DataFrame({"root_id": df["pt_root_id"].astype("int64").to_numpy(),
                             "cls": df["classification_system"].astype(str).str.strip().to_numpy(),
                             "type": df["cell_type"].astype(str).str.strip().to_numpy(),
                             "x": pos[:, 0], "y": pos[:, 1], "z": pos[:, 2]})

    def labels(self, refresh=False, man_raw=None, aut_raw=None):
        """One row per root ID: manual/machine class and type, soma position (voxels)."""
        if self._labels is not None and not refresh and man_raw is None:
            return self._labels
        if man_raw is None:
            man_raw = self._get_table(self.s.labels_manual)
            aut_raw = self._get_table(self.s.labels_auto)
        self._labels = merge_labels(man_raw, aut_raw)
        return self._labels

    # --- root IDs ----------------------------------------------------------------
    def roots(self, svs):
        svs = np.asarray(svs, dtype=np.uint64)
        out = np.zeros(len(svs), dtype="int64")
        nz = svs != 0
        if nz.any():
            out[nz] = np.asarray(self.client.chunkedgraph.get_roots(svs[nz], timestamp=self.now), dtype="int64")
        return out

    def current_root(self, rid):
        """Current segment sharing the most with an (possibly outdated) root ID."""
        cg = self.client.chunkedgraph
        if cg.is_latest_roots([int(rid)])[0]:
            return int(rid), 1.0
        best, frac = cg.suggest_latest_roots(int(rid), return_fraction_overlap=True)
        return int(best), float(frac)

    # --- L2 cache: light point cloud of a cell ---------------------------------------
    def l2_points(self, rid, chunk=3000):
        """Representative points (µm) and membrane areas of a cell's L2 chunks (no mesh needed)."""
        cg, l2c = self.client.chunkedgraph, self.client.l2cache
        l2 = np.asarray(cg.get_leaves(int(rid), stop_layer=2), dtype=np.int64)
        P, W = [], []
        for a in range(0, len(l2), chunk):
            ids = l2[a:a + chunk]
            d = l2c.get_l2data(ids.tolist(), attributes=["rep_coord_nm", "area_nm2"])
            for i in ids:
                e = d.get(str(i), {})
                if "rep_coord_nm" in e:
                    P.append(e["rep_coord_nm"])
                    W.append(e.get("area_nm2", 1.0))
        if not P:
            raise ValueError("no L2 cache data")
        return np.asarray(P, float) / 1000.0, np.asarray(W, float)

    # --- segmentation lookup -----------------------------------------------------
    def supervoxels_at_nm(self, xyz_nm, radius_vox=2):
        """Supervoxel IDs at points (nm); points on label 0 take the most common label nearby."""
        cv = self.cv
        res = np.asarray(cv.resolution, float)
        vox = np.floor(np.asarray(xyz_nm, float) / res).astype(int)
        sv = _sample(cv, vox)
        zero = np.where(sv == 0)[0]
        if len(zero) and radius_vox > 0:
            offs = np.array([(dx, dy, 0) for dx in range(-radius_vox, radius_vox + 1)
                             for dy in range(-radius_vox, radius_vox + 1) if (dx, dy) != (0, 0)])
            nb = _sample(cv, np.concatenate([vox[i] + offs for i in zero]))
            n = len(offs)
            for k, i in enumerate(zero):
                lab = [l for l in nb[k * n:(k + 1) * n] if l != 0]
                if lab:
                    sv[i] = Counter(lab).most_common(1)[0][0]
        return sv


def _sample(cv, vox):
    uniq = np.unique(vox, axis=0)
    res = cv.scattered_points(uniq, mip=0)
    lut = {tuple(int(c) for c in k): int(v) for k, v in res.items()}
    return np.array([lut.get(tuple(int(c) for c in p), 0) for p in vox], dtype=np.uint64)


def merge_labels(man_raw, aut_raw):
    def collapse(df, tag):
        g = df.groupby("root_id")
        return pd.DataFrame({f"{tag}_class": g["cls"].agg(lambda s: "|".join(sorted(set(s)))),
                             f"{tag}_type": g["type"].agg(lambda s: "|".join(sorted(set(s)))),
                             f"{tag}_x": g["x"].first(), f"{tag}_y": g["y"].first(), f"{tag}_z": g["z"].first()})
    lab = collapse(man_raw, "manual").join(collapse(aut_raw, "auto"), how="outer")
    for a in "xyz":
        lab[a] = lab[f"manual_{a}"].fillna(lab[f"auto_{a}"])
    lab = lab.reset_index()
    conflict = lab["manual_type"].fillna("").str.contains("|", regex=False)
    lab["label"] = lab["manual_type"].where(lab["manual_type"].notna() & ~conflict)
    lab["cls"] = lab["manual_class"].fillna(lab["auto_class"]).replace({"": "unclassified", "nan": "unclassified"})
    lab["any_type"] = lab["label"].fillna(lab["auto_type"])
    return lab[["root_id", "cls", "label", "manual_class", "manual_type", "auto_class", "auto_type", "any_type", "x", "y", "z"]]
