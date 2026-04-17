"""
3D Model Converter Backend
==========================
Two conversion modes:

1. POST /api/convert-path  { "path": "C:/full/path/to/model.wrl" }
   Backend reads the file directly from the local filesystem — zero upload
   time, no extra RAM copy.  Use this when the backend runs on the same
   machine as the browser (the normal localhost scenario).

2. POST /api/convert  (multipart file upload)
   Fall-back for when the file must be sent over the network.

Run:
    cd backend
    pip install -r requirements.txt
    uvicorn main:app --port 8000 --reload
"""

import logging
import os
import tempfile
import time

import trimesh
from fastapi import FastAPI, File, HTTPException, UploadFile
from vrml_parser import load_vrml_as_scene
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

app = FastAPI(title="3D Model Converter API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-Mesh-Count", "X-Triangle-Count", "X-Vertex-Count"],
)

SUPPORTED  = {"wrl", "vrml", "stp", "step"}
MAX_BYTES  = 4 * 1024 ** 3    # 4 GB hard cap for upload endpoint
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB read chunks


# ---------------------------------------------------------------------------
# Shared conversion helper
# ---------------------------------------------------------------------------

def _convert_path_to_glb(src_path: str, label: str) -> tuple[bytes, dict]:
    """
    Load *src_path* with trimesh and return (glb_bytes, stats_dict).
    Logs each phase with timing.
    """
    size_mb = os.path.getsize(src_path) / 1_048_576

    log.info("--- Phase: PARSE ---")
    log.info("Source    : %s  (%.1f MB)", label, size_mb)
    t_parse = time.time()

    ext = src_path.rsplit(".", 1)[-1].lower() if "." in src_path else ""

    if ext in ("wrl", "vrml"):
        # trimesh does not support VRML — use the custom parser
        log.info("Using custom VRML parser (trimesh does not support WRL)")
        scene = load_vrml_as_scene(src_path)
    else:
        loaded = trimesh.load(src_path, force="scene")
        if isinstance(loaded, trimesh.Trimesh):
            log.info("Single mesh — wrapping in Scene")
            scene = trimesh.Scene(geometry={"mesh": loaded})
        elif isinstance(loaded, trimesh.Scene):
            scene = loaded
        else:
            log.warning("Unexpected trimesh type: %s — empty scene", type(loaded))
            scene = trimesh.Scene()

    elapsed_parse = time.time() - t_parse
    log.info("Parse done: %.2f s", elapsed_parse)

    mesh_count     = len(scene.geometry)
    triangle_count = sum(len(g.faces)    for g in scene.geometry.values() if hasattr(g, "faces"))
    vertex_count   = sum(len(g.vertices) for g in scene.geometry.values() if hasattr(g, "vertices"))

    log.info("Geometry  : %d meshes | %s triangles | %s vertices",
             mesh_count, f"{triangle_count:,}", f"{vertex_count:,}")

    log.info("--- Phase: EXPORT ---")
    t_export = time.time()

    glb_bytes = scene.export(file_type="glb")

    elapsed_export = time.time() - t_export
    glb_mb  = len(glb_bytes) / 1_048_576
    ratio   = size_mb / max(glb_mb, 0.001)

    log.info("GLB size  : %.1f MB  (%.1fx smaller than source)", glb_mb, ratio)
    log.info("Export    : %.2f s", elapsed_export)
    log.info("Total conversion: %.2f s  (parse=%.2f  export=%.2f)",
             elapsed_parse + elapsed_export, elapsed_parse, elapsed_export)

    stats = {
        "mesh_count":     mesh_count,
        "triangle_count": triangle_count,
        "vertex_count":   vertex_count,
    }
    return glb_bytes, stats


def _glb_response(glb_bytes: bytes, stats: dict) -> Response:
    return Response(
        content=glb_bytes,
        media_type="model/gltf-binary",
        headers={
            "Content-Disposition": 'attachment; filename="model.glb"',
            "X-Mesh-Count":     str(stats["mesh_count"]),
            "X-Triangle-Count": str(stats["triangle_count"]),
            "X-Vertex-Count":   str(stats["vertex_count"]),
        },
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "trimesh": trimesh.__version__}


class PathRequest(BaseModel):
    path: str


@app.post("/api/convert-path")
async def convert_from_path(req: PathRequest):
    """
    Read the file directly from the local filesystem — no upload needed.
    The browser sends only the path string; the backend does all I/O locally.
    """
    t_start = time.time()

    # Strip surrounding quotes that Windows "Copy as path" adds
    raw = req.path.strip().strip('"').strip("'")
    src_path = os.path.normpath(raw)

    log.info("=== Path-based conversion ===")
    log.info("Path      : %s", src_path)

    if not os.path.isfile(src_path):
        log.error("File not found: %s", src_path)
        raise HTTPException(404, f"File not found on server: {src_path}")

    ext = src_path.rsplit(".", 1)[-1].lower() if "." in src_path else ""
    if ext not in SUPPORTED:
        raise HTTPException(400, f"Unsupported format '.{ext}'. Supported: {SUPPORTED}")

    try:
        glb_bytes, stats = _convert_path_to_glb(src_path, os.path.basename(src_path))
        log.info("=== Done in %.2f s ===", time.time() - t_start)
        return _glb_response(glb_bytes, stats)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Conversion failed")
        raise HTTPException(500, f"Conversion failed: {exc}") from exc


@app.post("/api/convert")
async def convert_upload(file: UploadFile = File(...)):
    """
    Fall-back: receive file bytes via multipart upload (use when the file
    is not on the same machine as the backend).
    """
    t_start  = time.time()
    filename = file.filename or "model.wrl"
    ext      = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wrl"

    log.info("=== Upload-based conversion ===")
    log.info("File      : %s", filename)

    if ext not in SUPPORTED:
        raise HTTPException(400, f"Unsupported format '.{ext}'")

    # Stream upload to a temp file in chunks to avoid loading 1 GB into RAM
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=f".{ext}")
    bytes_written = 0
    try:
        log.info("Streaming to temp file …")
        with os.fdopen(tmp_fd, "wb") as f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)
                bytes_written += len(chunk)
                if bytes_written > MAX_BYTES:
                    raise HTTPException(413, "File exceeds 4 GB limit")

        t_recv = time.time()
        log.info("Upload complete: %.1f MB  (%.2f s)", bytes_written / 1_048_576, t_recv - t_start)

        glb_bytes, stats = _convert_path_to_glb(tmp_path, filename)
        log.info("=== Done in %.2f s ===", time.time() - t_start)
        return _glb_response(glb_bytes, stats)

    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Conversion failed")
        raise HTTPException(500, f"Conversion failed: {exc}") from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
