"""Settings stored in %USERPROFILE%/ChATlas/settings.json."""
import json
import os
from dataclasses import dataclass, asdict, field

DATA_DIR = os.path.join(os.path.expanduser("~"), "ChATlas")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


@dataclass
class Settings:
    datastack: str = "stroeh_mouse_retina"
    server: str = "https://global.daf-apis.com"
    labels_manual: str = "retina_cell_types_manual"
    labels_auto: str = "retina_cell_types_auto"
    voxel_nm: tuple = (16.0, 16.0, 40.0)          # table / Neuroglancer coordinates
    mesh_cache: str = os.path.join(DATA_DIR, "mesh_cache")
    output_dir: str = os.path.join(DATA_DIR, "outputs")
    threads: int = 4
    cache_max_gb: float = 20.0        # 0 = unlimited; least-recently-used meshes are removed beyond this

    # ChAT surfaces / sampling
    sacs_per_point: int = 2
    sac_spacing_um: float = 120.0      # grid spacing for picking SACs over a region (one nearest SAC per grid point)
    max_sacs_per_layer: int = 25
    samples_per_um2_sac: float = 4.0
    samples_per_um2_cell: float = 10.0
    max_samples: int = 100_000
    max_samples_sac: int = 40_000
    grid_um: float = 4.0
    min_pts_per_bin: int = 20
    poly_deg: int = 2
    band_half_um: float = 4.0
    smooth_um: float = 8.0

    # features
    ipl_range: tuple = (-1.2, 2.4)
    bin: float = 0.1
    terminal_frac: float = 0.15
    min_terminal_pts: int = 200
    max_terminal_diam_um: float = 60.0
    min_covered: float = 0.8
    min_cells_per_type: int = 5
    ref_radius_um: float = 40.0
    ref_per_type: int = 15

    # display
    faces_per_cell: int = 2000
    faces_target: int = 80_000

    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls):
        s = cls()
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, encoding="utf-8") as f:
                    d = json.load(f)
                for k, v in d.items():
                    if hasattr(s, k):
                        setattr(s, k, tuple(v) if isinstance(getattr(s, k), tuple) else v)
            except Exception:
                pass
        s.ensure_dirs()
        return s

    def save(self):
        self.ensure_dirs()
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    def ensure_dirs(self):
        for d in (DATA_DIR, self.mesh_cache, self.output_dir):
            os.makedirs(d, exist_ok=True)
