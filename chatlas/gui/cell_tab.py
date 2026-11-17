"""Tab: open cells by root ID."""
import re

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from qtpy import QtCore, QtGui, QtWidgets

from ..core.chat import fit_frame_from_sacs, query_points_for_disc
from ..core.search import arbor_features, mesh_points
from .common import PALETTE, PlotDialog, hrow, ngl_open, run_in_thread
from .viewer import Viewer3D


class CellTab(QtWidgets.QWidget):
    def __init__(self, ctx, log, parent=None):
        super().__init__(parent)
        self.ctx, self.log = ctx, log
        self.frame = None
        self.cells = {}            # rid -> dict(info, verts, faces, color, feat, P)
        self._build()

    def _build(self):
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        QtWidgets.QHBoxLayout(self).addWidget(split)
        left = QtWidgets.QWidget()
        L = QtWidgets.QVBoxLayout(left)

        g1 = QtWidgets.QGroupBox("Open cells")
        v1 = QtWidgets.QVBoxLayout(g1)
        self.ed_ids = QtWidgets.QPlainTextEdit()
        self.ed_ids.setPlaceholderText("root ID(s) — one or more, separated by commas, spaces or new lines")
        self.ed_ids.setMaximumHeight(80)
        self.chk_add = QtWidgets.QCheckBox("add to the current scene"); self.chk_add.setChecked(True)
        self.chk_chat = QtWidgets.QCheckBox("ChAT surfaces around the cells"); self.chk_chat.setChecked(True)
        self.sp_faces = QtWidgets.QSpinBox(); self.sp_faces.setRange(500, 500000); self.sp_faces.setSingleStep(5000); self.sp_faces.setValue(30000)
        self.btn_open = QtWidgets.QPushButton("Open"); self.btn_open.setObjectName("primary")
        self.btn_cancel = QtWidgets.QPushButton("Cancel"); self.btn_cancel.setEnabled(False)
        self.prog = QtWidgets.QProgressBar(); self.prog_lbl = QtWidgets.QLabel("")
        for w in (self.ed_ids, self.chk_add, self.chk_chat, hrow("faces per cell", self.sp_faces),
                  hrow(self.btn_open, self.btn_cancel), self.prog, self.prog_lbl):
            v1.addWidget(w)
        L.addWidget(g1)

        g2 = QtWidgets.QGroupBox("Cells in the scene")
        v2 = QtWidgets.QVBoxLayout(g2)
        self.lst = QtWidgets.QListWidget()
        self.lst.setMinimumHeight(150)
        b_rm, b_clear = QtWidgets.QPushButton("Remove selected"), QtWidgets.QPushButton("Clear all")
        self.btn_refit = QtWidgets.QPushButton("Refit ChAT surfaces to all cells")
        self.btn_prof = QtWidgets.QPushButton("Stratification profiles…")
        self.btn_centre = QtWidgets.QPushButton("Use selected soma as centre in other tabs")
        self.btn_ngl = QtWidgets.QPushButton("Open all in Neuroglancer")
        for w in (self.lst, hrow(b_rm, b_clear), self.btn_refit, self.btn_prof, self.btn_centre, self.btn_ngl):
            v2.addWidget(w)
        L.addWidget(g2)

        g3 = QtWidgets.QGroupBox("Selected cell")
        v3 = QtWidgets.QVBoxLayout(g3)
        self.info = QtWidgets.QTextBrowser(); self.info.setMinimumHeight(220)
        v3.addWidget(self.info)
        L.addWidget(g3)
        L.addStretch(1)
        scroll = QtWidgets.QScrollArea(); scroll.setWidget(left); scroll.setWidgetResizable(True); scroll.setMinimumWidth(360)
        split.addWidget(scroll)
        self.viewer = Viewer3D()
        split.addWidget(self.viewer)
        split.setSizes([370, 1100])

        self.btn_open.clicked.connect(self.open_cells)
        self.btn_cancel.clicked.connect(lambda: getattr(self, "worker", None) and self.worker.cancel())
        self.lst.itemChanged.connect(self._toggle)
        self.lst.currentItemChanged.connect(lambda cur, prev: self._show_info(cur))
        b_rm.clicked.connect(self._remove)
        b_clear.clicked.connect(self._clear)
        self.btn_refit.clicked.connect(lambda: self._run(list(self.cells), refit=True))
        self.btn_prof.clicked.connect(self.profiles)
        self.btn_centre.clicked.connect(self._use_centre)
        self.btn_ngl.clicked.connect(self.open_ngl)

    # ------------------------------------------------------------------ open
    def open_cells(self):
        ids = [int(x) for x in re.findall(r"\d{3,}", self.ed_ids.toPlainText())]
        if not ids:
            QtWidgets.QMessageBox.information(self, "Open", "Paste one or more root IDs.")
            return
        if not self.chk_add.isChecked():
            self._clear()
        self._run(ids, refit=self.frame is None or not self.chk_add.isChecked())

    def _run(self, ids, refit=False):
        s, cave, meshes = self.ctx.settings, self.ctx.cave, self.ctx.meshes
        want_chat, faces = self.chk_chat.isChecked(), self.sp_faces.value()
        known = dict(self.cells)
        frame0 = None if refit else self.frame

        def job(log, progress, cancelled):
            if cave._labels is None:
                progress(0, 0, "loading cell-type tables")
            labels = cave.labels()
            out, P_all = {}, []
            for k, rid in enumerate(ids):
                if cancelled():
                    break
                progress(k, len(ids), f"cell {k + 1}/{len(ids)}: resolving")
                if rid in known:
                    out[rid] = known[rid]; P_all.append(known[rid]["P"]); continue
                try:
                    cur, frac = cave.current_root(rid)
                except Exception as e:
                    log(f"{rid}: could not check the ID ({e}); using it as given")
                    cur, frac = rid, np.nan
                if cur != rid:
                    log(f"{rid} is outdated -> current {cur} ({frac:.0%} of the old cell)")
                row = labels[labels.root_id == cur]
                info = dict(requested=rid, root_id=cur, overlap=frac,
                            cls=row.cls.iloc[0] if len(row) else "not in tables",
                            manual=row.manual_type.iloc[0] if len(row) and pd.notna(row.manual_type.iloc[0]) else None,
                            machine=row.auto_type.iloc[0] if len(row) and pd.notna(row.auto_type.iloc[0]) else None,
                            soma=tuple(row[["x", "y", "z"]].iloc[0].round(0).astype(int)) if len(row) else None)
                progress(k, len(ids), f"cell {k + 1}/{len(ids)}: mesh")
                avail = meshes.ensure([cur], log=log)
                if cur not in avail:
                    log(f"{cur}: mesh not available")
                    continue
                vv, ff = meshes.simplified(cur, faces)
                try:
                    P, W = cave.l2_points(cur)
                except Exception:
                    P, W = mesh_points(meshes, cur, s)
                out[cur] = dict(info=info, verts=vv, faces=ff, P=P, W=W)
                P_all.append(P)
            frame = frame0
            if want_chat and P_all:
                if frame is None or refit:
                    allP = np.vstack(P_all)
                    vox = np.asarray(s.voxel_nm, float)
                    c = allP[:, :2].mean(axis=0) * 1000 / vox[:2]
                    span = float(np.ptp(allP[:, :2], axis=0).max())
                    qp = query_points_for_disc(c, min(max(span / 2, 100), 600), s.voxel_nm, s.sac_spacing_um)
                    frame = fit_frame_from_sacs(labels, qp, meshes, s, log=log, progress=progress, cancelled=cancelled,
                                                k_per_point=1, max_per_layer=max(s.max_sacs_per_layer, len(qp)))
                for rid, d in out.items():
                    if refit or "feat" not in d:
                        d["feat"] = arbor_features(d["P"], d["W"], frame, s)
            return frame, out

        self.btn_open.setEnabled(False); self.btn_cancel.setEnabled(True)
        self.worker = run_in_thread(self, job, self._done, self._fail, self._progress, self.log)

    def _progress(self, i, n, msg):
        self.prog.setMaximum(n if n > 0 else 0); self.prog.setValue(i); self.prog_lbl.setText(msg)

    def _fail(self, msg):
        self.btn_open.setEnabled(True); self.btn_cancel.setEnabled(False)
        self.prog.setMaximum(1); self.prog.setValue(0); self.prog_lbl.setText("failed")
        self.log("ERROR: " + msg.splitlines()[0])
        QtWidgets.QMessageBox.critical(self, "Open failed", msg[:3000])

    def _done(self, res):
        frame, out = res
        self.btn_open.setEnabled(True); self.btn_cancel.setEnabled(False)
        self.prog.setMaximum(1); self.prog.setValue(1); self.prog_lbl.setText(f"{len(out)} cell(s) ready")
        self.frame = frame
        for rid, d in out.items():
            d.setdefault("color", PALETTE[len(self.cells) % len(PALETTE)] if rid not in self.cells else self.cells[rid]["color"])
            self.cells[rid] = d
        self._redraw()
        self._fill_list(select=list(out)[-1] if out else None)

    # ------------------------------------------------------------------ scene
    def _T(self, P):
        return self.frame.to_uvw(P) if self.frame is not None else np.asarray(P, float)

    def _label(self, d):
        i, f = d["info"], d.get("feat", {})
        t = i["manual"] or (f"machine: {i['machine']}" if i["machine"] else "no label")
        extra = f" · span {f['field_span_um']:.0f} µm · ChAT median {f['median']:.2f}" if "median" in f else ""
        return f"{i['root_id']} · {i['cls']} · {t}{extra}"

    def _redraw(self):
        v = self.viewer
        v.clear()
        allv = []
        for rid, d in self.cells.items():
            vv = self._T(d["verts"])
            allv.append(vv)
            v.add_mesh(f"c:{rid}", vv, d["faces"], d["color"], group=f"c:{rid}", label=self._label(d))
        if self.frame is not None and allv:
            A = np.vstack(allv)
            pad = 20
            grid = self.frame.surface_grid(A[:, 0].min() - pad, A[:, 0].max() + pad, A[:, 1].min() - pad, A[:, 1].max() + pad, n=140)
            v.add_surface("OFF", *grid["OFF"], color="#b5179e", group="surfaces", label="OFF ChAT band", opacity=0.22)
            v.add_surface("ON", *grid["ON"], color="#3a86ff", group="surfaces", label="ON ChAT band", opacity=0.22)
        v.reset_view()

    def _fill_list(self, select=None):
        self.lst.blockSignals(True)
        self.lst.clear()
        for rid, d in self.cells.items():
            i = d["info"]
            t = i["manual"] or (f"({i['machine']})" if i["machine"] else "")
            it = QtWidgets.QListWidgetItem(f"{rid}   {i['cls']}  {t}")
            it.setData(QtCore.Qt.UserRole, rid)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked)
            it.setForeground(QtGui.QBrush(QtGui.QColor(d["color"])))
            self.lst.addItem(it)
            if rid == select:
                self.lst.setCurrentItem(it)
        self.lst.blockSignals(False)
        self._show_info(self.lst.currentItem())

    def _toggle(self, item):
        self.viewer.set_group_visible(f"c:{item.data(QtCore.Qt.UserRole)}", item.checkState() == QtCore.Qt.Checked)

    def _remove(self):
        it = self.lst.currentItem()
        if it:
            rid = it.data(QtCore.Qt.UserRole)
            self.cells.pop(rid, None)
            self.viewer.remove_group(f"c:{rid}")
            self._fill_list()

    def _clear(self):
        self.cells.clear()
        self.frame = None
        self.viewer.clear()
        self._fill_list()

    def _show_info(self, item):
        if item is None:
            self.info.setHtml("")
            return
        rid = item.data(QtCore.Qt.UserRole)
        d = self.cells.get(rid)
        if not d:
            return
        i, f = d["info"], d.get("feat", {})
        QtWidgets.QApplication.clipboard().setText(str(rid))
        rows = [("root ID", f"<b>{rid}</b> (copied)")]
        if i["requested"] != rid:
            rows.append(("requested", f"{i['requested']} → current ({i['overlap']:.0%} overlap)"))
        rows += [("class", i["cls"]), ("manual type", i["manual"] or "–"), ("machine type", i["machine"] or "–"),
                 ("soma (voxel)", ", ".join(map(str, i["soma"])) if i["soma"] else "– (not in tables)")]
        if f:
            if "field_span_um" in f:
                rows.append(("field span / diameter", f"{f['field_span_um']:.0f} µm / {f.get('field_diam_um', np.nan):.0f} µm"))
            if "median" in f:
                rows.append(("ChAT depth", f"median {f['median']:.2f} · peak {f['peak']:.2f} · 10–90% {f['q10']:.2f}–{f['q90']:.2f}"))
            rows.append(("inside ChAT coverage", f"{f.get('covered', np.nan):.0%} of IPL membrane"))
        self.info.setHtml("<table cellspacing=4>" + "".join(f"<tr><td style='color:#7f8db3'>{a}</td><td>{b}</td></tr>" for a, b in rows) + "</table>")
        self.viewer.focus(f"c:{rid}")

    def _use_centre(self):
        it = self.lst.currentItem()
        if not it:
            return
        d = self.cells[it.data(QtCore.Qt.UserRole)]
        soma = d["info"]["soma"]
        if soma is None:
            P = d["P"]
            vox = np.asarray(self.ctx.settings.voxel_nm, float)
            soma = tuple((P.mean(axis=0) * 1000 / vox).round(0).astype(int))
        win = self.window()
        for tab in (getattr(win, "celltypes", None), getattr(win, "search", None)):
            if tab is not None:
                tab.ed_cx.setText(str(soma[0])); tab.ed_cy.setText(str(soma[1]))
        self.log(f"centre set to voxel {soma[0]}, {soma[1]} in the Cell types and Search tabs")

    def open_ngl(self):
        segs = {int(r): d["color"] for r, d in self.cells.items()}
        som = [d["info"]["soma"] for d in self.cells.values() if d["info"]["soma"]]
        pos = np.mean(np.asarray(som, float), axis=0) if som else None
        ngl_open(self, segs, None, pos, layer_name="cells")

    def profiles(self):
        s = self.ctx.settings
        edges = np.arange(s.ipl_range[0], s.ipl_range[1] + s.bin / 2, s.bin)
        centres = edges[:-1] + s.bin / 2
        fig = Figure(figsize=(7, 7), layout="constrained")
        ax = fig.add_subplot(1, 1, 1)
        n = 0
        for rid, d in self.cells.items():
            prof = d.get("feat", {}).get("profile")
            if isinstance(prof, np.ndarray):
                ax.plot(prof / s.bin, centres, color=d["color"], lw=2, label=self._label(d)[:60]); n += 1
        for y in (0, 1):
            ax.axhline(y, color="k", ls="--", lw=0.8)
        ax.set_ylim(s.ipl_range[1], s.ipl_range[0]); ax.set_xlabel("membrane density"); ax.set_ylabel("ChAT depth (0 = OFF, 1 = ON)")
        ax.set_title("Stratification" if n else "No profiles (ChAT surfaces off?)"); ax.legend(fontsize=7)
        PlotDialog(fig, "Stratification of opened cells", self).show()
