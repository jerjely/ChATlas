import os as _os

# Keep the math libraries single-threaded and tolerant of duplicate OpenMP runtimes: on Windows,
# MKL / OpenMP DLLs loaded next to VTK and Qt can otherwise crash numerical code in worker threads.
for _k, _v in {"MKL_THREADING_LAYER": "SEQUENTIAL", "KMP_DUPLICATE_LIB_OK": "TRUE",
               "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}.items():
    _os.environ.setdefault(_k, _v)

__app_name__ = "ChATlas"
__version__ = "1.5.0"
