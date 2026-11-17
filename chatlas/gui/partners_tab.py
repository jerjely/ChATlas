"""Tab 1: synapse partners of an annotated cell."""
import os

import numpy as np
import pandas as pd
from qtpy import QtCore, QtWidgets

from ..core.chat import profile_bins
from ..core.partners import distances_from, parse_state, run_partner_pipeline
from .common import CLASS_COLORS, PlotDialog, hrow, make_table, ngl_open, run_in_thread, type_colors
from .plots import depth_figure, distance_figure, path_vs_straight_figure, polar_figure
from .viewer import Viewer3D


class PartnersTab(QtWidgets.QWidget):
    def __init__(self, ctx, log, parent=None):
        super().__init__(parent)
        self.ctx, self.log = ctx, log
        self.parsed = None
        self.R = None
        self.A = None
        self.colors = {}
        self.loaded_partner_types = set()
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        lay = QtWidgets.QHBoxLayout(self)
        lay.addWidget(split)

        # left controls
        left = QtWidgets.QWidget()
        L = QtWidgets.QVBoxLayout(left)
        g1 = QtWidgets.QGroupBox("1 · Annotations")
        l1 = QtWidgets.QVBoxLayout(g1)
        self.btn_load = QtWidgets.QPushButton("Load Neuroglancer state…")
        self.btn_load.setToolTip("A .txt / .json file with the Neuroglancer JSON state (e.g. copied from an email).\n"
                                 "Line annotations: one end on the target cell, the other on a partner.")
        self.lbl_state = QtWidgets.QLabel("no state loaded")
        self.lbl_state.setWordWrap(True)
        self.btn_run = QtWidgets.QPushButton("Analyse partners")
        self.btn_run.setObjectName("primary")
        self.btn_run.setEnabled(False)
        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.prog = QtWidgets.QProgressBar()
        self.prog_lbl = QtWidgets.QLabel("")
        for w in (self.btn_load, self.lbl_state, hrow(self.btn_run, self.btn_cancel), self.prog, self.prog_lbl):
            l1.addWidget(w)
        L.addWidget(g1)

        g2 = QtWidgets.QGroupBox("2 · Partner types")
        l2 = QtWidgets.QVBoxLayout(g2)
        self.types = QtWidgets.QListWidget()
        self.types.setMinimumHeight(220)
        b_all, b_none = QtWidgets.QPushButton("All"), QtWidgets.QPushButton("None")
        self.chk_target = QtWidgets.QCheckBox("Target cell mesh"); self.chk_target.setChecked(True)
        self.chk_surf = QtWidgets.QCheckBox("ChAT surfaces"); self.chk_surf.setChecked(True)
        self.chk_points = QtWidgets.QCheckBox("Annotation points"); self.chk_points.setChecked(True)
        self.chk_hover = QtWidgets.QCheckBox("Hover labels"); self.chk_hover.setChecked(True)
        self.btn_meshes = QtWidgets.QPushButton("Load partner meshes (checked types)")
        self.btn_meshes.setEnabled(False)
        self.btn_ngl = QtWidgets.QPushButton("Open checked types in Neuroglancer")
        self.btn_ngl.setEnabled(False)
        for w in (self.types, hrow(b_all, b_none, None), self.chk_target, self.chk_surf, self.chk_points, self.chk_hover, self.btn_meshes, self.btn_ngl):
            l2.addWidget(w)
        L.addWidget(g2)

        g3 = QtWidgets.QGroupBox("3 · Distance from soma / primary dendrite")
        l3 = QtWidgets.QVBoxLayout(g3)
        self.btn_pick = QtWidgets.QPushButton("Pick origin on the target cell (click in 3D)")
        self.ed_origin = QtWidgets.QLineEdit()
        self.ed_origin.setPlaceholderText("or type voxel x, y, z (Neuroglancer)")
        self.btn_set = QtWidgets.QPushButton("Set")
        self.lbl_origin = QtWidgets.QLabel("origin: not set")
        self.cb_metric = QtWidgets.QComboBox()
        self.cb_metric.addItems(["straight line in 3D", "along the cell (path through the arbor)"])
        self.lbl_path = QtWidgets.QLabel("")
        self.lbl_path.setWordWrap(True)
        self.btn_dist = QtWidgets.QPushButton("Distance plots…")
        self.btn_depth = QtWidgets.QPushButton("Depth plots…")
        self.btn_export = QtWidgets.QPushButton("Export tables…")
        for w in (self.btn_pick, hrow(self.ed_origin, self.btn_set), self.lbl_origin, hrow("distance", self.cb_metric), self.lbl_path,
                  self.btn_dist, self.btn_depth, self.btn_export):
            l3.addWidget(w)
        for b in (self.btn_pick, self.btn_set, self.btn_dist, self.btn_depth, self.btn_export):
            b.setEnabled(False)
        L.addWidget(g3)
        L.addStretch(1)
        scroll = QtWidgets.QScrollArea(); scroll.setWidget(left); scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(330)
        split.addWidget(scroll)

        # right: viewer + table
        right = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.viewer = Viewer3D()
        right.addWidget(self.viewer)
        self.table, self.model = make_table()
        right.addWidget(self.table)
        right.setSizes([650, 250])
        split.addWidget(right)
        split.setSizes([340, 1100])

        # signals
        self.btn_load.clicked.connect(self.load_state)
        self.btn_run.clicked.connect(self.run)
        self.btn_cancel.clicked.connect(self.cancel)
        b_all.clicked.connect(lambda: self._check_all(True))
        b_none.clicked.connect(lambda: self._check_all(False))
        self.types.itemChanged.connect(self._type_toggled)
        self.chk_target.toggled.connect(lambda v: self.viewer.set_group_visible("target", v))
        self.chk_surf.toggled.connect(lambda v: self.viewer.set_group_visible("surfaces", v))
        self.chk_points.toggled.connect(lambda v: self._apply_visibility())
        self.btn_meshes.clicked.connect(self.load_partner_meshes)
        self.btn_ngl.clicked.connect(self.open_ngl)
        self.chk_hover.toggled.connect(lambda v: setattr(self.viewer, "hover_enabled", v))
        self.btn_pick.clicked.connect(self.start_pick)
        self.viewer.picked.connect(self.on_picked)
        self.btn_set.clicked.connect(self.set_origin_text)
        self.btn_dist.clicked.connect(self.show_distance)
        self.cb_metric.currentIndexChanged.connect(lambda i: self._ensure_path() if i == 1 else None)
        self.btn_depth.clicked.connect(self.show_depth)
        self.btn_export.clicked.connect(self.export)
        self.table.clicked.connect(self.row_clicked)

    # ------------------------------------------------------------------ steps
    def load_state(self, path=None):
        if not path:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Neuroglancer state", "", "State (*.txt *.json);;All files (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                self.parsed = parse_state(f.read())
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Could not read state", str(e))
            return
        p = self.parsed
        self.lbl_state.setText(f"<b>{os.path.basename(path)}</b><br>{len(p['lines'])} line annotations "
                               f"(layer '{p['layer']}')<br>segment(s) in link: {', '.join(map(str, p['segments'])) or '-'}")
        self.btn_run.setEnabled(len(p["lines"]) > 0)
        self.log(f"loaded state {path}: {len(p['lines'])} line annotations")

    def run(self):
        self.btn_run.setEnabled(False); self.btn_cancel.setEnabled(True)
        self.ctx.cave.refresh_time()
        self.worker = run_in_thread(self, run_partner_pipeline, self.on_done, self.on_fail, self.on_progress, self.log,
                                    self.parsed, self.ctx.cave, self.ctx.meshes, self.ctx.settings)

    def cancel(self):
        if getattr(self, "worker", None):
            self.worker.cancel()
            self.log("cancelling…")

    def on_progress(self, i, n, msg):
        self.prog.setMaximum(n if n > 0 else 0)
        self.prog.setValue(i)
        self.prog_lbl.setText(msg)

    def on_fail(self, msg):
        self.btn_run.setEnabled(True); self.btn_cancel.setEnabled(False)
        self.prog.setMaximum(1); self.prog.setValue(0); self.prog_lbl.setText("failed")
        self.log("ERROR: " + msg.splitlines()[0])
        QtWidgets.QMessageBox.critical(self, "Analysis failed", msg[:3000])

    def on_done(self, R):
        self.R, self.A = R, None
        self.graph = None
        self.btn_run.setEnabled(True); self.btn_cancel.setEnabled(False)
        self.prog.setMaximum(1); self.prog.setValue(1); self.prog_lbl.setText("done")
        P = R.partners
        cnt = P.groupby("best_type").agg(cells=("root_id", "size"), annotations=("n_annotations", "sum"),
                                         cls=("class", lambda s: s.mode()[0])).sort_values("annotations", ascending=False)
        self.type_order = list(cnt.index)
        self.colors = type_colors(self.type_order)
        self.types.blockSignals(True)
        self.types.clear()
        for t, r in cnt.iterrows():
            it = QtWidgets.QListWidgetItem(f"{t}   [{r.cls}]   {r.cells} cells · {r.annotations} ann.")
            it.setData(QtCore.Qt.UserRole, t)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked)
            it.setForeground(QtGui_color(self.colors[t]))
            self.types.addItem(it)
        self.types.blockSignals(False)
        cols = ["root_id", "best_type", "class", "source", "n_annotations", "label", "auto_type", "predicted", "p", "median", "term_diam_um", "qc"]
        self.model.set(P[[c for c in cols if c in P]])
        self.draw_scene()
        for b in (self.btn_meshes, self.btn_ngl, self.btn_pick, self.btn_set, self.btn_depth, self.btn_export):
            b.setEnabled(True)
        acc = "" if np.isnan(R.cv_accuracy) else f", classifier CV accuracy {R.cv_accuracy:.0%}"
        self.log(f"partners: {len(P)}, types: {len(self.type_order)}{acc}")

    # ------------------------------------------------------------------ scene
    def draw_scene(self):
        R, s, v = self.R, self.ctx.settings, self.viewer
        v.clear()
        self.loaded_partner_types = set()
        uvw = R.syn_uvw
        pad = 25
        grid = R.frame.surface_grid(uvw[:, 0].min() - pad, uvw[:, 0].max() + pad, uvw[:, 1].min() - pad, uvw[:, 1].max() + pad, n=140)
        v.add_surface("OFF", *grid["OFF"], color="#b5179e", group="surfaces", label="OFF ChAT band", opacity=0.25)
        v.add_surface("ON", *grid["ON"], color="#3a86ff", group="surfaces", label="ON ChAT band", opacity=0.25)
        if self.ctx.meshes.has(R.target):
            tv, tf = self.ctx.meshes.simplified(R.target, s.faces_target)
            v.add_mesh("target", R.frame.to_uvw(tv), tf, "#00c864", group="target", label=f"target cell {R.target}", opacity=0.55)
        a = R.ann[R.ann.partner != 0]
        for t in self.type_order:
            m = (a.best_type == t).to_numpy()
            if not m.any():
                continue
            sub = a[m]
            labs = [f"{t} · partner {p} · depth {d:.2f}" for p, d in zip(sub.partner, sub.syn_depth)]
            v.add_points(f"ann:{t}", uvw[a.index[m]], self.colors[t], group=f"ann:{t}", labels=labs, size=9)
        v.reset_view(depth_axis=(0, 0, 1))
        self._apply_visibility()

    def _checked_types(self):
        out = []
        for i in range(self.types.count()):
            it = self.types.item(i)
            if it.checkState() == QtCore.Qt.Checked:
                out.append(it.data(QtCore.Qt.UserRole))
        return out

    def _check_all(self, on):
        self.types.blockSignals(True)
        for i in range(self.types.count()):
            self.types.item(i).setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
        self.types.blockSignals(False)
        self._apply_visibility()

    def _type_toggled(self, item):
        self._apply_visibility()

    def _apply_visibility(self):
        if self.R is None:
            return
        checked = set(self._checked_types())
        for t in self.type_order:
            on = t in checked
            self.viewer.set_group_visible(f"ann:{t}", on and self.chk_points.isChecked())
            self.viewer.set_group_visible(f"mesh:{t}", on)

    def load_partner_meshes(self):
        types = [t for t in self._checked_types() if t not in self.loaded_partner_types]
        if not types:
            self.log("partner meshes for the checked types are already shown")
            return
        P = self.R.partners[self.R.partners.best_type.isin(types)]
        if len(P) > 300 and QtWidgets.QMessageBox.question(
                self, "Many meshes", f"{len(P)} partner meshes — this can take a while the first time. Continue?") != QtWidgets.QMessageBox.Yes:
            return
        s = self.ctx.settings

        def job(log, progress, cancelled):
            avail = self.ctx.meshes.ensure(P.root_id, progress=progress, log=log, cancelled=cancelled)
            out = []
            for k, r in enumerate(P.itertuples()):
                if cancelled():
                    break
                if r.root_id in avail:
                    vv, ff = self.ctx.meshes.simplified(r.root_id, s.faces_per_cell)
                    out.append((r.best_type, r.root_id, r.n_annotations, vv, ff))
                progress(k + 1, len(P), "preparing partner meshes")
            return out

        self.btn_meshes.setEnabled(False)
        run_in_thread(self, job, lambda out: self._add_partner_meshes(out, types), self.on_fail, self.on_progress, self.log)

    def _add_partner_meshes(self, out, types):
        cls = self.R.partners.set_index("root_id")["class"].to_dict()
        for t, rid, n, vv, ff in out:
            self.viewer.add_mesh(f"p:{rid}", self.R.frame.to_uvw(vv), ff, self.colors.get(t, "#cccccc"), group=f"mesh:{t}",
                                 label=f"{t} · {cls.get(rid, '')} · {rid} · {n} annotations")
        self.loaded_partner_types |= set(types)
        self.btn_meshes.setEnabled(True)
        self._apply_visibility()
        self.viewer.render()
        self.log(f"added {len(out)} partner meshes")

    def open_ngl(self):
        types = self._checked_types()
        P = self.R.partners[self.R.partners.best_type.isin(types)]
        segs = {self.R.target: "#00c864"}
        segs.update({int(r.root_id): self.colors.get(r.best_type, "#cccccc") for r in P.itertuples()})
        a = self.R.ann[(self.R.ann.partner != 0) & self.R.ann.best_type.isin(types)]
        layers = []
        for t in types:
            sub = a[a.best_type == t]
            if len(sub):
                layers.append(dict(name=f"syn {t}", color=self.colors.get(t, "#ffff00"),
                                   points=sub[["sx", "sy", "sz"]].to_numpy(float),
                                   descriptions=[f"{t} | partner {p}" for p in sub.partner]))
        pos = a[["sx", "sy", "sz"]].to_numpy(float).mean(axis=0) if len(a) else None
        if len(segs) > 400:
            self.log(f"{len(segs)} cells — Neuroglancer will load them progressively")
        ngl_open(self, segs, layers, pos, layer_name="partners")

    def row_clicked(self, idx):
        df = self.model.df()
        rid = int(df.iloc[idx.row()]["root_id"])
        QtWidgets.QApplication.clipboard().setText(str(rid))
        if f"p:{rid}" in self.viewer.items:
            self.viewer.focus(f"p:{rid}")
            self.viewer.highlight(f"p:{rid}")
        else:
            a = self.R.ann[self.R.ann.partner == rid]
            if len(a):
                c = self.R.syn_uvw[a.index].mean(axis=0)
                self.viewer.plotter.set_focus(c)
                self.viewer.mark(c, color="#ffffff", key="__sel__")
        self.log(f"partner {rid} (copied to clipboard)")

    # ------------------------------------------------------------------ distances
    def start_pick(self):
        if "target" not in self.viewer.items:
            QtWidgets.QMessageBox.information(self, "No target mesh", "The target cell mesh is not loaded.")
            return
        self.chk_target.setChecked(True)
        self.viewer.start_pick(["target"])
        self.log("click on the target cell where the primary dendrite leaves the soma…")

    def on_picked(self, pos_uvw):
        s = self.ctx.settings
        um = self.R.frame.from_uvw(np.asarray(pos_uvw)[None, :])[0]
        vox = um * 1000 / np.asarray(s.voxel_nm, float)
        self.ed_origin.setText(f"{vox[0]:.0f}, {vox[1]:.0f}, {vox[2]:.0f}")
        self.set_origin(vox)

    def set_origin_text(self):
        try:
            vox = [float(x) for x in self.ed_origin.text().replace(";", ",").split(",")]
            assert len(vox) == 3
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Origin", "Enter three numbers: x, y, z (Neuroglancer voxels).")
            return
        s = self.ctx.settings
        um = np.asarray(vox) * np.asarray(s.voxel_nm, float) / 1000
        self.viewer.mark(self.R.frame.to_uvw(um[None, :])[0])
        self.set_origin(vox)

    def set_origin(self, vox):
        self.origin_vox = np.asarray(vox, float)
        self.A = distances_from(self.R, self.origin_vox, self.ctx.settings)
        a = self.A[self.A.partner != 0]
        self.lbl_origin.setText(f"origin voxel {self.origin_vox.round(0).astype(int).tolist()}<br>"
                                f"annotation distances {a.dist3d_um.min():.0f}–{a.dist3d_um.max():.0f} µm (median {a.dist3d_um.median():.0f})")
        self.btn_dist.setEnabled(True)
        self.log(f"origin set at voxel {self.origin_vox.round(0).astype(int).tolist()}")
        if self.cb_metric.currentIndex() == 1:
            self._ensure_path()

    # ------------------------------------------------------------------ path distances
    def _ensure_path(self):
        if self.A is None:
            self.lbl_path.setText("set the origin first")
            return
        if "dist_path_um" in self.A:
            return
        from ..core.paths import build_arbor_graph
        s, R = self.ctx.settings, self.R
        vox = np.asarray(s.voxel_nm, float)
        o_um = self.origin_vox * vox / 1000
        t_um = self.A[["sx", "sy", "sz"]].to_numpy(float) * vox / 1000
        graph = getattr(self, "graph", None)

        def job(log, progress, cancelled):
            progress(0, 0, "building the arbor graph of the target cell")
            g = graph or build_arbor_graph(self.ctx.cave, self.ctx.meshes, R.target, s, log=log)
            progress(0, 0, "computing path distances")
            path, snap = g.distances(o_um, t_um)
            return g, path, snap

        self.lbl_path.setText("computing path distances…")
        self.btn_dist.setEnabled(False)
        run_in_thread(self, job, self._path_done, self.on_fail, self.on_progress, self.log)

    def _path_done(self, res):
        g, path, snap = res
        self.graph = g
        self.A["dist_path_um"] = path
        self.A["snap_um"] = snap
        a = self.A[self.A.partner != 0]
        ok = a.dist_path_um.notna()
        ratio = (a.dist_path_um / a.dist3d_um.clip(lower=1))[ok]
        self.lbl_path.setText(f"path distances: {g.source}, {ok.mean():.0%} of annotations connected to the origin, "
                              f"median snap {np.nanmedian(a.snap_um):.1f} µm"
                              + (f", median path/straight {ratio.median():.2f}" if ok.any() else
                                 " — no annotation is connected to the origin (fragmented cell?)"))
        self.btn_dist.setEnabled(True)
        self.prog.setMaximum(1); self.prog.setValue(1); self.prog_lbl.setText("path distances ready")
        if (~ok).any():
            self.log(f"{int((~ok).sum())} annotations sit on pieces not connected to the origin (no path; left out)")

    def show_distance(self):
        types = self._checked_types()
        path = self.cb_metric.currentIndex() == 1
        if path and "dist_path_um" not in self.A:
            self._ensure_path()
            return
        col, label = ("dist_path_um", "path distance along the cell (µm)") if path else ("dist3d_um", "3D distance from origin (µm)")
        fig, order = distance_figure(self.A, self.colors, types, col=col, label=label)
        PlotDialog(fig, f"Distance from origin by partner type — {'along the cell' if path else 'straight line'}", self).show()
        PlotDialog(polar_figure(self.A, self.colors, order), "Direction and distance by partner type", self).show()
        if path:
            PlotDialog(path_vs_straight_figure(self.A, self.colors, types), "Path vs straight distance", self).show()
        from scipy.stats import ks_2samp
        a = self.A[self.A.partner != 0].dropna(subset=[col])
        rows = []
        for t in order:
            d_in, d_out = a[a.best_type == t][col], a[a.best_type != t][col]
            p = ks_2samp(d_in, d_out).pvalue if len(d_in) >= 3 else np.nan
            rows.append(f"{t:30s} n={len(d_in):4d}  median {d_in.median():7.1f} µm  KS p={p:.3g}  (Bonferroni {min(1, p * len(order)):.3g})")
        self.log("distance per type (KS test vs all other annotations):\n" + "\n".join(rows))

    def show_depth(self):
        s = self.ctx.settings
        edges, centres, _ = profile_bins(s)
        fig = depth_figure(self.R, self.colors, self._checked_types(), s, (edges, centres))
        PlotDialog(fig, "ChAT depth of annotations", self).show()

    def export(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Export to folder", self.ctx.settings.output_dir)
        if not d:
            return
        self.R.partners.to_csv(os.path.join(d, "partners.csv"), index=False)
        (self.A if self.A is not None else self.R.ann).to_csv(os.path.join(d, "annotations.csv"), index=False)
        if self.R.cv_report:
            with open(os.path.join(d, "classifier_report.txt"), "w") as f:
                f.write(f"cross-validated accuracy: {self.R.cv_accuracy:.3f}\n\n{self.R.cv_report}")
        self.viewer.screenshot(os.path.join(d, "partners_3d.png"))
        self.log(f"exported to {d}")


def QtGui_color(hexcol):
    from qtpy import QtGui
    return QtGui.QBrush(QtGui.QColor(hexcol))
