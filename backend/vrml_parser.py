"""
Custom VRML 2.0 parser for CATIA-exported WRL files.

CATIA WRL structure (each part is a Shape block):

  Shape {
    appearance Appearance {
      material Material { diffuseColor r g b }
    }
    geometry IndexedFaceSet {
      coord Coordinate { point [ x y z, ... ] }
      coordIndex [ i j k -1 ... ]
      normal Normal { vector [ nx ny nz, ... ] }
      normalIndex [ i j k -1 ... ]      (optional)
    }
  }

Transform nodes with translation/rotation wrap groups of Shape nodes.
We collect all Shape blocks (with their Transform context) and convert
each IndexedFaceSet into a trimesh.Trimesh, then return a trimesh.Scene.
"""

import logging
import re

import numpy as np
import trimesh

log = logging.getLogger(__name__)

# ── Pre-compiled patterns ────────────────────────────────────────────────────

_RE_COMMENT  = re.compile(r'#[^\n]*')
_RE_DIFFUSE  = re.compile(
    r'diffuseColor\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)'
)
_RE_POINT_BLOCK  = re.compile(r'\bpoint\s*\[',  re.DOTALL)
_RE_CIDX_BLOCK   = re.compile(r'\bcoordIndex\s*\[', re.DOTALL)
_RE_FLOAT        = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')
_RE_INT          = re.compile(r'-?\d+')


# ── Brace-matched block extractor ─────────────────────────────────────────────

def _block_after(content: str, start: int) -> tuple[str, int]:
    """
    Starting at *start*, find the next '{' and return the full balanced
    '{...}' block plus the position just after its closing '}'.
    Returns ('', -1) on failure.
    """
    p = content.find('{', start)
    if p == -1:
        return '', -1
    depth = 0
    for i in range(p, len(content)):
        ch = content[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return content[p: i + 1], i + 1
    return '', -1


def _bracket_content(content: str, start: int) -> tuple[str, int]:
    """
    Starting at *start*, find the next '[' and return everything inside
    the matching ']', plus the position just after ']'.
    """
    p = content.find('[', start)
    if p == -1:
        return '', -1
    q = content.find(']', p)
    if q == -1:
        return '', -1
    return content[p + 1: q], q + 1


# ── Number parsing ────────────────────────────────────────────────────────────

def _floats(text: str) -> np.ndarray:
    return np.array(_RE_FLOAT.findall(text), dtype=np.float32)


def _ints(text: str) -> list[int]:
    return list(map(int, _RE_INT.findall(text)))


# ── Fan-triangulate -1-terminated index list ──────────────────────────────────

def _to_faces(indices: list[int]) -> np.ndarray | None:
    faces: list[list[int]] = []
    face: list[int] = []
    for idx in indices:
        if idx == -1:
            n = len(face)
            if n == 3:
                faces.append(face)
            elif n > 3:                          # convex polygon → fan
                for i in range(1, n - 1):
                    faces.append([face[0], face[i], face[i + 1]])
            face = []
        else:
            face.append(idx)
    # flush final face if file omits trailing -1
    n = len(face)
    if n == 3:
        faces.append(face)
    elif n > 3:
        for i in range(1, n - 1):
            faces.append([face[0], face[i], face[i + 1]])
    return np.array(faces, dtype=np.int32) if faces else None


# ── Single Shape parser ───────────────────────────────────────────────────────

def _parse_shape(block: str) -> trimesh.Trimesh | None:
    # ── colour ──
    color = np.array([0.75, 0.75, 0.8, 1.0], dtype=np.float32)
    m = _RE_DIFFUSE.search(block)
    if m:
        color[:3] = float(m.group(1)), float(m.group(2)), float(m.group(3))

    # ── vertices (coord Coordinate { point [ ... ] }) ──
    m2 = _RE_POINT_BLOCK.search(block)
    if not m2:
        return None
    raw_pts, _ = _bracket_content(block, m2.start())
    if not raw_pts:
        return None
    verts = _floats(raw_pts)
    if len(verts) == 0 or len(verts) % 3 != 0:
        return None
    vertices = verts.reshape(-1, 3)

    # ── face indices (coordIndex [ ... ]) ──
    m3 = _RE_CIDX_BLOCK.search(block)
    if not m3:
        return None
    raw_idx, _ = _bracket_content(block, m3.start())
    if not raw_idx:
        return None
    faces = _to_faces(_ints(raw_idx))
    if faces is None or len(faces) == 0:
        return None

    # guard against out-of-range indices
    if faces.max() >= len(vertices):
        faces = faces[faces.max(axis=1) < len(vertices)]
        if len(faces) == 0:
            return None

    face_colors = np.tile(
        (color * 255).astype(np.uint8), (len(faces), 1)
    )

    return trimesh.Trimesh(
        vertices=vertices,
        faces=faces,
        face_colors=face_colors,
        process=False,
    )


# ── Public entry point ────────────────────────────────────────────────────────

def load_vrml_as_scene(filepath: str) -> trimesh.Scene:
    """
    Parse *filepath* (VRML 2.0 / VRML97) and return a trimesh.Scene.
    Optimised for large CATIA WRL exports with thousands of Shape nodes.
    """
    log.info("Reading %s into memory …", filepath)
    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        content = fh.read()

    log.info("File size in RAM: %.1f MB  (%d chars)", len(content) / 1_048_576, len(content))

    # Strip VRML line comments so they don't confuse the parsers
    content = _RE_COMMENT.sub('', content)

    scene      = trimesh.Scene()
    mesh_count = 0
    skip_count = 0
    pos        = 0
    kw         = 'Shape'
    kw_len     = len(kw)

    log.info("Scanning for Shape blocks …")

    while True:
        idx = content.find(kw, pos)
        if idx == -1:
            break

        # Reject keywords that are part of a longer word (e.g. "DEF Shape …")
        char_before = content[idx - 1] if idx > 0 else ' '
        char_after  = content[idx + kw_len] if idx + kw_len < len(content) else ' '
        if char_before.isalpha() or char_after.isalpha():
            pos = idx + kw_len
            continue

        block, next_pos = _block_after(content, idx + kw_len)
        if not block or next_pos == -1:
            pos = idx + kw_len
            continue

        try:
            mesh = _parse_shape(block)
            if mesh is not None and len(mesh.faces) > 0:
                scene.add_geometry(mesh, geom_name=f'mesh_{mesh_count}')
                mesh_count += 1
                if mesh_count % 200 == 0:
                    log.info("  … %d meshes parsed", mesh_count)
        except Exception as exc:
            skip_count += 1
            if skip_count <= 5:
                log.warning("Skipped shape #%d: %s", mesh_count + skip_count, exc)

        pos = next_pos

    log.info("Parsing complete: %d meshes  (%d skipped)", mesh_count, skip_count)
    return scene
