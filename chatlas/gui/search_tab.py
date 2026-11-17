"""Tab: stratification search — wide cells passing through a small square in a target ChAT layer."""
import os

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from qtpy import QtCore, QtWidgets

from ..core.search import run_search
from .common import PALETTE, PlotDialog, hrow, make_table, ngl_open, run_in_thread
from .viewer import Viewer3D

DEFAULT_CLASSES = ["AC", "not in tables", "unclassified"]


class SearchTab(QtWidgets.QWidget):
    def __init__(self, ctx, log, parent=None):
        super().__init__(parent)
        self.ctx, self.log = ctx, log
        self.R = None
        self._build()

    def _build(self):
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        QtWidgets.QHBoxLayout(self).addWidget(split)
        left = QtWidgets.QWidget()
        L = QtWidgets.QVBoxLayout(left)

        g1 = QtWidgets.QGroupBox("1 · Search square")
        f1 = QtWidgets.QFormLayout(g1)
        self.ed_cx, self.ed_cy = QtWidgets.QLineEdit("40000"), QtWidgets.QLineEdit("50000")
        self.sp_sq = QtWidgets.QDoubleSpinBox(); self.sp_sq.setRange(2, 500); self.sp_sq.setValue(30); self.sp_sq.setSuffix(" µm")
        f1.addRow("centre x (voxel)", self.ed_cx)
        f1.addRow("centre y (voxel)", self.ed_cy)
        f1.addRow("square side", self.sp_sq)
        L.addWidget(g1)

        g2 = QtWidgets.QGroupBox("2 · Target layer")
        f2 = QtWidgets.QFormLayout(g2)
        self.rb_ref = QtWidgets.QRadioButton("from a reference type"); self.rb_ref.setChecked(True)
        self.rb_man = QtWidgets.QRadioButton("manual ChAT range")
        self.ed_ref = QtWidgets.QComboBox(); self.ed_ref.setEditable(True); self.ed_ref.addItem("t3a")
        self.sp_nref = QtWidgets.QSpinBox(); self.sp_nref.setRange(1, 100); self.sp_nref.setValue(10)
        self.sp_lo = QtWidgets.QDoubleSpinBox(); self.sp_lo.setRange(-2, 3); self.sp_lo.setSingleStep(0.05); self.sp_lo.setValue(0.10)
        self.sp_hi = QtWidgets.QDoubleSpinBox(); self.sp_hi.setRange(-2, 3); self.sp_hi.setSingleStep(0.05); self.sp_hi.setValue(0.45)
        self.lbl_band = QtWidgets.QLabel("layer: –")
        f2.addRow(self.rb_ref)
        f2.addRow("reference type", self.ed_ref)
        f2.addRow("reference cells (nearest)", self.sp_nref)
        f2.addRow(self.rb_man)
        f2.addRow("ChAT from / to", hrow(self.sp_lo, self.sp_hi))
        f2.addRow(self.lbl_band)
        L.addWidget(g2)

        g3 = QtWidgets.QGroupBox("3 · Criteria")
        f3 = QtWidgets.QFormLayout(g3)
        self.sp_span = QtWidgets.QDoubleSpinBox(); self.sp_span.setRange(0, 5000); self.sp_span.setValue(150); self.sp_span.setSuffix(" µm")
        self.sp_frac = QtWidgets.QDoubleSpinBox(); self.sp_frac.setRange(0, 1); self.sp_frac.setSingleStep(0.05); self.sp_frac.setValue(0.4)
        self.sp_minpts = QtWidgets.QSpinBox(); self.sp_minpts.setRange(0, 100000); self.sp_minpts.setValue(200)
        self.sp_margin = QtWidgets.QDoubleSpinBox(); self.sp_margin.setRange(0, 1); self.sp_margin.setSingleStep(0.05); self.sp_margin.setValue(0.1)
        self.chk_whole = QtWidgets.QCheckBox("sample the whole IPL depth (slower; default: only the target layer)")
        self.sp_maxc = QtWidgets.QSpinBox(); self.sp_maxc.setRange(10, 20000); self.sp_maxc.setValue(400)
        self.lst_cls = QtWidgets.QListWidget(); self.lst_cls.setMaximumHeight(110)
        for c in ["AC", "not in tables", "unclassified", "RGC", "BC", "Glia", "HC"]:
            it = QtWidgets.QListWidgetItem(c)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if c in DEFAULT_CLASSES else QtCore.Qt.Unchecked)
            self.lst_cls.addItem(it)
        f3.addRow("min field span (wide-field)", self.sp_span)
        f3.addRow("min share of arbor in layer", self.sp_frac)
        f3.addRow("min size (L2 chunks / points)", self.sp_minpts)
        f3.addRow("depth margin around layer", self.sp_margin)
        f3.addRow(self.chk_whole)
        f3.addRow("max candidates measured", self.sp_maxc)
        f3.addRow("classes to consider", self.lst_cls)
        L.addWidget(g3)

        self.btn_go = QtWidgets.QPushButton("Search"); self.btn_go.setObjectName("primary")
        self.btn_cancel = QtWidgets.QPushButton("Cancel"); self.btn_cancel.setEnabled(False)
        self.prog = QtWidgets.QProgressBar(); self.prog_lbl = QtWidgets.QLabel("")
        self.chk_hits = QtWidgets.QCheckBox("table: hits only"); self.chk_hits.setChecked(True)
        self.btn_3d = QtWidgets.QPushButton("Show hits in 3D"); self.btn_3d.setEnabled(False)
        self.btn_prof = QtWidgets.QPushButton("Profiles…"); self.btn_prof.setEnabled(False)
        self.btn_export = QtWidgets.QPushButton("Export table…"); self.btn_export.setEnabled(False)
        self.btn_ngl = QtWidgets.QPushButton("Open hits in Neuroglancer"); self.btn_ngl.setEnabled(False)
        for w in (hrow(self.btn_go, self.btn_cancel), self.prog, self.prog_lbl, self.chk_hits,
                  hrow(self.btn_3d, self.btn_prof), self.btn_ngl, self.btn_export):
            L.addWidget(w)
        L.addStretch(1)
        scroll = QtWidgets.QScrollArea(); scroll.setWidget(left); scroll.setWidgetResizable(True); scroll.setMinimumWidth(360)
        split.addWidget(scroll)

        right = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.viewer = Viewer3D()
        right.addWidget(self.viewer)
        self.table, self.model = make_table()
        right.addWidget(self.table)
        right.setSizes([600, 300])
        split.addWidget(right)
        split.setSizes([370, 1100])

        self.btn_go.clicked.connect(self.search)
        self.btn_cancel.clicked.connect(lambda: getattr(self, "worker", None) and self.worker.cancel())
        self.chk_hits.toggled.connect(self._fill_table)
        self.btn_3d.clicked.connect(self.show_3d)
        self.btn_prof.clicked.connect(self.profiles)
        self.btn_export.clicked.connect(self.export)
        self.btn_ngl.clicked.connect(self.open_ngl)
        self.table.clicked.connect(self.row_clicked)

    # ------------------------------------------------------------------ run
    def _params(self):
        cls = [self.lst_cls.item(i).text() for i in range(self.lst_cls.count())
               if self.lst_cls.item(i).checkState() == QtCore.Qt.Checked]
        return dict(center_vox=(float(self.ed_cx.text()), float(self.ed_cy.text())), square_um=self.sp_sq.value(),
                    sac_radius_um=max(150.0, self.sp_sq.value()),
                    band_mode="reference" if self.rb_ref.isChecked() else "manual",
                    ref_type=self.ed_ref.currentText().strip(), n_ref=self.sp_nref.value(),
                    band=(self.sp_lo.value(), self.sp_hi.value()), depth_margin=self.sp_margin.value(),
                    whole_ipl=self.chk_whole.isChecked(), min_span_um=self.sp_span.value(), min_frac=self.sp_frac.value(),
                    min_points=self.sp_minpts.value(), classes=cls, max_candidates=self.sp_maxc.value())

    def search(self):
        try:
            p = self._params()
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Search", "Enter the centre as voxel x and y.")
            return
        self.ctx.cave.refresh_time()
        self.btn_go.setEnabled(False); self.btn_cancel.setEnabled(True)
        self.worker = run_in_thread(self, run_search, self._done, self._fail, self._progress, self.log,
                                    p, self.ctx.cave, self.ctx.meshes, self.ctx.settings)

    def _progress(self, i, n, msg):
        self.prog.setMaximum(n if n > 0 else 0); self.prog.setValue(i); self.prog_lbl.setText(msg)

    def _fail(self, msg):
        self.btn_go.setEnabled(True); self.btn_cancel.setEnabled(False)
        self.prog.setMaximum(1); self.prog.setValue(0); self.prog_lbl.setText("failed")
        self.log("ERROR: " + msg.splitlines()[0])
        QtWidgets.QMessageBox.critical(self, "Search failed", msg[:3000])

    def _done(self, R):
        self.R = R
        self.btn_go.setEnabled(True); self.btn_cancel.setEnabled(False)
        self.prog.setMaximum(1); self.prog.setValue(1)
        T = R.table
        self.prog_lbl.setText(f"{int(T.hit.sum())} hits among {len(T)} candidates")
        self.lbl_band.setText(f"layer: ChAT <b>{R.band[0]:.2f} – {R.band[1]:.2f}</b>")
        if self.rb_ref.isChecked():
            self.sp_lo.setValue(R.band[0]); self.sp_hi.setValue(R.band[1])
        self._fill_table()
        for b in (self.btn_3d, self.btn_prof, self.btn_ngl, self.btn_export):
            b.setEnabled(True)
        self._draw_context()

    def _fill_table(self):
        if self.R is None:
            return
        T = self.R.table
        if self.chk_hits.isChecked():
            T = T[T.hit]
        cols = ["root_id", "hit", "cls", "any_type", "field_span_um", "frac_in_band", "median", "peak", "q10", "q90",
                "covered", "n_points", "square_hits"]
        self.model.set(T[[c for c in cols if c in T]].round(3))

    # ------------------------------------------------------------------ views
    def _draw_context(self):
        R, v = self.R, self.viewer
        v.clear()
        sq = R.square_uv
        c = sq[:4].mean(axis=0)
        span = max(self.sp_span.value(), 150)
        grid = R.frame.surface_grid(c[0] - span, c[0] + span, c[1] - span, c[1] + span, n=120)
        v.add_surface("OFF", *grid["OFF"], color="#b5179e", group="surfaces", label="OFF ChAT band", opacity=0.22)
        v.add_surface("ON", *grid["ON"], color="#3a86ff", group="surfaces", label="ON ChAT band", opacity=0.22)
        for name, dd, col in (("layer top", R.band[0], "#ffd166"), ("layer bottom", R.band[1], "#ffd166")):
            off, on = R.frame.surf_off(sq[:, 0], sq[:, 1]), R.frame.surf_on(sq[:, 0], sq[:, 1])
            v.add_lines(name, np.column_stack([sq, off + dd * (on - off)]), col, group="square", width=4)
        v.reset_view()

    def show_3d(self):
        hits = self.R.table[self.R.table.hit]
        if len(hits) == 0:
            QtWidgets.QMessageBox.information(self, "No hits", "No cells meet the criteria. Relax them and search again.")
            return
        s = self.ctx.settings
        ids = list(hits.root_id[:60])

        def job(log, progress, cancelled):
            avail = self.ctx.meshes.ensure(ids, progress=progress, log=log, cancelled=cancelled)
            out = []
            for k, rid in enumerate(ids):
                if cancelled():
                    break
                if rid in avail:
                    out.append((rid,) + self.ctx.meshes.simplified(rid, max(s.faces_per_cell, 8000)))
                progress(k + 1, len(ids), "preparing meshes")
            return out

        self.btn_3d.setEnabled(False)
        run_in_thread(self, job, self._add_meshes, self._fail, self._progress, self.log)

    def _add_meshes(self, out):
        self.btn_3d.setEnabled(True)
        info = self.R.table.set_index("root_id")
        self.viewer.remove_group("hits")
        for k, (rid, vv, ff) in enumerate(out):
            r = info.loc[rid]
            lab = (f"{rid} · {r.cls} {'' if pd.isna(r.any_type) else r.any_type} · span {r.field_span_um:.0f} µm · "
                   f"{r.frac_in_band:.0%} in layer")
            self.viewer.add_mesh(f"h:{rid}", self.R.frame.to_uvw(vv), ff, PALETTE[k % len(PALETTE)], group="hits", label=lab)
        self.viewer.reset_view()
        self.log(f"showing {len(out)} hits in 3D")

    def open_ngl(self):
        T = self.R.table
        H = T[T.hit] if T.hit.any() else T.head(20)
        segs = {int(r): PALETTE[k % len(PALETTE)] for k, r in enumerate(H.root_id)}
        cx, cy = self.R.params["center_vox"]
        sq = self.R.square_uv
        vox = np.asarray(self.ctx.settings.voxel_nm, float)
        mid = (self.R.band[0] + self.R.band[1]) / 2
        off, on = self.R.frame.surf_off(sq[:, 0], sq[:, 1]), self.R.frame.surf_on(sq[:, 0], sq[:, 1])
        corners = self.R.frame.from_uvw(np.column_stack([sq, off + mid * (on - off)]))[:4] * 1000 / vox
        layers = [dict(name="search square", color="#ffd166", points=corners, descriptions=["search square"] * 4)]
        ngl_open(self, segs, layers, tuple(corners.mean(axis=0)), layer_name="search hits")

    def row_clicked(self, idx):
        rid = int(self.model.df().iloc[idx.row()]["root_id"])
        QtWidgets.QApplication.clipboard().setText(str(rid))
        if f"h:{rid}" in self.viewer.items:
            self.viewer.focus(f"h:{rid}"); self.viewer.highlight(f"h:{rid}")
        self.log(f"{rid} (copied to clipboard)")

    def profiles(self):
        R, s = self.R, self.ctx.settings
        T = R.table[R.table.hit] if R.table.hit.any() else R.table.head(10)
        edges = np.arange(s.ipl_range[0], s.ipl_range[1] + s.bin / 2, s.bin)
        centres = edges[:-1] + s.bin / 2
        fig = Figure(figsize=(14, 6.5), layout="constrained")
        ax = fig.add_subplot(1, 2, 1)
        ax.axhspan(R.band[0], R.band[1], color="#ffd166", alpha=0.35, label="target layer")
        for k, (_, r) in enumerate(T.head(20).iterrows()):
            if isinstance(r.get("profile"), np.ndarray):
                ax.plot(r.profile / s.bin, centres, color=PALETTE[k % len(PALETTE)], lw=1.5, label=str(r.root_id))
        for y in (0, 1):
            ax.axhline(y, color="k", ls="--", lw=0.8)
        ax.set_ylim(s.ipl_range[1], s.ipl_range[0]); ax.set_xlabel("membrane density"); ax.set_ylabel("ChAT depth (0 = OFF, 1 = ON)")
        ax.set_title("Stratification of hits" if R.table.hit.any() else "Top 10 candidates (no hits)")
        ax.legend(fontsize=7)
        ax2 = fig.add_subplot(1, 2, 2)
        A = R.table.dropna(subset=["field_span_um", "frac_in_band"])
        ax2.scatter(A.field_span_um, A.frac_in_band, s=14, color="0.6", label="candidates")
        H = A[A.hit]
        ax2.scatter(H.field_span_um, H.frac_in_band, s=40, color="#f72585", edgecolor="k", lw=0.4, label="hits")
        ax2.axvline(self.sp_span.value(), color="k", ls="--", lw=0.8); ax2.axhline(self.sp_frac.value(), color="k", ls="--", lw=0.8)
        ax2.set_xscale("symlog", linthresh=10); ax2.set_xlabel("field span (µm)"); ax2.set_ylabel("share of arbor in layer")
        ax2.set_title("All candidates: width vs layer share"); ax2.legend()
        PlotDialog(fig, "Stratification search", self).show()

    def export(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Export to folder", self.ctx.settings.output_dir)
        if not d:
            return
        T = self.R.table.drop(columns=["hull", "profile"], errors="ignore")
        cx, cy = self.R.params["center_vox"]
        T.to_csv(os.path.join(d, f"search_{int(cx)}_{int(cy)}_{self.R.params['square_um']:.0f}um.csv"), index=False)
        self.viewer.screenshot(os.path.join(d, f"search_{int(cx)}_{int(cy)}_3d.png"))
        self.log(f"exported to {d}")
