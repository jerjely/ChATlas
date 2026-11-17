"""3D viewer (VTK via pyvistaqt) with hover labels, groups and point picking."""
import time

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from qtpy import QtCore, QtGui, QtWidgets
from scipy.spatial import cKDTree

try:
    from vtkmodules.vtkRenderingCore import vtkCellPicker
except Exception:                                   # older VTK
    from vtk import vtkCellPicker


def faces_to_pv(faces):
    f = np.asarray(faces, dtype=np.int64)
    return np.hstack([np.full((len(f), 1), 3, dtype=np.int64), f]).ravel()


class Viewer3D(QtWidgets.QWidget):
    picked = QtCore.Signal(object)          # world position (np.array) of a pick

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.plotter = QtInteractor(self)
        lay.addWidget(self.plotter.interactor)
        self.plotter.set_background("#0f1424", top="#1f2a44")
        self.plotter.add_axes(color="white")
        self.items = {}            # key -> dict(actor, group, labels, tree, color)
        self.groups = {}           # group -> set(keys)
        self._last_hover = 0
        self._pick_keys = None
        self._pick_marker = None
        self._cell_picker = vtkCellPicker()          # software ray picking (safe on all graphics drivers)
        self._cell_picker.SetTolerance(0.002)
        self._hover_picker = vtkCellPicker()
        self._hover_picker.SetTolerance(0.004)
        self.hover_enabled = True
        self._hover_label = QtWidgets.QLabel(self)
        self._hover_label.setStyleSheet("background: rgba(10,15,30,220); color: #e8f1ff; border: 1px solid #4cc9f0;"
                                        "border-radius: 4px; padding: 3px 6px; font-size: 11px;")
        self._hover_label.hide()
        self._hover_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        iren = self.plotter.iren
        if iren is not None:
            iren.add_observer("MouseMoveEvent", self._on_move)
            iren.add_observer("LeftButtonPressEvent", self._on_left)

    # ------------------------------------------------------------------ content
    def clear(self):
        self.plotter.clear_actors()
        self.items.clear()
        self.groups.clear()
        self._pick_marker = None
        self._hover_label.hide()

    def remove_group(self, group):
        for k in list(self.groups.get(group, [])):
            it = self.items.pop(k, None)
            if it:
                self.plotter.remove_actor(it["actor"], render=False)
        self.groups.pop(group, None)
        self.plotter.render()

    def _register(self, key, actor, group, labels, pts):
        tree = cKDTree(pts) if pts is not None and len(pts) and not isinstance(labels, str) else None
        self.items[key] = dict(actor=actor, group=group, labels=labels, tree=tree)
        self.groups.setdefault(group, set()).add(key)

    def add_mesh(self, key, verts, faces, color, group="default", label="", vertex_labels=None, opacity=1.0,
                 smooth=True, render=False):
        mesh = pv.PolyData(np.asarray(verts, float), faces_to_pv(faces))
        actor = self.plotter.add_mesh(mesh, color=color, opacity=opacity, smooth_shading=smooth, name=str(key),
                                      render=render, pickable=True, specular=0.3, ambient=0.15)
        if vertex_labels is not None:
            self._register(key, actor, group, list(vertex_labels), np.asarray(verts, float))
        else:
            self._register(key, actor, group, label, None)
        return actor

    def add_points(self, key, pts, color, group="default", labels=None, size=8, render=False):
        pts = np.asarray(pts, float)
        if len(pts) == 0:
            return None
        cloud = pv.PolyData(pts)
        actor = self.plotter.add_mesh(cloud, color=color, point_size=size, render_points_as_spheres=True,
                                      name=str(key), render=render, pickable=True)
        self._register(key, actor, group, list(labels) if labels is not None else "", pts)
        return actor

    def add_surface(self, key, gu, gv, gw, color, group="surfaces", label="", opacity=0.3, render=False):
        grid = pv.StructuredGrid(gu, gv, np.nan_to_num(gw, nan=np.nanmean(gw)))
        mask = np.isnan(gw).ravel(order="F")
        grid["keep"] = (~mask).astype(float)
        grid = grid.threshold(0.5, scalars="keep")
        if grid.n_points == 0:
            return None
        actor = self.plotter.add_mesh(grid, color=color, opacity=opacity, name=str(key), render=render,
                                      pickable=False, smooth_shading=True)
        self._register(key, actor, group, label, None)
        return actor

    def add_lines(self, key, pts, color, group="default", width=3, render=False):
        line = pv.lines_from_points(np.asarray(pts, float))
        actor = self.plotter.add_mesh(line, color=color, line_width=width, name=str(key), render=render, pickable=False)
        self._register(key, actor, group, "", None)

    def set_group_visible(self, group, visible):
        for k in self.groups.get(group, []):
            self.items[k]["actor"].SetVisibility(bool(visible))
        self.plotter.render()

    def set_visible(self, key, visible):
        if key in self.items:
            self.items[key]["actor"].SetVisibility(bool(visible))

    def set_opacity(self, key, opacity):
        if key in self.items:
            self.items[key]["actor"].GetProperty().SetOpacity(opacity)

    def highlight(self, key, color="#ffffff"):
        if key not in self.items:
            return
        prop = self.items[key]["actor"].GetProperty()
        orig = prop.GetColor()
        prop.SetColor(QtGui.QColor(color).redF(), QtGui.QColor(color).greenF(), QtGui.QColor(color).blueF())
        self.plotter.render()
        def restore():
            if key in self.items and self.items[key]["actor"].GetProperty() is prop:
                prop.SetColor(*orig)
                self.plotter.render()
        QtCore.QTimer.singleShot(1500, restore)

    def focus(self, key):
        if key in self.items:
            b = self.items[key]["actor"].GetBounds()
            c = ((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2)
            self.plotter.set_focus(c)
            self.plotter.render()

    def reset_view(self, depth_axis=(0, 0, 1)):
        self.plotter.view_vector((0.6, -1.0, 0.45), viewup=tuple(-np.asarray(depth_axis)))
        self.plotter.reset_camera()
        self.plotter.render()

    def render(self):
        self.plotter.render()

    def screenshot(self, path):
        self.plotter.screenshot(path)

    # ------------------------------------------------------------------ hover
    def _label_at(self, x, y):
        ren = self.plotter.renderer
        if not self._hover_picker.Pick(x, y, 0, ren):
            return None
        actor = self._hover_picker.GetActor()
        if actor is None:
            return None
        for key, it in self.items.items():
            if it["actor"] is actor:
                lab = it["labels"]
                if isinstance(lab, str):
                    return lab or None
                if it["tree"] is not None:
                    pos = np.array(self._hover_picker.GetPickPosition())
                    _, i = it["tree"].query(pos)
                    return lab[int(i)]
        return None

    def _on_move(self, obj, event):
        if not self.hover_enabled:
            return
        now = time.time()
        if now - self._last_hover < 0.12:
            return
        self._last_hover = now
        x, y = self.plotter.iren.get_event_position()
        try:
            lab = self._label_at(x, y)
        except Exception:
            lab = None
        if lab:
            self._hover_label.setText(str(lab))
            self._hover_label.adjustSize()
            h = self.plotter.interactor.height()
            self._hover_label.move(int(x) + 14, int(h - y) + 8)
            self._hover_label.show()
            self._hover_label.raise_()
        else:
            self._hover_label.hide()

    # ------------------------------------------------------------------ picking
    def start_pick(self, keys):
        """Next left click on one of these items emits `picked` with the world position."""
        self._pick_keys = set(keys)
        self.plotter.interactor.setCursor(QtCore.Qt.CrossCursor)

    def cancel_pick(self):
        self._pick_keys = None
        self.plotter.interactor.unsetCursor()

    def _on_left(self, obj, event):
        if not self._pick_keys:
            return
        x, y = self.plotter.iren.get_event_position()
        if not self._cell_picker.Pick(x, y, 0, self.plotter.renderer):
            return
        actor = self._cell_picker.GetActor()
        ok = any(self.items.get(k, {}).get("actor") is actor for k in self._pick_keys)
        if not ok:
            return
        pos = np.array(self._cell_picker.GetPickPosition())
        self.cancel_pick()
        self.mark(pos)
        self.picked.emit(pos)

    def mark(self, pos, color="#ff3355", key="__pick__"):
        if key in self.items:
            self.plotter.remove_actor(self.items.pop(key)["actor"], render=False)
        sph = pv.Sphere(radius=2.5, center=pos)
        actor = self.plotter.add_mesh(sph, color=color, name=key, pickable=False)
        self.items[key] = dict(actor=actor, group="__pick__", labels="origin", tree=None)
        self.plotter.render()
