"""Tab 2: all cells of one type around a point."""
import os

import numpy as np
import pandas as pd
from matplotlib.patches import Circle
from qtpy import QtCore, QtWidgets

from ..core.celltypes import cells_of_type, context_cells, type_catalog
from ..core.chat import features, fit_frame_from_sacs, profile_bins, qc_flags, query_points_for_disc
from .common import CLASS_COLORS, PALETTE, PlotDialog, hrow, make_table, ngl_open, run_in_thread
from .plots import strat_figure
from .viewer import Viewer3D


class CellTypeTab(QtWidgets.QWidget):
    def __init__(self, ctx, log, parent=None):
        super().__init__(parent)
        self.ctx, self.log = ctx, log
        self.catalog = None
        self.frame = None
        self.cells = None
        self._build()

    def _build(self):
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        QtWidgets.QHBoxLayout(self).addWidget(split)
        left = QtWidgets.QWidget()
        L = QtWidgets.QVBoxLayout(left)

        g1 = QtWidgets.QGroupBox("1 · Cell type")
        l1 = QtWidgets.QFormLayout(g1)
        self.btn_tables = QtWidgets.QPushButton("Load cell-type tables")
        self.cb_source = QtWidgets.QComboBox(); self.cb_source.addItems(["manual+machine", "manual"])
        self.cb_class = QtWidgets.QComboBox()
        self.cb_type = QtWidgets.QComboBox()
        self.cb_type.setEditable(True)
        self.cb_type.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        l1.addRow(self.btn_tables)
        l1.addRow("labels", self.cb_source)
        l1.addRow("class", self.cb_class)
        l1.addRow("type", self.cb_type)
        L.addWidget(g1)

        g2 = QtWidgets.QGroupBox("2 · Region")
        l2 = QtWidgets.QFormLayout(g2)
        self.ed_cx, self.ed_cy = QtWidgets.QLineEdit("40000"), QtWidgets.QLineEdit("50000")
        self.ed_root = QtWidgets.QLineEdit(); self.ed_root.setPlaceholderText("root ID (optional)")
        self.btn_root = QtWidgets.QPushButton("Centre on cell")
        self.sp_radius = QtWidgets.QDoubleSpinBox(); self.sp_radius.setRange(5, 3000); self.sp_radius.setValue(150); self.sp_radius.setSuffix(" µm")
        self.sp_max = QtWidgets.QSpinBox(); self.sp_max.setRange(1, 5000); self.sp_max.setValue(300)
        l2.addRow("centre x (voxel)", self.ed_cx)
        l2.addRow("centre y (voxel)", self.ed_cy)
        l2.addRow(hrow(self.ed_root, self.btn_root))
        l2.addRow("radius", self.sp_radius)
        l2.addRow("max cells", self.sp_max)
        L.addWidget(g2)

        g3 = QtWidgets.QGroupBox("3 · Display")
        l3 = QtWidgets.QVBoxLayout(g3)
        self.chk_chat = QtWidgets.QCheckBox("ChAT surfaces (fit from nearby SACs)"); self.chk_chat.setChecked(True)
        self.chk_context = QtWidgets.QCheckBox("Somata of all labelled cells in the region (dots)")
        self.chk_hover = QtWidgets.QCheckBox("Hover labels"); self.chk_hover.setChecked(True)
        self.sp_faces = QtWidgets.QSpinBox(); self.sp_faces.setRange(200, 100000); self.sp_faces.setSingleStep(500)
        self.sp_faces.setValue(self.ctx.settings.faces_per_cell)
        self.btn_show = QtWidgets.QPushButton("Show cells"); self.btn_show.setObjectName("primary"); self.btn_show.setEnabled(False)
        self.btn_cancel = QtWidgets.QPushButton("Cancel"); self.btn_cancel.setEnabled(False)
        self.prog = QtWidgets.QProgressBar(); self.prog_lbl = QtWidgets.QLabel("")
        self.sp_qcdiam = QtWidgets.QDoubleSpinBox(); self.sp_qcdiam.setRange(0, 5000); self.sp_qcdiam.setDecimals(0)
        self.sp_qcdiam.setSuffix(" µm"); self.sp_qcdiam.setSpecialValueText("no limit")
        self.sp_qcdiam.setToolTip("Cells larger than this at their main depth are flagged as possible merges.\n"
                                  "Set automatically: 60 µm for bipolar cells, no limit for other classes.")
        self.sp_qccov = QtWidgets.QDoubleSpinBox(); self.sp_qccov.setRange(0, 1); self.sp_qccov.setSingleStep(0.1)
        self.sp_qccov.setValue(0.5)
        self.sp_qccov.setToolTip("Minimum share of the cell (at its main depth) that must lie where the ChAT surfaces are supported by SAC dendrites.")
        self.chk_allqc = QtWidgets.QCheckBox("Plot cells failing QC too")
        self.btn_strat = QtWidgets.QPushButton("Stratification & mosaic…"); self.btn_strat.setEnabled(False)
        self.btn_export = QtWidgets.QPushButton("Export table…"); self.btn_export.setEnabled(False)
        self.btn_ngl = QtWidgets.QPushButton("Open in Neuroglancer"); self.btn_ngl.setEnabled(False)
        for w in (self.chk_chat, self.chk_context, self.chk_hover, hrow("faces per cell", self.sp_faces), hrow(self.btn_show, self.btn_cancel),
                  self.prog, self.prog_lbl, hrow("QC max size", self.sp_qcdiam), hrow("QC min ChAT coverage", self.sp_qccov),
                  self.chk_allqc, self.btn_strat, self.btn_ngl, self.btn_export):
            l3.addWidget(w)
        L.addWidget(g3)
        L.addStretch(1)
        scroll = QtWidgets.QScrollArea(); scroll.setWidget(left); scroll.setWidgetResizable(True); scroll.setMinimumWidth(330)
        split.addWidget(scroll)

        right = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.viewer = Viewer3D()
        right.addWidget(self.viewer)
        self.table, self.model = make_table()
        right.addWidget(self.table)
        right.setSizes([650, 250])
        split.addWidget(right)
        split.setSizes([340, 1100])

        self.btn_tables.clicked.connect(self.load_tables)
        self.chk_hover.toggled.connect(lambda v: setattr(self.viewer, "hover_enabled", v))
        self.cb_source.currentIndexChanged.connect(self._fill_classes)
        self.cb_class.currentIndexChanged.connect(self._fill_types)
        self.cb_type.currentIndexChanged.connect(self._auto_qc)
        self.btn_root.clicked.connect(self.center_on_root)
        self.btn_show.clicked.connect(self.show_cells)
        self.btn_cancel.clicked.connect(lambda: getattr(self, "worker", None) and self.worker.cancel())
        self.btn_strat.clicked.connect(self.stratification)
        self.btn_export.clicked.connect(self.export)
        self.btn_ngl.clicked.connect(self.open_ngl)
        self.table.clicked.connect(self.row_clicked)

    # ------------------------------------------------------------------ tables
    def load_tables(self):
        self.btn_tables.setEnabled(False)
        self.ctx.cave.refresh_time()
        run_in_thread(self, lambda log, progress, cancelled: self.ctx.cave.labels(refresh=True),
                      self._tables_loaded, self._fail, self._progress, self.log)
        self.prog.setMaximum(0)
        self.prog_lbl.setText("loading cell-type tables…")

    def _tables_loaded(self, labels):
        self.btn_tables.setEnabled(True)
        self.prog.setMaximum(1); self.prog.setValue(1); self.prog_lbl.setText(f"{len(labels):,} labelled cells")
        self.log(f"cell-type tables: {len(labels):,} cells")
        self._fill_classes()
        self.btn_show.setEnabled(True)

    def _fill_classes(self):
        labels = self.ctx.cave._labels
        if labels is None:
            return
        self.catalog = type_catalog(labels, self.cb_source.currentText())
        self.cb_class.blockSignals(True)
        self.cb_class.clear()
        cls = self.catalog.groupby("class").n.sum().sort_values(ascending=False)
        self.cb_class.addItem(f"all ({cls.sum():,})", None)
        for c, n in cls.items():
            self.cb_class.addItem(f"{c} ({n:,})", c)
        self.cb_class.blockSignals(False)
        self._fill_types()

    def _fill_types(self):
        if self.catalog is None:
            return
        c = self.cb_class.currentData()
        cat = self.catalog if c is None else self.catalog[self.catalog["class"] == c]
        cat = cat.groupby("type").n.sum().sort_values(ascending=False)
        self.cb_type.clear()
        for t, n in cat.items():
            self.cb_type.addItem(f"{t}  ({n:,})", t)

    def _auto_qc(self):
        t = self.cb_type.currentData()
        labels = self.ctx.cave._labels
        cls = ""
        if labels is not None and t is not None:
            m = labels[(labels.any_type == t) | (labels.label == t)]
            cls = str(m.cls.mode().iloc[0]) if len(m) else ""
        self.sp_qcdiam.setValue(self.ctx.settings.max_terminal_diam_um if "BC" in cls else 0)

    def center_on_root(self):
        labels = self.ctx.cave._labels
        try:
            rid = int(self.ed_root.text().strip())
        except ValueError:
            return
        row = labels[labels.root_id == rid] if labels is not None else pd.DataFrame()
        if len(row) == 0:
            try:
                rid2, frac = self.ctx.cave.current_root(rid)
                row = labels[labels.root_id == rid2]
                if len(row):
                    self.log(f"{rid} is outdated -> {rid2} ({frac:.0%} overlap)")
            except Exception as e:
                self.log(f"could not resolve {rid}: {e}")
        if len(row) == 0:
            QtWidgets.QMessageBox.information(self, "Not found", "This cell is not in the cell-type tables (no soma position).")
            return
        self.ed_cx.setText(f"{row.x.iloc[0]:.0f}"); self.ed_cy.setText(f"{row.y.iloc[0]:.0f}")

    # ------------------------------------------------------------------ show
    def _progress(self, i, n, msg):
        self.prog.setMaximum(n if n > 0 else 0); self.prog.setValue(i); self.prog_lbl.setText(msg)

    def _fail(self, msg):
        self.btn_show.setEnabled(True); self.btn_tables.setEnabled(True); self.btn_cancel.setEnabled(False)
        self.prog.setMaximum(1); self.prog.setValue(0); self.prog_lbl.setText("failed")
        self.log("ERROR: " + msg.splitlines()[0])
        QtWidgets.QMessageBox.critical(self, "Failed", msg[:3000])

    def show_cells(self):
        t = self.cb_type.currentData() or self.cb_type.currentText().split("  (")[0]
        try:
            center = (float(self.ed_cx.text()), float(self.ed_cy.text()))
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Centre", "Enter the centre as voxel x and y.")
            return
        s = self.ctx.settings
        labels = self.ctx.cave._labels
        cells = cells_of_type(labels, t, center, self.sp_radius.value(), s.voxel_nm, self.cb_source.currentText())
        if len(cells) == 0:
            QtWidgets.QMessageBox.information(self, "No cells", f"No '{t}' cells with soma within {self.sp_radius.value():.0f} µm.")
            return
        if len(cells) > self.sp_max.value():
            self.log(f"{len(cells)} cells found; showing the {self.sp_max.value()} nearest (raise 'max cells' for more)")
            cells = cells.head(self.sp_max.value())
        want_chat, faces, radius = self.chk_chat.isChecked(), self.sp_faces.value(), self.sp_radius.value()
        ctxcells = context_cells(labels, center, radius, s.voxel_nm) if self.chk_context.isChecked() else None
        self.cur_type, self.center, self.radius = t, center, radius

        def job(log, progress, cancelled):
            frame = None
            if want_chat:
                qp = query_points_for_disc(center, radius, s.voxel_nm, s.sac_spacing_um)
                frame = fit_frame_from_sacs(labels, qp, self.ctx.meshes, s, log=log, progress=progress, cancelled=cancelled,
                                            k_per_point=1, max_per_layer=max(s.max_sacs_per_layer, len(qp)))
            avail = self.ctx.meshes.ensure(cells.root_id, progress=progress, log=log, cancelled=cancelled)
            out = []
            for k, rid in enumerate(cells.root_id):
                if cancelled():
                    break
                if rid in avail:
                    out.append((rid,) + self.ctx.meshes.simplified(rid, faces))
                progress(k + 1, len(cells), "preparing meshes")
            return frame, out

        self.btn_show.setEnabled(False); self.btn_cancel.setEnabled(True)
        self.worker = run_in_thread(self, job, lambda res: self._draw(res, cells, ctxcells), self._fail, self._progress, self.log)

    def _draw(self, res, cells, ctxcells):
        frame, out = res
        self.frame, self.cells = frame, cells.copy()
        self.btn_show.setEnabled(True); self.btn_cancel.setEnabled(False)
        self.prog.setMaximum(1); self.prog.setValue(1); self.prog_lbl.setText(f"{len(out)} cells shown")
        s, v = self.ctx.settings, self.viewer
        T = frame.to_uvw if frame is not None else (lambda P: np.asarray(P, float))
        v.clear()
        info = cells.set_index("root_id")
        for k, (rid, vv, ff) in enumerate(out):
            r = info.loc[rid]
            lab = f"{self.cur_type} · {rid} · {r.label_source} · {r.dist_um:.0f} µm from centre"
            v.add_mesh(f"c:{rid}", T(vv), ff, PALETTE[k % len(PALETTE)], group="cells", label=lab)
        vox_nm = np.asarray(s.voxel_nm, float)
        if frame is not None:
            c_um = np.array([self.center[0], self.center[1], 0]) * vox_nm / 1000
            cu = frame.to_uvw(c_um[None, :])[0]
            grid = frame.surface_grid(cu[0] - self.radius, cu[0] + self.radius, cu[1] - self.radius, cu[1] + self.radius, n=120)
            v.add_surface("OFF", *grid["OFF"], color="#b5179e", group="surfaces", label="OFF ChAT band", opacity=0.25)
            v.add_surface("ON", *grid["ON"], color="#3a86ff", group="surfaces", label="ON ChAT band", opacity=0.25)
        if ctxcells is not None and len(ctxcells):
            pts = T(ctxcells[["x", "y", "z"]].to_numpy(float) * vox_nm / 1000)
            for cls, sub_idx in ctxcells.groupby(ctxcells.cls.fillna("unclassified")).indices.items():
                sub = ctxcells.iloc[sub_idx]
                labs = [f"{c} · {t} · {r}" for c, t, r in zip(sub.cls, sub.any_type.fillna("?"), sub.root_id)]
                v.add_points(f"ctx:{cls}", pts[sub_idx], CLASS_COLORS.get(cls, "#cccccc"), group="context", labels=labs, size=6)
        v.reset_view()
        cols = ["root_id", "label_source", "label", "auto_type", "dist_um", "x", "y", "z"]
        self.model.set(self.cells[[c for c in cols if c in self.cells]].round(1))
        self.btn_strat.setEnabled(frame is not None)
        self.btn_export.setEnabled(True)
        self.btn_ngl.setEnabled(True)
        self.log(f"showing {len(out)} {self.cur_type} cells within {self.radius:.0f} µm")

    def open_ngl(self):
        segs = {int(r): PALETTE[k % len(PALETTE)] for k, r in enumerate(self.cells.root_id)}
        som = self.cells[["x", "y", "z"]].dropna().to_numpy(float)
        layers = [dict(name=f"{self.cur_type} somata", color="#ffffff", points=som,
                       descriptions=[str(r) for r in self.cells.dropna(subset=["x"]).root_id])] if len(som) else []
        pos = (self.center[0], self.center[1], float(np.median(som[:, 2]))) if len(som) else None
        ngl_open(self, segs, layers, pos, layer_name=str(self.cur_type))

    def row_clicked(self, idx):
        rid = int(self.model.df().iloc[idx.row()]["root_id"])
        QtWidgets.QApplication.clipboard().setText(str(rid))
        self.viewer.focus(f"c:{rid}")
        self.viewer.highlight(f"c:{rid}")
        self.log(f"{rid} (copied to clipboard)")

    # ------------------------------------------------------------------ analysis
    def stratification(self):
        s, frame, cells = self.ctx.settings, self.frame, self.cells
        qc_d, qc_c = self.sp_qcdiam.value(), self.sp_qccov.value()

        def job(log, progress, cancelled):
            rows = []
            for k, rid in enumerate(cells.root_id):
                if cancelled():
                    break
                if self.ctx.meshes.has(rid):
                    rows.append({"root_id": rid, **features(frame.to_uvw(self.ctx.meshes.sample(rid, s.samples_per_um2_cell)), frame, s)})
                progress(k + 1, len(cells), "measuring stratification")
            f = pd.DataFrame(rows)
            if len(f):
                f["qc"] = qc_flags(f, s, max_diam_um=qc_d or None, min_covered=qc_c)
            return f

        run_in_thread(self, job, self._strat_done, self._fail, self._progress, self.log)

    def _strat_done(self, f):
        s = self.ctx.settings
        self.feat = f
        _, centres, _ = profile_bins(s)
        if len(f) == 0:
            self.log("stratification: no cells measured")
            return
        reasons = f.qc.value_counts().to_dict()
        ok = f if self.chk_allqc.isChecked() else f[f.qc == "ok"]
        self.log(f"QC: {reasons}" + ("" if len(f[f.qc == "ok"]) else "  — all cells failed QC; adjust the QC limits or tick 'Plot cells failing QC too'"))
        vox_nm = np.asarray(s.voxel_nm, float)
        cu = self.frame.to_uvw((np.array([self.center[0], self.center[1], 0]) * vox_nm / 1000)[None, :])[0]
        circ = Circle((cu[0], cu[1]), self.radius, fill=False, ls="--", color="k")
        som = self.cells[self.cells.root_id.isin(ok.root_id)][["x", "y", "z"]].dropna().to_numpy(float)
        somata_uv = self.frame.to_uvw(som * vox_nm / 1000)[:, :2] if len(som) else None
        fig = strat_figure(ok, centres, s, self.cur_type, square=circ, somata_uv=somata_uv)
        PlotDialog(fig, f"{self.cur_type}: stratification and mosaic", self).show()
        merged = self.cells.merge(f.drop(columns=["hull"], errors="ignore"), on="root_id", how="left")
        keep = ["root_id", "label_source", "dist_um", "qc", "median", "q10", "q90", "thickness", "term_diam_um", "x", "y", "z"]
        self.model.set(merged[[c for c in keep if c in merged]].round(3))
        self.cells_feat = merged
        self.log(f"stratification: {len(f[f.qc == 'ok'])} of {len(f)} cells pass QC "
                 f"(median depth {ok['median'].median():.2f}, diameter {ok.term_diam_um.median():.1f} µm)")

    def export(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Export to folder", self.ctx.settings.output_dir)
        if not d:
            return
        name = str(self.cur_type).replace(" ", "_").replace("/", "-")
        df = getattr(self, "cells_feat", None)
        (df if df is not None else self.cells).to_csv(os.path.join(d, f"{name}_cells.csv"), index=False)
        self.viewer.screenshot(os.path.join(d, f"{name}_3d.png"))
        self.log(f"exported to {d}")
