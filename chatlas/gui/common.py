"""Shared GUI pieces: background worker, pandas table, plot dialog, colours."""
import traceback

import numpy as np
import pandas as pd
from qtpy import QtCore, QtGui, QtWidgets

PALETTE = ["#4cc9f0", "#f72585", "#ffb703", "#80ed99", "#b5179e", "#fb8500", "#3a86ff", "#e9c46a",
           "#06d6a0", "#ef476f", "#a0c4ff", "#ffd6a5", "#9b5de5", "#00bbf9", "#f15bb5", "#c0fdff",
           "#caffbf", "#ff9f1c", "#8ecae6", "#d0f4de"]
CLASS_COLORS = {"BC": "#ff9f1c", "BC (predicted)": "#ffd166", "AC": "#4cc9f0", "RGC": "#80ed99",
                "not in tables": "#9aa5b1", "unknown": "#9aa5b1"}


def type_colors(types):
    return {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(types)}


class Worker(QtCore.QObject):
    progress = QtCore.Signal(int, int, str)
    log = QtCore.Signal(str)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self._cancel = False

    def cancel(self):
        self._cancel = True

    @QtCore.Slot()
    def run(self):
        try:
            res = self.fn(*self.args, log=self.log.emit, progress=lambda i, n, msg="": self.progress.emit(int(i), int(n), msg),
                          cancelled=lambda: self._cancel, **self.kwargs)
            self.finished.emit(res)
        except Exception as e:
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


class _Relay(QtCore.QObject):
    """Lives in the GUI thread, so worker signals are delivered (queued) to the GUI thread."""

    def __init__(self, parent, on_done, on_fail, on_progress, on_log):
        super().__init__(parent)
        self.cb = (on_done, on_fail, on_progress, on_log)

    @QtCore.Slot(object)
    def done(self, res):
        self.cb[0](res)

    @QtCore.Slot(str)
    def fail(self, msg):
        self.cb[1](msg)

    @QtCore.Slot(int, int, str)
    def prog(self, i, n, msg):
        if self.cb[2]:
            self.cb[2](i, n, msg)

    @QtCore.Slot(str)
    def log(self, msg):
        if self.cb[3]:
            self.cb[3](msg)


def run_in_thread(owner, fn, on_done, on_fail=None, on_progress=None, on_log=None, *args, **kwargs):
    """Run fn(*args, log=, progress=, cancelled=) in a QThread; callbacks run in the GUI thread."""
    on_fail = on_fail or (lambda m: QtWidgets.QMessageBox.critical(owner, "Error", m[:3000]))
    relay = _Relay(owner, on_done, on_fail, on_progress, on_log)
    thread = QtCore.QThread(owner)
    worker = Worker(fn, *args, **kwargs)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    Q = QtCore.Qt.QueuedConnection
    worker.finished.connect(relay.done, Q)
    worker.failed.connect(relay.fail, Q)
    worker.progress.connect(relay.prog, Q)
    worker.log.connect(relay.log, Q)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    jobs = getattr(owner, "_jobs", [])
    jobs.append((thread, worker, relay))
    owner._jobs = jobs

    def cleanup():
        try:
            owner._jobs.remove((thread, worker, relay))
        except ValueError:
            pass
        relay.deleteLater()
        worker.deleteLater()
        thread.deleteLater()
    thread.finished.connect(cleanup)
    thread.start()
    return worker


class PandasModel(QtCore.QAbstractTableModel):
    def __init__(self, df=None):
        super().__init__()
        self._df = df if df is not None else pd.DataFrame()

    def set(self, df):
        self.beginResetModel()
        self._df = df.reset_index(drop=True)
        self.endResetModel()

    def df(self):
        return self._df

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._df)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return self._df.shape[1]

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        v = self._df.iat[index.row(), index.column()]
        if role == QtCore.Qt.DisplayRole:
            if isinstance(v, (float, np.floating)):
                return "" if np.isnan(v) else f"{v:.3g}" if abs(v) < 1e5 else f"{v:.0f}"
            if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
                return ""
            return str(v)
        if role == QtCore.Qt.UserRole:
            return v
        return None

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole:
            return str(self._df.columns[section]) if orientation == QtCore.Qt.Horizontal else str(section + 1)
        return None

    def sort(self, column, order):
        if self._df.empty:
            return
        col = self._df.columns[column]
        self.beginResetModel()
        self._df = self._df.sort_values(col, ascending=order == QtCore.Qt.AscendingOrder, kind="mergesort").reset_index(drop=True)
        self.endResetModel()


def make_table():
    view = QtWidgets.QTableView()
    model = PandasModel()
    view.setModel(model)
    view.setSortingEnabled(True)
    view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
    view.horizontalHeader().setStretchLastSection(True)
    view.verticalHeader().setVisible(False)
    view.setAlternatingRowColors(True)
    view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

    def menu(pos):
        idx = view.indexAt(pos)
        if not idx.isValid():
            return
        m = QtWidgets.QMenu(view)
        a1 = m.addAction("Copy cell")
        a2 = m.addAction("Copy root ID")
        act = m.exec_(view.viewport().mapToGlobal(pos)) if hasattr(m, "exec_") else m.exec(view.viewport().mapToGlobal(pos))
        df = model.df()
        if act == a1:
            QtWidgets.QApplication.clipboard().setText(str(df.iat[idx.row(), idx.column()]))
        elif act == a2 and "root_id" in df:
            QtWidgets.QApplication.clipboard().setText(str(df.iloc[idx.row()]["root_id"]))
    view.customContextMenuRequested.connect(menu)
    return view, model


class PlotDialog(QtWidgets.QDialog):
    """A resizable window with a matplotlib figure and a save button."""

    def __init__(self, fig, title, parent=None):
        super().__init__(parent)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
        self.setWindowTitle(title)
        self.resize(1200, 850)
        lay = QtWidgets.QVBoxLayout(self)
        canvas = FigureCanvasQTAgg(fig)
        lay.addWidget(NavigationToolbar2QT(canvas, self))
        lay.addWidget(canvas)
        self.fig = fig


def hrow(*widgets):
    w = QtWidgets.QWidget()
    l = QtWidgets.QHBoxLayout(w)
    l.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        if isinstance(x, str):
            l.addWidget(QtWidgets.QLabel(x))
        elif x is None:
            l.addStretch(1)
        else:
            l.addWidget(x)
    return w

def ngl_open(owner, segments, point_layers=None, position=None, layer_name="cells"):
    """Build a Neuroglancer state for these cells (root_id -> colour) and open it in the browser."""
    from ..core.ngl import build_state, image_source, open_state, segmentation_source
    if not segments:
        QtWidgets.QMessageBox.information(owner, "Neuroglancer", "Nothing to show yet.")
        return
    ctx = owner.ctx
    try:
        state = build_state(segmentation_source(ctx.cave), image_source(ctx.cave), segments, ctx.settings.voxel_nm,
                            point_layers=point_layers, position=position, layer_name=layer_name)
        url = open_state(ctx.cave, state, log=owner.log)
        QtWidgets.QApplication.clipboard().setText(url)
        owner.log(f"opened {len(segments)} cells in Neuroglancer (link copied): {url[:120]}{'…' if len(url) > 120 else ''}")
    except Exception as e:
        QtWidgets.QMessageBox.critical(owner, "Neuroglancer", str(e)[:2000])
