"""Build Neuroglancer states from ChATlas selections and open them in the browser."""
import json
import urllib.parse
import webbrowser

import numpy as np


def _hex(c):
    c = str(c)
    return c if c.startswith("#") else "#" + c


def segmentation_source(cave):
    src = cave.client.info.segmentation_source()
    if src.startswith("graphene://https://"):
        src = src.replace("graphene://https://", "graphene://middleauth+https://")
    return src


def image_source(cave):
    try:
        return cave.client.info.image_source()
    except Exception:
        return None


def build_state(seg_source, img_source, segments, voxel_nm=(16, 16, 40), point_layers=None, position=None,
                layer_name="cells", show_3d_only=False):
    """
    segments: dict root_id -> colour (hex)
    point_layers: list of dict(name, color, points (N x 3, voxels), descriptions (optional))
    position: voxel (x, y, z) for the view centre
    """
    dims = {"x": [voxel_nm[0] * 1e-9, "m"], "y": [voxel_nm[1] * 1e-9, "m"], "z": [voxel_nm[2] * 1e-9, "m"]}
    layers = []
    if img_source:
        layers.append({"type": "image", "source": img_source, "tab": "source", "name": "img"})
    ids = [str(int(r)) for r in segments]
    layers.append({"type": "segmentation", "source": seg_source, "tab": "segments", "name": layer_name,
                   "segments": ids, "segmentColors": {str(int(k)): _hex(v) for k, v in segments.items()}})
    for pl in point_layers or []:
        pts = np.asarray(pl["points"], float)
        desc = pl.get("descriptions") or [None] * len(pts)
        anns = []
        for i, (p, d) in enumerate(zip(pts, desc)):
            a = {"point": [float(p[0]), float(p[1]), float(p[2])], "type": "point", "id": f"{abs(hash(pl['name'])) % 10**8}{i}"}
            if d:
                a["description"] = str(d)
            anns.append(a)
        layers.append({"type": "annotation", "source": {"url": "local://annotations",
                       "transform": {"outputDimensions": dims}}, "tab": "annotations",
                       "annotationColor": _hex(pl.get("color", "#ffff00")), "annotations": anns, "name": pl["name"]})
    state = {"dimensions": dims, "layers": layers, "selectedLayer": {"visible": True, "layer": layer_name},
             "layout": "3d" if show_3d_only else "xy-3d", "projectionScale": 60000}
    if position is not None:
        state["position"] = [float(x) for x in position]
    return state


def open_state(cave, state, log=print):
    """Upload to the CAVE state server and open; falls back to a URL that carries the whole state."""
    url = None
    try:
        viewer = cave.client.info.viewer_site()
    except Exception:
        viewer = None
    try:
        sid = cave.client.state.upload_state_json(state)
        url = cave.client.state.build_neuroglancer_url(sid, ngl_url=viewer) if viewer else \
            cave.client.state.build_neuroglancer_url(sid)
    except Exception as e:
        log(f"state server not available ({str(e)[:80]}); using a URL with the state embedded")
    if url is None:
        base = (viewer or "https://neuroglancer-demo.appspot.com").rstrip("/")
        url = f"{base}/#!" + urllib.parse.quote(json.dumps(state, separators=(",", ":")))
    webbrowser.open(url)
    return url
