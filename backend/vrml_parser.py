"""
Advanced High-Performance VRML 2.0 Parser.
Supports 4x4 Matrix Transformations (Rotation, Scale, Translation).
Optimized for massive CATIA layouts with Zero-Copy indexing.
"""

import logging
import re
import numpy as np
import trimesh
import gpu_accel
import time

log = logging.getLogger(__name__)

# ── Pre-compiled patterns ─────────────────────────────────────────────────────
_RE_COMMENT    = re.compile(r'#[^\n]*')
_RE_DIFFUSE    = re.compile(r'diffuseColor\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)')
_RE_TRANS      = re.compile(r'translation\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)')
_RE_ROTATION   = re.compile(r'rotation\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)')
_RE_SCALE      = re.compile(r'\bscale\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)')
_RE_POINT_OPEN = re.compile(r'\bpoint\s*\[')
_RE_CIDX_OPEN  = re.compile(r'\bcoordIndex\s*\[')
_RE_FLOAT      = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')
_RE_DEF_LINE   = re.compile(r'DEF\s+(?P<name>[^\s{]+)\s+(?P<type>[^\s{]+)')
_RE_USE_LINE   = re.compile(r'USE\s+(?P<name>[^\s{}]+)')
_RE_COORD_USE  = re.compile(r'coord\s+USE\s+([^\s}]+)')
_RE_GEO_USE    = re.compile(r'geometry\s+USE\s+([^\s}]+)')

# ── Matrix Math Helpers ───────────────────────────────────────────────────────

def _get_matrix(translation=None, rotation=None, scale=None):
    mat = np.eye(4, dtype=np.float32)
    if scale is not None:
        mat = mat @ np.diag([scale[0], scale[1], scale[2], 1.0]).astype(np.float32)
    if rotation is not None:
        x, y, z, angle = rotation
        s, c = np.sin(angle), np.cos(angle)
        t = 1 - c
        norm = np.sqrt(x*x + y*y + z*z)
        if norm > 1e-6:
            x, y, z = x/norm, y/norm, z/norm
            r_mat = np.array([
                [t*x*x + c,   t*x*y - s*z, t*x*z + s*y, 0],
                [t*x*y + s*z, t*y*y + c,   t*y*z - s*x, 0],
                [t*x*z - s*y, t*y*z + s*x, t*z*z + c,   0],
                [0,           0,           0,           1]
            ], dtype=np.float32)
            mat = mat @ r_mat
    if translation is not None:
        mat[0:3, 3] = translation
    return mat

def _apply_transform(vertices, matrix):
    if vertices is None or len(vertices) == 0: return vertices
    v_h = np.hstack([vertices, np.ones((len(vertices), 1), dtype=np.float32)])
    return (v_h @ matrix.T)[:, 0:3]

# ── Zero-Copy Block Parsing ───────────────────────────────────────────────────

def _block_end(content, start):
    p = content.find('{', start)
    if p == -1: return -1
    depth, curr = 1, p + 1
    while depth > 0:
        no, nc = content.find('{', curr), content.find('}', curr)
        if nc == -1: return -1
        if no != -1 and no < nc: depth += 1; curr = no + 1
        else: depth -= 1; curr = nc + 1
    return curr

def _bracket_range(content, open_re, start, end):
    m = open_re.search(content, start, end)
    if not m: return -1, -1
    p = content.find('[', m.end() - 1)
    if p == -1 or p >= end: return -1, -1
    q = content.find(']', p)
    return (p + 1, q) if q != -1 and q < end else (-1, -1)

def _parse_floats_range(content, start, end):
    chunk = content[start:end].replace(',', ' ')
    try:
        res = np.fromstring(chunk, dtype=np.float32, sep=' ')
        if res.size > 0: return res
    except: pass
    return np.array(_RE_FLOAT.findall(chunk), dtype=np.float32)

