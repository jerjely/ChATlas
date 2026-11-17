"""Distances along a cell's arbor (path length) instead of straight lines."""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree


class ArborGraph:
    """Nodes with positions (µm) and a weighted undirected graph (edge length in µm)."""

    def __init__(self, pos, edges, source, bridge_um=0.0):
        self.pos = np.asarray(pos, float)
        self.tree = cKDTree(self.pos)
        e = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
        e = e[e[:, 0] != e[:, 1]]
        self.source = source
        self._build(e)
        self.n_bridges = 0
        if bridge_um > 0 and self.n_comp > 1:
            # connect separate pieces that nearly touch (e.g. seams between mesh chunks)
            pairs = np.array(sorted(self.tree.query_pairs(bridge_um)), dtype=np.int64).reshape(-1, 2)
            if len(pairs):
                pairs = pairs[self.comp[pairs[:, 0]] != self.comp[pairs[:, 1]]]
                self.n_bridges = len(pairs)
                if len(pairs):
                    self._build(np.vstack([e, pairs]))

    def _build(self, e):
        w = np.linalg.norm(self.pos[e[:, 0]] - self.pos[e[:, 1]], axis=1)
        n = len(self.pos)
        self.graph = coo_matrix((np.r_[w, w], (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])), shape=(n, n)).tocsr()
        self.n_comp, self.comp = connected_components(self.graph, directed=False)
        self.main = int(np.bincount(self.comp).argmax())

    def summary(self):
        sizes = np.bincount(self.comp)
        br = f", {self.n_bridges} small gaps bridged" if getattr(self, "n_bridges", 0) else ""
        return (f"{self.source}: {len(self.pos):,} nodes, {self.graph.nnz // 2:,} edges, "
                f"{self.n_comp} connected piece(s) (largest {sizes.max() / len(self.pos):.0%} of nodes){br}")

    def distances(self, origin_um, targets_um):
        """Path length (µm) from the node nearest the origin to the node nearest each target.
        Returns (path_um, snap_um); path is NaN when a target sits on a disconnected piece."""
        origin_um = np.asarray(origin_um, float)
        _, o = self.tree.query(origin_um)
        if self.comp[o] != self.main and np.mean(self.comp == self.comp[o]) < 0.05:
            # origin landed on a stray small piece: snap to the nearest node of the main body instead
            idx_main = np.where(self.comp == self.main)[0]
            o = idx_main[np.argmin(np.linalg.norm(self.pos[idx_main] - origin_um, axis=1))]
        d = dijkstra(self.graph, directed=False, indices=int(o))
        snap, idx = self.tree.query(np.asarray(targets_um, float))
        path = d[idx]
        path[~np.isfinite(path)] = np.nan
        return path, snap


def l2_graph(cave, rid, chunk=3000):
    """Arbor graph from the chunked graph's L2 adjacency + L2-cache positions."""
    cg, l2c = cave.client.chunkedgraph, cave.client.l2cache
    edges = np.asarray(cg.level2_chunk_graph(int(rid)), dtype=np.int64).reshape(-1, 2)
    ids = np.unique(edges) if len(edges) else np.asarray(cg.get_leaves(int(rid), stop_layer=2), dtype=np.int64)
    pos = {}
    for a in range(0, len(ids), chunk):
        sub = ids[a:a + chunk]
        d = l2c.get_l2data(sub.tolist(), attributes=["rep_coord_nm"])
        for i in sub:
            e = d.get(str(i), {})
            if "rep_coord_nm" in e:
                pos[int(i)] = e["rep_coord_nm"]
    keep = np.array([i for i in ids if int(i) in pos], dtype=np.int64)
    if len(keep) < 2:
        raise ValueError("no L2 positions")
    index = {int(i): k for k, i in enumerate(keep)}
    P = np.array([pos[int(i)] for i in keep], float) / 1000.0
    E = np.array([(index[int(a)], index[int(b)]) for a, b in edges if int(a) in index and int(b) in index], dtype=np.int64)
    return ArborGraph(P, E, "L2 chunk graph")


def mesh_graph(verts_um, faces):
    """Fallback: graph over mesh vertices (paths run along the membrane surface)."""
    f = np.asarray(faces, dtype=np.int64)
    e = np.vstack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    e = np.unique(np.sort(e, axis=1), axis=0)
    return ArborGraph(verts_um, e, "mesh surface graph", bridge_um=1.0)


def build_arbor_graph(cave, meshes, rid, s, log=print):
    try:
        g = l2_graph(cave, rid)
    except Exception as e:
        log(f"L2 graph not available ({str(e)[:80]}); using the mesh surface instead")
        meshes.ensure([rid], log=log)
        v, f = meshes.simplified(rid, max(s.faces_target, 60_000))
        g = mesh_graph(v, f)
    log(g.summary())
    return g
