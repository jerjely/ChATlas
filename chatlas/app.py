"""ChATlas main window."""
import os
import sys

os.environ.setdefault("QT_API", "pyside6")

from qtpy import QtCore, QtGui, QtWidgets

from . import __app_name__, __version__
from .core.cave import Cave
from .core.config import Settings
from .core.meshes import MeshStore

ASSETS = os.path.join(os.path.dirname(__file__), "assets")

STYLE = """
QWidget { background: #0f1424; color: #dfe7f5; font-size: 12px; }
QGroupBox { border: 1px solid #2a3558; border-radius: 8px; margin-top: 14px; padding: 8px 6px 6px 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #4cc9f0; font-weight: 600; }
QPushButton { background: #1d2744; border: 1px solid #33406b; border-radius: 6px; padding: 6px 10px; }
QPushButton:hover { background: #26335a; border-color: #4cc9f0; }
QPushButton:disabled { color: #5d6785; border-color: #232c48; }
QPushButton#primary { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #b5179e, stop:1 #3a86ff); border: none; color: white; font-weight: 600; }
QPushButton#primary:disabled { background: #2a3150; color: #6c7594; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QListWidget, QTableView {
    background: #141b31; border: 1px solid #2a3558; border-radius: 5px; padding: 3px; selection-background-color: #3a86ff; }
QTableView { alternate-background-color: #172041; gridline-color: #232c48; }
QHeaderView::section { background: #1a2340; color: #9fb3d9; border: none; padding: 4px; }
QTabWidget::pane { border: 1px solid #2a3558; border-radius: 8px; top: -1px; }
QTabBar::tab { background: #141b31; padding: 8px 18px; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; color: #9fb3d9; }
QTabBar::tab:selected { background: #1f2a4a; color: white; border-bottom: 2px solid #f72585; }
QProgressBar { border: 1px solid #2a3558; border-radius: 5px; text-align: center; height: 14px; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f72585, stop:1 #4cc9f0); border-radius: 4px; }
QScrollArea { border: none; }
QSplitter::handle { background: #1a2340; }
QToolTip { background: #141b31; color: #e8f1ff; border: 1px solid #4cc9f0; }
"""


class Ctx:
    """Shared state: settings, CAVE access, mesh cache."""

    def __init__(self):
        self.settings = Settings.load()
        self.reset()

    def reset(self):
        labels = getattr(getattr(self, "cave", None), "_labels", None)
        self.cave = Cave(self.settings)
        self.cave._labels = labels if labels is not None and getattr(self, "_keep_labels", True) else None
        self.meshes = MeshStore(self.settings, self.cave)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        from .gui.celltype_tab import CellTypeTab
        from .gui.partners_tab import PartnersTab
        from .gui.search_tab import SearchTab
        from .gui.cell_tab import CellTab
        from .gui.settings_tab import SettingsTab
        self.ctx = Ctx()
        self.setWindowTitle(f"{__app_name__} {__version__} — retina connectome explorer")
        self.setWindowIcon(QtGui.QIcon(os.path.join(ASSETS, "chatlas.ico" if sys.platform == "win32" else "logo_256.png")))
        self.resize(1500, 950)

        central = QtWidgets.QWidget()
        V = QtWidgets.QVBoxLayout(central)
        V.setContentsMargins(10, 8, 10, 8)
        V.addWidget(self._header())

        self.logbox = QtWidgets.QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMaximumBlockCount(5000)

        tabs = QtWidgets.QTabWidget()
        self.partners = PartnersTab(self.ctx, self.log)
        self.celltypes = CellTypeTab(self.ctx, self.log)
        self.search = SearchTab(self.ctx, self.log)
        self.cellview = CellTab(self.ctx, self.log)
        self.settings_tab = SettingsTab(self.ctx, self.log)
        tabs.addTab(self.partners, "  Synapse partners  ")
        tabs.addTab(self.celltypes, "  Cell types  ")
        tabs.addTab(self.search, "  Stratification search  ")
        tabs.addTab(self.cellview, "  Cell viewer  ")
        tabs.addTab(self.settings_tab, "  Settings  ")
        split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        split.addWidget(tabs)
        split.addWidget(self.logbox)
        split.setSizes([820, 120])
        V.addWidget(split)
        self.setCentralWidget(central)
        self.log(f"{__app_name__} {__version__} — data folder: {os.path.dirname(self.ctx.settings.mesh_cache)}")
        self.log(f"mesh cache: {self.ctx.settings.mesh_cache}")

    def _header(self):
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        h.setContentsMargins(4, 0, 4, 0)
        logo = QtWidgets.QLabel()
        pm = QtGui.QPixmap(os.path.join(ASSETS, "logo_256.png")).scaled(46, 46, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        logo.setPixmap(pm)
        title = QtWidgets.QLabel(f"<span style='font-size:22px; font-weight:700; color:#ffffff;'>Ch<span style='color:#f72585'>AT</span>las</span>"
                                 f"<span style='font-size:12px; color:#7f8db3;'>&nbsp;&nbsp;stratification · partners · mosaics · search</span>")
        h.addWidget(logo)
        h.addWidget(title)
        h.addStretch(1)
        return w

    def log(self, msg):
        self.logbox.appendPlainText(str(msg))
        self.logbox.verticalScrollBar().setValue(self.logbox.verticalScrollBar().maximum())


def _install_crash_log():
    """Python errors and native crashes are written to ~/ChATlas/chatlas.log."""
    import faulthandler, logging, traceback
    from .core.config import DATA_DIR
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "chatlas.log")
    f = open(path, "a", buffering=1, encoding="utf-8")
    import datetime
    f.write(f"\n===== ChATlas {__version__} started {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
    faulthandler.enable(file=f, all_threads=True)
    if sys.stdout is None:            # pythonw: no console
        sys.stdout = f
    if sys.stderr is None:
        sys.stderr = f

    def hook(et, ev, tb):
        f.write("".join(traceback.format_exception(et, ev, tb)))
        f.flush()
        try:
            QtWidgets.QMessageBox.critical(None, "ChATlas error", f"{ev}\n\nDetails were written to {path}")
        except Exception:
            pass
    sys.excepthook = hook
    return f


def main():
    _crash_log = _install_crash_log()
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ChATlas.app")
        except Exception:
            pass
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QtGui.QIcon(os.path.join(ASSETS, "chatlas.ico" if sys.platform == "win32" else "logo_256.png")))
    splash = QtWidgets.QSplashScreen(QtGui.QPixmap(os.path.join(ASSETS, "logo_256.png")))
    splash.show()
    app.processEvents()
    win = MainWindow()
    win.show()
    splash.finish(win)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