def _indices_to_faces(indices):
    if indices.size == 0: return None
    if indices[-1] != -1: indices = np.append(indices, np.int32(-1))
    neg_pos = np.where(indices == -1)[0]
    if neg_pos.size == 0: return None
    starts = np.empty(len(neg_pos), dtype=np.int64)
    starts[0], starts[1:] = 0, neg_pos[:-1] + 1
    lengths = (neg_pos - starts).astype(np.int64)
    valid = lengths >= 3
    starts, lengths = starts[valid], lengths[valid]
    if starts.size == 0: return None
    face_list = []
    tri_mask = lengths == 3
    if tri_mask.any():
        ts = starts[tri_mask].astype(np.intp)
        face_list.append(np.column_stack([indices[ts], indices[ts+1], indices[ts+2]]))
    quad_mask = lengths == 4
    if quad_mask.any():
        qs = starts[quad_mask].astype(np.intp)
        i0, i1, i2, i3 = indices[qs], indices[qs+1], indices[qs+2], indices[qs+3]
        face_list.append(np.column_stack([i0, i1, i2]))
        face_list.append(np.column_stack([i0, i2, i3]))
    return np.concatenate(face_list, axis=0).astype(np.int32) if face_list else None

def _extract_geometry_range(content, start, end, def_map):
    b_s, b_e = _bracket_range(content, _RE_POINT_OPEN, start, end)
    vertices = None
    if b_s != -1:
        vf = _parse_floats_range(content, b_s, b_e)
        if vf.size > 0 and vf.size % 3 == 0: vertices = vf.reshape(-1, 3)
    else:
        m_use = _RE_COORD_USE.search(content, start, end)
        if m_use and m_use.group(1) in def_map:
            res = def_map[m_use.group(1)]
            vertices = res if isinstance(res, np.ndarray) else res[0]
    if vertices is None: return None
    b_s, b_e = _bracket_range(content, _RE_CIDX_OPEN, start, end)
    if b_s == -1: return vertices, None
    chunk = content[b_s:b_e].replace(',', ' ')
    try:
        idx_arr = np.fromstring(chunk, dtype=np.int32, sep=' ')
    except:
        idx_arr = np.array(re.findall(r'-?\d+', chunk), dtype=np.int32)
    faces = _indices_to_faces(idx_arr)
    if faces is not None: faces = gpu_accel.validate_faces(faces, len(vertices))
    return vertices, faces

def _extract_shape_data_range(content, start, end, def_map):
    color = np.array([192, 192, 204, 255], dtype=np.uint8)
    m = _RE_DIFFUSE.search(content, start, end)
    if m:
        r, g, b = float(m.group(1)), float(m.group(2)), float(m.group(3))
        color[:3] = np.clip([r, g, b], 0, 1) * 255
    res = _extract_geometry_range(content, start, end, def_map)
    if res is None:
        m_use = _RE_GEO_USE.search(content, start, end)
        if m_use and m_use.group(1) in def_map:
            res = def_map[m_use.group(1)]
            if isinstance(res, tuple): return res[0], res[1], color
    else: return res[0], res[1], color
    return None

