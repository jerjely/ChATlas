"""Mesh cache on disk: download, load one at a time, sample, simplify."""
import gc
import os
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import trimesh


class MeshStore:
    def __init__(self, settings, cave):
        self.s = settings
        self.cave = cave
        self._pts = {}

    def path(self, rid):
        return os.path.join(self.s.mesh_cache, f"{int(rid)}.ply")

    def has(self, rid):
        return os.path.exists(self.path(rid))

    def _download(self, rid, retries=4):
        f = self.path(rid)
        if os.path.exists(f):
            return True
        for attempt in range(retries):
            try:
                m = self.cave.cv.mesh.get(int(rid))
                m = m[int(rid)] if isinstance(m, dict) else m
                tm = trimesh.Trimesh(vertices=m.vertices, faces=m.faces, process=False)
                tm.merge_vertices()
                tmp = f + ".tmp.ply"
                tm.export(tmp)
                os.replace(tmp, f)
                return True
            except MemoryError:
                raise
            except Exception:
                if attempt == retries - 1:
                    raise
                time.sleep(2 * (attempt + 1))

    def ensure(self, ids, progress=None, log=None, cancelled=lambda: False):
        """Download missing meshes; returns the set of IDs available in the cache."""
        ids = list(dict.fromkeys(int(r) for r in ids))
        todo = [r for r in ids if not self.has(r)]
        if log:
            log(f"{len(ids)} meshes needed, {len(ids) - len(todo)} cached, downloading {len(todo)}")
        failed = {}
        if todo:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with ThreadPoolExecutor(max(1, int(self.s.threads))) as ex:
                    futs = {ex.submit(self._download, r): r for r in todo}
                    for k, fu in enumerate(as_completed(futs), 1):
                        if cancelled():
                            ex.shutdown(cancel_futures=True)
                            break
                        try:
                            fu.result()
                        except Exception as e:
                            failed[futs[fu]] = str(e)[:120]
                        if progress:
                            progress(k, len(todo), "downloading meshes")
        if failed and log:
            log(f"{len(failed)} meshes failed (run again to retry): " + "; ".join(f"{k}: {v}" for k, v in list(failed.items())[:3]))
        for r in ids:
            if r not in todo:
                _touch(self.path(r))          # mark cached meshes as recently used
        self.enforce_limit(protect=set(ids), log=log)
        return {r for r in ids if self.has(r)}

    # ---- cache management ---------------------------------------------------------
    def _files(self):
        d = self.s.mesh_cache
        out = []
        if os.path.isdir(d):
            for e in os.scandir(d):
                if e.is_file() and e.name.endswith(".ply"):
                    st = e.stat()
                    out.append((e.path, e.name, st.st_size, st.st_mtime))
        return out

    def stats(self):
        files = self._files()
        full = [f for f in files if not f[1].startswith("dec")]
        dec = [f for f in files if f[1].startswith("dec")]
        return dict(n_meshes=len(full), bytes_meshes=sum(f[2] for f in full),
                    n_simplified=len(dec), bytes_simplified=sum(f[2] for f in dec),
                    bytes_total=sum(f[2] for f in files))

    @staticmethod
    def _rid_of(name):
        stem = name[:-4]
        return int(stem.split("_")[-1]) if stem.split("_")[-1].isdigit() else None

    def clear(self, simplified_only=False, older_than_days=None, protect=()):
        """Delete cached files; returns (n_files, bytes)."""
        now = time.time()
        n = b = 0
        protect = set(int(x) for x in protect)
        for path, name, size, mtime in self._files():
            if simplified_only and not name.startswith("dec"):
                continue
            if older_than_days is not None and now - mtime < older_than_days * 86400:
                continue
            if self._rid_of(name) in protect:
                continue
            try:
                os.remove(path); n += 1; b += size
            except OSError:
                pass
        self._pts.clear()
        return n, b

    def enforce_limit(self, protect=(), log=None):
        """Remove least-recently-used files until the cache is below cache_max_gb."""
        limit = float(getattr(self.s, "cache_max_gb", 0) or 0) * 1e9
        if limit <= 0:
            return 0
        files = sorted(self._files(), key=lambda f: f[3])           # oldest use first
        total = sum(f[2] for f in files)
        protect = set(int(x) for x in protect)
        removed = 0
        for path, name, size, mtime in files:
            if total <= limit:
                break
            if self._rid_of(name) in protect:
                continue
            try:
                os.remove(path); total -= size; removed += size
            except OSError:
                pass
        if removed and log:
            log(f"mesh cache above {limit / 1e9:.1f} GB: removed {removed / 1e9:.2f} GB of least-recently-used meshes")
        return removed

    def load(self, rid):
        _touch(self.path(rid))
        return trimesh.load(self.path(rid), process=False)

    def sample(self, rid, per_um2, max_n=None, keep=True):
        """Area-uniform surface points in µm (kept in memory as float32 unless keep=False)."""
        key = (int(rid), per_um2, max_n)
        if key in self._pts:
            return self._pts[key].astype(float)
        tm = self.load(rid)
        n = int(np.clip(tm.area / 1e6 * per_um2, 2000, max_n or self.s.max_samples))
        p = (_sample_low_memory(tm, n) / 1000.0).astype(np.float32)
        del tm
        gc.collect()
        if keep:
            self._pts[key] = p
        return p.astype(float)

    def simplified(self, rid, n_faces):
        """(vertices µm, faces) simplified to ~n_faces; cached on disk."""
        f_dec = os.path.join(self.s.mesh_cache, f"dec{int(n_faces)}_{int(rid)}.ply")
        if os.path.exists(f_dec):
            _touch(f_dec)
            tm = trimesh.load(f_dec, process=False)
        else:
            tm = self.load(rid)
            tm = simplify(tm, n_faces)
            tm.export(f_dec)
        return np.asarray(tm.vertices) / 1000.0, np.asarray(tm.faces)


