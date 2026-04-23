"""
Custom VRML 2.0 parser for CATIA-exported WRL files.

Key design: accumulate all geometry into flat numpy arrays during parsing
and create ONE merged trimesh.Trimesh at the end.  The original approach of
creating a separate Trimesh per Shape produced 778 000+ objects in the scene,
making trimesh's GLB exporter hang because it serialises every mesh as a
separate GLTF primitive.  A single merged mesh exports in seconds.

GPU acceleration (gpu_accel.py):
- Final chunk concatenation runs on the RTX 4000 Ada via CuPy when the
  dataset is large enough to justify the PCIe transfer.
- Face validation and color tiling also offload to GPU for large arrays.

CATIA WRL Shape structure:

    Shape {
        appearance Appearance {
            material Material { diffuseColor r g b }
        }
        geometry IndexedFaceSet {
            coord Coordinate { point [ x y z, ... ] }
            coordIndex [ i j k -1 ... ]
        }
    }
"""

import logging
import re

import numpy as np
import trimesh

import gpu_accel

log = logging.getLogger(__name__)

# ── Pre-compiled patterns ─────────────────────────────────────────────────────
_RE_COMMENT    = re.compile(r'#[^\n]*')
_RE_DIFFUSE    = re.compile(
    r'diffuseColor\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)'
)
_RE_POINT_OPEN = re.compile(r'\bpoint\s*\[')
_RE_CIDX_OPEN  = re.compile(r'\bcoordIndex\s*\[')
# Regex fallbacks (only used when numpy fast-path fails)
_RE_FLOAT      = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')
_RE_INT        = re.compile(r'-?\d+')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _block_after(content: str, start: int) -> tuple[str, int]:
    """Return the balanced { ... } block that starts at or after *start*."""
    p = content.find('{', start)
    if p == -1:
        return '', -1
    depth = 0
    for i in range(p, len(content)):
        c = content[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return content[p: i + 1], i + 1
    return '', -1


def _bracket_content(content: str, open_re: re.Pattern, start: int) -> tuple[str, int]:
    """Find *open_re* (matches '...keyword [') from *start*, return content up to ']'."""
    m = open_re.search(content, start)
    if not m:
        return '', -1
    bracket_start = m.end() - 1          # points at '['
    p = content.find('[', bracket_start)
    q = content.find(']', p)
    if p == -1 or q == -1:
        return '', -1
    return content[p + 1: q], q + 1


def _parse_floats(text: str) -> np.ndarray:
    """Parse floats from VRML coordinate text.

    Uses numpy.fromstring (C extension) which is 10–50× faster than regex
    for large vertex arrays. Falls back to regex on parse error.
    """
    try:
        clean = text.replace(',', ' ')
        result = np.fromstring(clean, dtype=np.float32, sep=' ')
        if len(result) > 0:
            return result
    except Exception:
        pass
    return np.array(_RE_FLOAT.findall(text), dtype=np.float32)


def _parse_indices(text: str) -> np.ndarray:
    """Parse integers from VRML coordIndex text using numpy (fast path)."""
    try:
        clean = text.replace(',', ' ')
        return np.fromstring(clean, dtype=np.int32, sep=' ')
    except Exception:
        return np.array(list(map(int, _RE_INT.findall(text))), dtype=np.int32)


def _indices_to_faces(indices: np.ndarray) -> np.ndarray | None:
    """Convert -1-terminated VRML index array to an Nx3 triangle array.

    Fully vectorised: triangles and quads are handled with numpy fancy
    indexing (no Python loop); n-gons use a loop but are rare in CATIA output.
    """
    if not isinstance(indices, np.ndarray):
        indices = np.asarray(indices, dtype=np.int32)
    if len(indices) == 0:
        return None

    # Ensure sentinel at end
    if indices[-1] != -1:
        indices = np.append(indices, np.int32(-1))

    neg_pos = np.where(indices == -1)[0]
    if len(neg_pos) == 0:
        return None

    starts = np.empty(len(neg_pos), dtype=np.int64)
    starts[0] = 0
    starts[1:] = neg_pos[:-1] + 1
    lengths = (neg_pos - starts).astype(np.int64)

    # Drop degenerate polygons
    valid = lengths >= 3
    starts  = starts[valid]
    lengths = lengths[valid]

    if len(starts) == 0:
        return None

    face_list: list[np.ndarray] = []

    # ── Triangles (most common in CATIA VRML) ────────────────────────────────
    tri_mask = lengths == 3
    if tri_mask.any():
        ts = starts[tri_mask].astype(np.intp)
        face_list.append(np.column_stack([
            indices[ts],
            indices[ts + 1],
            indices[ts + 2],
        ]))

    # ── Quads (fan-triangulate to 2 triangles each) ───────────────────────────
    quad_mask = lengths == 4
    if quad_mask.any():
        qs = starts[quad_mask].astype(np.intp)
        i0, i1, i2, i3 = (
            indices[qs], indices[qs + 1], indices[qs + 2], indices[qs + 3]
        )
        face_list.append(np.column_stack([i0, i1, i2]))
        face_list.append(np.column_stack([i0, i2, i3]))

    # ── N-gons (rare — Python loop acceptable) ────────────────────────────────
    ngon_mask = lengths > 4
    if ngon_mask.any():
        ngon_faces: list[list[int]] = []
        for s, l in zip(starts[ngon_mask].tolist(), lengths[ngon_mask].tolist()):
            poly = indices[int(s): int(s) + int(l)]
            for i in range(1, int(l) - 1):
                ngon_faces.append([int(poly[0]), int(poly[i]), int(poly[i + 1])])
        if ngon_faces:
            face_list.append(np.array(ngon_faces, dtype=np.int32))

    if not face_list:
        return None

    return np.concatenate(face_list, axis=0).astype(np.int32)


# ── Per-shape raw data extractor ──────────────────────────────────────────────

def _extract_shape(block: str):
    """
    Return (vertices Nx3 float32, faces Mx3 int32, color 4-element uint8)
    or None if the block has no usable geometry.
    """
    # colour
    color = np.array([192, 192, 204, 255], dtype=np.uint8)
    m = _RE_DIFFUSE.search(block)
    if m:
        r, g, b = float(m.group(1)), float(m.group(2)), float(m.group(3))
        color[:3] = np.clip([r, g, b], 0, 1) * 255

    # vertices
    raw_pts, _ = _bracket_content(block, _RE_POINT_OPEN, 0)
    if not raw_pts:
        return None
    vf = _parse_floats(raw_pts)
    if len(vf) == 0 or len(vf) % 3 != 0:
        return None
    vertices = vf.reshape(-1, 3)

    # face indices
    raw_idx, _ = _bracket_content(block, _RE_CIDX_OPEN, 0)
    if not raw_idx:
        return None
    idx_arr = _parse_indices(raw_idx)
    faces = _indices_to_faces(idx_arr)
    if faces is None or len(faces) == 0:
        return None

    # drop faces that reference an out-of-bounds vertex
    if faces.size > 0:
        faces = gpu_accel.validate_faces(faces, len(vertices))
    if len(faces) == 0:
        return None

    return vertices, faces, color


# ── Public entry point ────────────────────────────────────────────────────────

def load_vrml_as_scene(filepath: str) -> trimesh.Scene:
    """
    Parse *filepath* (VRML 2.0) and return a trimesh.Scene containing a
    single merged mesh.  Creating one mesh instead of one-per-Shape reduces
    the GLTF primitive count from ~800 000 to 1, making GLB export instant.
    """
    log.info("GPU status: %s", gpu_accel.GPU_INFO)
    log.info("Reading %s …", filepath)
    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        content = fh.read()
    log.info("In RAM: %.1f MB", len(content) / 1_048_576)

    content = _RE_COMMENT.sub('', content)

    vert_chunks:  list[np.ndarray] = []
    face_chunks:  list[np.ndarray] = []
    color_chunks: list[np.ndarray] = []

    mesh_count = skip_count = 0
    v_offset = 0
    pos = 0
    kw, kw_len = 'Shape', len('Shape')

    log.info("Scanning for Shape blocks …")
    while True:
        idx = content.find(kw, pos)
        if idx == -1:
            break

        before = content[idx - 1]         if idx > 0             else ' '
        after  = content[idx + kw_len]    if idx + kw_len < len(content) else ' '
        if before.isalpha() or after.isalpha():
            pos = idx + kw_len
            continue

        block, next_pos = _block_after(content, idx + kw_len)
        if not block or next_pos == -1:
            pos = idx + kw_len
            continue
        pos = next_pos

        try:
            result = _extract_shape(block)
            if result is None:
                skip_count += 1
                continue

            vertices, faces, color = result
            n_faces = len(faces)

            vert_chunks.append(vertices)
            face_chunks.append(faces + v_offset)
            color_chunks.append(gpu_accel.tile_color(color, n_faces))
            v_offset   += len(vertices)
            mesh_count += 1

            if mesh_count % 5_000 == 0:
                log.info("  … %d shapes accumulated", mesh_count)

        except Exception as exc:
            skip_count += 1
            if skip_count <= 5:
                log.warning("Skipped shape %d: %s", mesh_count + skip_count, exc)

    log.info("Accumulated %d shapes (%d skipped) — merging into one mesh …",
             mesh_count, skip_count)

    if not vert_chunks:
        log.warning("No geometry found — returning empty scene")
        return trimesh.Scene()

    # ── GPU-accelerated chunk merge ───────────────────────────────────────────
    log.info("Merging %d vertex chunks on %s …",
             len(vert_chunks), "GPU" if gpu_accel.GPU_AVAILABLE else "CPU")
    all_vertices    = gpu_accel.concatenate_chunks(vert_chunks,  axis=0)
    all_faces       = gpu_accel.concatenate_chunks(face_chunks,  axis=0)
    all_face_colors = gpu_accel.concatenate_chunks(color_chunks, axis=0)

    log.info("Merged: %s vertices, %s triangles",
             f"{len(all_vertices):,}", f"{len(all_faces):,}")

    del vert_chunks, face_chunks, color_chunks

    merged = trimesh.Trimesh(
        vertices=all_vertices,
        faces=all_faces,
        process=False,
    )
    merged.visual.face_colors = all_face_colors

    scene = trimesh.Scene()
    scene.add_geometry(merged, geom_name='layout')
    log.info("Scene ready — 1 merged mesh, passing to GLB exporter …")
    return scene
