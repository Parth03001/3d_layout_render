"""
Custom VRML 2.0 parser for CATIA-exported WRL files.

Key design: accumulate all geometry into flat numpy arrays during parsing
and create ONE merged trimesh.Trimesh at the end.  The original approach of
creating a separate Trimesh per Shape produced 778 000+ objects in the scene,
making trimesh's GLB exporter hang because it serialises every mesh as a
separate GLTF primitive.  A single merged mesh exports in seconds.

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

log = logging.getLogger(__name__)

# ── Pre-compiled patterns ─────────────────────────────────────────────────────
_RE_COMMENT = re.compile(r'#[^\n]*')
_RE_DIFFUSE = re.compile(
    r'diffuseColor\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)'
)
_RE_POINT_OPEN = re.compile(r'\bpoint\s*\[')
_RE_CIDX_OPEN  = re.compile(r'\bcoordIndex\s*\[')
_RE_FLOAT = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')
_RE_INT   = re.compile(r'-?\d+')


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
    return np.array(_RE_FLOAT.findall(text), dtype=np.float32)


def _parse_indices(text: str) -> list[int]:
    return list(map(int, _RE_INT.findall(text)))


def _indices_to_faces(indices: list[int]) -> np.ndarray | None:
    """Convert -1-terminated VRML index list to Nx3 triangle array."""
    faces: list[list[int]] = []
    poly: list[int] = []
    for idx in indices:
        if idx == -1:
            n = len(poly)
            if n == 3:
                faces.append(poly)
            elif n > 3:
                for i in range(1, n - 1):
                    faces.append([poly[0], poly[i], poly[i + 1]])
            poly = []
        else:
            poly.append(idx)
    # flush final polygon if trailing -1 is absent
    n = len(poly)
    if n == 3:
        faces.append(poly)
    elif n > 3:
        for i in range(1, n - 1):
            faces.append([poly[0], poly[i], poly[i + 1]])
    return np.array(faces, dtype=np.int32) if faces else None


# ── Per-shape raw data extractor ──────────────────────────────────────────────

def _extract_shape(block: str):
    """
    Return (vertices Nx3 float32, faces Mx3 int32, color 4-element uint8)
    or None if the block has no usable geometry.
    """
    # colour
    color = np.array([192, 192, 204, 255], dtype=np.uint8)   # default light-grey
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
    faces = _indices_to_faces(_parse_indices(raw_idx))
    if faces is None or len(faces) == 0:
        return None

    # drop faces that reference a vertex out of bounds
    valid = faces.max(axis=1) < len(vertices)
    if not valid.all():
        faces = faces[valid]
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
    log.info("Reading %s …", filepath)
    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        content = fh.read()
    log.info("In RAM: %.1f MB", len(content) / 1_048_576)

    content = _RE_COMMENT.sub('', content)

    # Accumulate raw numpy arrays — NO per-shape Trimesh creation
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

        # Reject 'Shape' that is part of a longer identifier
        before = content[idx - 1]  if idx > 0             else ' '
        after  = content[idx + kw_len] if idx + kw_len < len(content) else ' '
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
            color_chunks.append(
                np.tile(color, (n_faces, 1))   # broadcast colour to every face
            )
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

    # ── One concatenation pass ────────────────────────────────────────────
    all_vertices    = np.concatenate(vert_chunks,  axis=0)
    all_faces       = np.concatenate(face_chunks,  axis=0)
    all_face_colors = np.concatenate(color_chunks, axis=0)

    log.info("Merged: %s vertices, %s triangles",
             f"{len(all_vertices):,}", f"{len(all_faces):,}")

    # Free chunk lists before creating the large Trimesh
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
