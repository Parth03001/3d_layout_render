"""GPU acceleration layer for array operations.

Uses CuPy (CUDA) when available; falls back transparently to NumPy.
Heavy operations — chunk concatenation, face validation, color tiling —
run on the GPU when the dataset is large enough to justify the transfer.
"""

import logging
import numpy as np

log = logging.getLogger(__name__)

GPU_AVAILABLE = False
GPU_INFO = "not available"

try:
    import cupy as cp

    _dev = cp.cuda.Device(0)
    _dev.use()
    _rt_ver = cp.cuda.runtime.runtimeGetVersion()
    _major, _minor = _rt_ver // 1000, (_rt_ver % 1000) // 10
    _props = cp.cuda.runtime.getDeviceProperties(0)
    _name = _props["name"].decode() if isinstance(_props["name"], (bytes, bytearray)) else _props["name"]
    GPU_INFO = f"{_name} (CUDA {_major}.{_minor}, CuPy {cp.__version__})"
    GPU_AVAILABLE = True
    log.info("GPU acceleration ENABLED — %s", GPU_INFO)
except Exception as _exc:
    cp = None  # type: ignore[assignment]
    log.info("GPU not available (%s) — CPU fallback active", _exc)


# Threshold: only use GPU if chunk count or element count justifies the PCIe transfer
_GPU_CHUNK_THRESHOLD = 500
_GPU_ELEM_THRESHOLD = 500_000


def concatenate_chunks(chunks: list, axis: int = 0) -> np.ndarray:
    """Concatenate a list of numpy arrays, offloading to GPU when beneficial."""
    if not chunks:
        raise ValueError("empty chunk list")
    if len(chunks) == 1:
        return chunks[0]

    total_elements = sum(a.size for a in chunks)
    use_gpu = GPU_AVAILABLE and (
        len(chunks) >= _GPU_CHUNK_THRESHOLD or total_elements >= _GPU_ELEM_THRESHOLD
    )

    if use_gpu:
        try:
            merged = cp.concatenate([cp.asarray(c) for c in chunks], axis=axis)
            return cp.asnumpy(merged)
        except Exception as exc:
            log.warning("GPU concatenate failed (%s) — falling back to CPU", exc)

    return np.concatenate(chunks, axis=axis)


def validate_faces(faces: np.ndarray, n_vertices: int) -> np.ndarray:
    """Return only rows of *faces* whose max vertex index < n_vertices."""
    if GPU_AVAILABLE and faces.size >= _GPU_ELEM_THRESHOLD:
        try:
            gf = cp.asarray(faces)
            valid = gf.max(axis=1) < n_vertices
            return cp.asnumpy(gf[valid])
        except Exception as exc:
            log.warning("GPU face-validation failed (%s) — CPU fallback", exc)

    valid = faces.max(axis=1) < n_vertices
    return faces[valid]


def tile_color(color: np.ndarray, n_faces: int) -> np.ndarray:
    """Broadcast a 4-element color to shape (n_faces, 4)."""
    if GPU_AVAILABLE and n_faces >= _GPU_ELEM_THRESHOLD:
        try:
            return cp.asnumpy(cp.tile(cp.asarray(color), (n_faces, 1)))
        except Exception as exc:
            log.warning("GPU tile failed (%s) — CPU fallback", exc)

    return np.tile(color, (n_faces, 1))