def load_vrml_as_scene(filepath: str) -> trimesh.Scene:
    t0 = time.time()
    log.info("Step 1/6: Reading file...")
    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        content = fh.read()
    content = _RE_COMMENT.sub('', content)
    
    vert_chunks, face_chunks, color_chunks = [], [], []
    def_map = {}
    mesh_count = v_offset = 0
    transform_stack = [(float('inf'), np.eye(4, dtype=np.float32))]
    
    kw_re = re.compile(r'\b(DEF|USE|Shape|Transform|Group)\b')
    log.info("Step 3/6: Scanning keywords...")
    matches = list(kw_re.finditer(content))
    total_kw = len(matches)
    
    log.info("Step 4/6: Processing Hierarchy...")
    i = 0
    last_log = time.time()
    while i < total_kw:
        m = matches[i]
        kw, start = m.group(1), m.start()
        
        while start > transform_stack[-1][0]:
            transform_stack.pop()

        if kw in ('Transform', 'Group'):
            n_pos = _block_end(content, start)
            if n_pos != -1:
                t_m, r_m, s_m = _RE_TRANS.search(content, start, n_pos), _RE_ROTATION.search(content, start, n_pos), _RE_SCALE.search(content, start, n_pos)
                trans = [float(t_m.group(1)), float(t_m.group(2)), float(t_m.group(3))] if t_m else None
                rot   = [float(r_m.group(1)), float(r_m.group(2)), float(r_m.group(3)), float(r_m.group(4))] if r_m else None
                scale = [float(s_m.group(1)), float(s_m.group(2)), float(s_m.group(3))] if s_m else None
                combined_mat = transform_stack[-1][1] @ _get_matrix(trans, rot, scale)
                transform_stack.append((n_pos, combined_mat))
            i += 1; continue
            
        elif kw == 'DEF':
            m_def = _RE_DEF_LINE.match(content, start)
            if m_def:
                name, dtype = m_def.group('name'), m_def.group('type')
                n_pos = _block_end(content, start)
                if n_pos != -1:
                    if dtype in ('Transform', 'Group'):
                        t_m, r_m, s_m = _RE_TRANS.search(content, start, n_pos), _RE_ROTATION.search(content, start, n_pos), _RE_SCALE.search(content, start, n_pos)
                        trans = [float(t_m.group(1)), float(t_m.group(2)), float(t_m.group(3))] if t_m else None
                        rot   = [float(r_m.group(1)), float(r_m.group(2)), float(r_m.group(3)), float(r_m.group(4))] if r_m else None
                        scale = [float(s_m.group(1)), float(s_m.group(2)), float(s_m.group(3))] if s_m else None
                        combined_mat = transform_stack[-1][1] @ _get_matrix(trans, rot, scale)
                        transform_stack.append((n_pos, combined_mat))
                        i += 1; continue
                    elif dtype == 'Coordinate':
                        b_s, b_e = _bracket_range(content, _RE_POINT_OPEN, start, n_pos)
                        if b_s != -1:
                            vf = _parse_floats_range(content, b_s, b_e)
                            if vf.size > 0 and vf.size % 3 == 0: def_map[name] = vf.reshape(-1, 3)
                    elif dtype == 'IndexedFaceSet':
                        res = _extract_geometry_range(content, start, n_pos, def_map)
                        if res: def_map[name] = res
                    elif dtype == 'Shape':
                        res = _extract_shape_data_range(content, start, n_pos, def_map)
                        if res:
                            def_map[name] = res
                            v, f, c = res
                            if f is not None:
                                vert_chunks.append(_apply_transform(v, transform_stack[-1][1]))
                                face_chunks.append(f + v_offset)
                                color_chunks.append(gpu_accel.tile_color(c, len(f)))
                                v_offset += len(v); mesh_count += 1
                    # Skip leaf DEFs
                    while i < total_kw and matches[i].start() < n_pos: i += 1
                    continue
            i += 1; continue
            
        elif kw == 'USE':
            m_u = _RE_USE_LINE.match(content, start)
            if m_u:
                name = m_u.group('name')
                if name in def_map:
                    res = def_map[name]
                    if isinstance(res, tuple) and len(res) == 3:
                        v, f, c = res
                        if f is not None:
                            vert_chunks.append(_apply_transform(v, transform_stack[-1][1]))
                            face_chunks.append(f + v_offset)
                            color_chunks.append(gpu_accel.tile_color(c, len(f)))
                            v_offset += len(v); mesh_count += 1
            i += 1; continue
            
        elif kw == 'Shape':
            n_pos = _block_end(content, start)
            if n_pos != -1:
                res = _extract_shape_data_range(content, start, n_pos, def_map)
                if res:
                    v, f, c = res
                    if f is not None:
                        vert_chunks.append(_apply_transform(v, transform_stack[-1][1]))
                        face_chunks.append(f + v_offset)
                        color_chunks.append(gpu_accel.tile_color(c, len(f)))
                        v_offset += len(v); mesh_count += 1
                while i < total_kw and matches[i].start() < n_pos: i += 1
                continue
        i += 1
        if time.time() - last_log > 10:
            log.info("  ... %d%% keywords (%d shapes)", int(i/total_kw*100), mesh_count)
            last_log = time.time()

    log.info("Step 5/6: Accumulation Done. Shapes: %d", mesh_count)
    if not vert_chunks: return trimesh.Scene()
    
    log.info("Step 6/6: GPU Merge...")
    all_v = gpu_accel.concatenate_chunks(vert_chunks, 0)
    all_f = gpu_accel.concatenate_chunks(face_chunks, 0)
    all_c = gpu_accel.concatenate_chunks(color_chunks, 0)
    
    merged = trimesh.Trimesh(vertices=all_v, faces=all_f, process=False)
    merged.visual.face_colors = all_c
    scene = trimesh.Scene()
    scene.add_geometry(merged, geom_name='layout')
    log.info("Total conversion: %.2f s", time.time() - t0)
    return scene
