"""Tab 3: connection, token and folders."""
import webbrowser

from qtpy import QtCore, QtGui, QtWidgets

from .common import hrow, run_in_thread


class SettingsTab(QtWidgets.QWidget):
    def __init__(self, ctx, log, parent=None):
        super().__init__(parent)
        self.ctx, self.log = ctx, log
        s = ctx.settings
        lay = QtWidgets.QVBoxLayout(self)

        g = QtWidgets.QGroupBox("Dataset")
        f = QtWidgets.QFormLayout(g)
        self.ed_ds = QtWidgets.QLineEdit(s.datastack)
        self.ed_server = QtWidgets.QLineEdit(s.server)
        self.ed_man = QtWidgets.QLineEdit(s.labels_manual)
        self.ed_auto = QtWidgets.QLineEdit(s.labels_auto)
        self.ed_vox = QtWidgets.QLineEdit(", ".join(f"{v:g}" for v in s.voxel_nm))
        f.addRow("datastack", self.ed_ds)
        f.addRow("server", self.ed_server)
        f.addRow("manual cell-type table", self.ed_man)
        f.addRow("machine cell-type table", self.ed_auto)
        f.addRow("voxel size (nm) of table / Neuroglancer coordinates", self.ed_vox)
        lay.addWidget(g)

        g2 = QtWidgets.QGroupBox("CAVE token")
        v2 = QtWidgets.QVBoxLayout(g2)
        v2.addWidget(QtWidgets.QLabel("1. Open the token page and log in with the Google account you use in Neuroglancer.\n"
                                      "2. Copy the token, paste it below and save. It is stored in ~/.cloudvolume/secrets."))
        self.btn_page = QtWidgets.QPushButton("Open token page")
        self.ed_token = QtWidgets.QLineEdit(); self.ed_token.setEchoMode(QtWidgets.QLineEdit.Password)
        self.ed_token.setPlaceholderText("paste token here")
        self.btn_token = QtWidgets.QPushButton("Save token")
        self.btn_test = QtWidgets.QPushButton("Test connection")
        self.lbl_conn = QtWidgets.QLabel("")
        for w in (hrow(self.btn_page, None), hrow(self.ed_token, self.btn_token), hrow(self.btn_test, self.lbl_conn, None)):
            v2.addWidget(w)
        lay.addWidget(g2)

        g3 = QtWidgets.QGroupBox("Folders and performance")
        f3 = QtWidgets.QFormLayout(g3)
        self.ed_cache = QtWidgets.QLineEdit(s.mesh_cache)
        b_cache = QtWidgets.QPushButton("…")
        self.ed_out = QtWidgets.QLineEdit(s.output_dir)
        b_out = QtWidgets.QPushButton("…")
        self.sp_threads = QtWidgets.QSpinBox(); self.sp_threads.setRange(1, 16); self.sp_threads.setValue(s.threads)
        self.sp_faces = QtWidgets.QSpinBox(); self.sp_faces.setRange(200, 200000); self.sp_faces.setValue(s.faces_per_cell)
        self.sp_target = QtWidgets.QSpinBox(); self.sp_target.setRange(1000, 1000000); self.sp_target.setValue(s.faces_target)
        self.sp_sacs = QtWidgets.QSpinBox(); self.sp_sacs.setRange(2, 200); self.sp_sacs.setValue(s.max_sacs_per_layer)
        self.sp_smooth = QtWidgets.QDoubleSpinBox(); self.sp_smooth.setRange(2, 50); self.sp_smooth.setValue(s.smooth_um)
        self.sp_spacing = QtWidgets.QDoubleSpinBox(); self.sp_spacing.setRange(40, 400); self.sp_spacing.setSingleStep(20)
        self.sp_spacing.setSuffix(" µm"); self.sp_spacing.setValue(getattr(s, "sac_spacing_um", 120))
        self.sp_spacing.setToolTip("Regions are covered with a grid of this spacing; the nearest ON and OFF SAC to each grid point are used.\n"
                                   "Larger = fewer SACs to download (a SAC arbor is ~250-300 µm across, so up to ~200 µm usually still covers).")
        self.sp_perpt = QtWidgets.QSpinBox(); self.sp_perpt.setRange(1, 5); self.sp_perpt.setValue(s.sacs_per_point)
        self.sp_perpt.setToolTip("Synapse partners tab: nearest ON / OFF SACs taken per annotation point.")
        f3.addRow("mesh cache (reuse an existing mesh_cache folder here)", hrow(self.ed_cache, b_cache))
        f3.addRow("output folder", hrow(self.ed_out, b_out))
        f3.addRow("parallel downloads", self.sp_threads)
        f3.addRow("faces per cell in 3D", self.sp_faces)
        f3.addRow("faces for the target cell", self.sp_target)
        f3.addRow("max SACs per ChAT layer", self.sp_sacs)
        f3.addRow("ChAT surface smoothing (µm)", self.sp_smooth)
        f3.addRow("SAC grid spacing (regions)", self.sp_spacing)
        f3.addRow("SACs per annotation (partners)", self.sp_perpt)
        lay.addWidget(g3)
        g4 = QtWidgets.QGroupBox("Mesh cache")
        v4 = QtWidgets.QVBoxLayout(g4)
        self.lbl_cache = QtWidgets.QLabel("")
        self.sp_limit = QtWidgets.QDoubleSpinBox(); self.sp_limit.setRange(0, 10000); self.sp_limit.setDecimals(0)
        self.sp_limit.setSuffix(" GB"); self.sp_limit.setSpecialValueText("unlimited")
        self.sp_limit.setValue(getattr(s, "cache_max_gb", 20))
        self.sp_days = QtWidgets.QSpinBox(); self.sp_days.setRange(1, 3650); self.sp_days.setValue(30); self.sp_days.setSuffix(" days")
        b_refresh = QtWidgets.QPushButton("Refresh")
        b_dec = QtWidgets.QPushButton("Clear simplified copies")
        b_old = QtWidgets.QPushButton("Clear meshes not used for")
        b_all = QtWidgets.QPushButton("Clear entire cache")
        b_open = QtWidgets.QPushButton("Open folder")
        v4.addWidget(hrow(self.lbl_cache, None, b_refresh, b_open))
        v4.addWidget(hrow("size limit (least-recently-used meshes are removed above it):", self.sp_limit, None))
        v4.addWidget(hrow(b_dec, b_old, self.sp_days, b_all, None))
        lay.addWidget(g4)
        b_refresh.clicked.connect(self.refresh_cache)
        b_dec.clicked.connect(lambda: self._clear(simplified_only=True))
        b_old.clicked.connect(lambda: self._clear(older_than_days=self.sp_days.value()))
        b_all.clicked.connect(lambda: self._clear(confirm="Delete ALL cached meshes? They will be downloaded again when needed."))
        b_open.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.ctx.settings.mesh_cache)))

        self.btn_save = QtWidgets.QPushButton("Save settings"); self.btn_save.setObjectName("primary")
        lay.addWidget(hrow(self.btn_save, None))
        lay.addStretch(1)
        self.refresh_cache()

        self.btn_page.clicked.connect(lambda: webbrowser.open(self.ed_server.text().rstrip("/") + "/auth/api/v1/create_token"))
        self.btn_token.clicked.connect(self.save_token)
        self.btn_test.clicked.connect(self.test)
        b_cache.clicked.connect(lambda: self._dir(self.ed_cache))
        b_out.clicked.connect(lambda: self._dir(self.ed_out))
        self.btn_save.clicked.connect(self.save)

    def refresh_cache(self):
        st = self.ctx.meshes.stats()
        self.lbl_cache.setText(f"<b>{st['bytes_total'] / 1e9:.2f} GB</b> — {st['n_meshes']} meshes "
                               f"({st['bytes_meshes'] / 1e9:.2f} GB) + {st['n_simplified']} simplified copies "
                               f"({st['bytes_simplified'] / 1e9:.2f} GB)")

    def _clear(self, simplified_only=False, older_than_days=None, confirm=None):
        if confirm and QtWidgets.QMessageBox.question(self, "Clear cache", confirm) != QtWidgets.QMessageBox.Yes:
            return
        n, b = self.ctx.meshes.clear(simplified_only=simplified_only, older_than_days=older_than_days)
        self.log(f"mesh cache: removed {n} files ({b / 1e9:.2f} GB)")
        self.refresh_cache()

    def _dir(self, ed):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder", ed.text())
        if d:
            ed.setText(d)

    def save(self):
        s = self.ctx.settings
        s.datastack, s.server = self.ed_ds.text().strip(), self.ed_server.text().strip()
        s.labels_manual, s.labels_auto = self.ed_man.text().strip(), self.ed_auto.text().strip()
        try:
            s.voxel_nm = tuple(float(x) for x in self.ed_vox.text().split(","))
        except ValueError:
            pass
        s.mesh_cache, s.output_dir = self.ed_cache.text().strip(), self.ed_out.text().strip()
        s.threads, s.faces_per_cell, s.faces_target = self.sp_threads.value(), self.sp_faces.value(), self.sp_target.value()
        s.max_sacs_per_layer, s.smooth_um = self.sp_sacs.value(), self.sp_smooth.value()
        s.sac_spacing_um, s.sacs_per_point = self.sp_spacing.value(), self.sp_perpt.value()
        s.cache_max_gb = self.sp_limit.value()
        s.save()
        self.ctx.reset()
        self.ctx.meshes.enforce_limit(log=self.log)
        self.refresh_cache()
        self.log("settings saved")

    def save_token(self):
        tok = self.ed_token.text().strip()
        if not tok:
            return
        try:
            from caveclient import CAVEclient
            CAVEclient(server_address=self.ed_server.text().strip()).auth.save_token(token=tok, overwrite=True)
            self.ed_token.clear()
            self.ctx.reset()
            self.log("token saved")
            QtWidgets.QMessageBox.information(self, "Token", "Token saved.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Token", str(e))

    def test(self):
        self.lbl_conn.setText("testing…")

        def job(log, progress, cancelled):
            c = self.ctx.cave.client
            seg = c.info.segmentation_source()
            return seg

        run_in_thread(self, job, lambda seg: self.lbl_conn.setText(f"✓ connected — {seg}"),
                      lambda m: self.lbl_conn.setText("✗ " + m.splitlines()[0][:150]))