def _touch(path):
    try:
        os.utime(path, None)
    except OSError:
        pass


def _sample_low_memory(tm, n, seed=0):
    """Area-weighted surface sampling without trimesh's large temporary arrays (float32, chunked)."""
    rng = np.random.default_rng(seed)
    v = np.asarray(tm.vertices, dtype=np.float32)
    f = np.asarray(tm.faces)
    area = np.empty(len(f), dtype=np.float32)
    for a in range(0, len(f), 500_000):
        ff = f[a:a + 500_000]
        area[a:a + len(ff)] = 0.5 * np.linalg.norm(np.cross(v[ff[:, 1]] - v[ff[:, 0]], v[ff[:, 2]] - v[ff[:, 0]]), axis=1)
    cdf = np.cumsum(area, dtype=np.float64)
    idx = np.searchsorted(cdf, rng.random(n) * cdf[-1])
    idx = np.clip(idx, 0, len(f) - 1)
    r1, r2 = rng.random((2, n)).astype(np.float32)
    flip = r1 + r2 > 1
    r1[flip], r2[flip] = 1 - r1[flip], 1 - r2[flip]
    ff = f[idx]
    a, b, c = v[ff[:, 0]], v[ff[:, 1]], v[ff[:, 2]]
    return a + r1[:, None] * (b - a) + r2[:, None] * (c - a)


def simplify(tm, n_faces):
    if len(tm.faces) <= n_faces:
        return tm
    try:
        import fast_simplification
        v, f = fast_simplification.simplify(np.asarray(tm.vertices, np.float32), np.asarray(tm.faces),
                                            target_reduction=1 - n_faces / len(tm.faces))
        return trimesh.Trimesh(v, f, process=False)
    except Exception:
        pass
    try:
        return tm.simplify_quadric_decimation(face_count=n_faces)
    except Exception:
        rng = np.random.default_rng(0)
        idx = rng.choice(len(tm.faces), n_faces, replace=False)
        out = trimesh.Trimesh(tm.vertices, tm.faces[idx], process=False)
        out.remove_unreferenced_vertices()
        return out
