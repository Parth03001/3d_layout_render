"""
3D Model Converter Backend
==========================
Receives a VRML (.wrl) or STEP (.stp/.step) file via HTTP POST,
converts it to binary glTF (.glb) using trimesh, and streams the
result back.  The browser then loads the compact GLB with THREE.js
GLTFLoader, avoiding the multi-GB string allocation that crashes
the renderer process when parsing VRML directly in JavaScript.

Run:
    cd backend
    pip install -r requirements.txt
    uvicorn main:app --port 8000 --reload
"""

import logging
import os
import shutil
import tempfile
import time

import trimesh
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

app = FastAPI(title="3D Model Converter API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # lock down for production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-Mesh-Count", "X-Triangle-Count", "X-Vertex-Count"],
)

SUPPORTED = {"wrl", "vrml", "stp", "step"}
MAX_BYTES  = 4 * 1024 ** 3   # 4 GB hard cap
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB read chunks


@app.get("/health")
async def health():
    return {"status": "ok", "trimesh": trimesh.__version__}


@app.post("/api/convert")
async def convert_model(file: UploadFile = File(...)):
    t_start   = time.time()
    filename  = file.filename or "model.wrl"
    ext       = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wrl"

    log.info("=== New conversion request ===")
    log.info("File      : %s", filename)
    log.info("Extension : %s", ext)

    if ext not in SUPPORTED:
        raise HTTPException(400, f"Unsupported format '.{ext}'. Supported: {SUPPORTED}")

    # --- Stream upload to a temp file in fixed-size chunks ---------------
    # Avoids loading the entire file into Python RAM before processing.
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=f".{ext}")
    bytes_written = 0
    try:
        log.info("Streaming upload to temp file: %s", tmp_path)
        with os.fdopen(tmp_fd, "wb") as tmp_f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                tmp_f.write(chunk)
                bytes_written += len(chunk)
                if bytes_written > MAX_BYTES:
                    raise HTTPException(413, "File exceeds 4 GB limit")

        size_mb = bytes_written / 1_048_576
        t_recv  = time.time()
        log.info("Upload complete : %.1f MB  (%.2f s)", size_mb, t_recv - t_start)

    except HTTPException:
        os.unlink(tmp_path)
        raise
    except Exception as exc:
        os.unlink(tmp_path)
        log.exception("Upload failed")
        raise HTTPException(500, f"Upload failed: {exc}") from exc

    # --- Parse with trimesh ----------------------------------------------
    try:
        log.info("--- Phase: PARSE ---")
        log.info("Calling trimesh.load('%s', force='scene') ...", filename)
        t_parse_start = time.time()

        loaded = trimesh.load(tmp_path, force="scene")

        t_parsed = time.time()
        log.info("trimesh.load() done  (%.2f s)", t_parsed - t_parse_start)

        # Normalise to Scene
        if isinstance(loaded, trimesh.Trimesh):
            log.info("Single mesh returned — wrapping in Scene")
            scene = trimesh.Scene(geometry={"mesh": loaded})
        elif isinstance(loaded, trimesh.Scene):
            scene = loaded
        else:
            log.warning("Unexpected trimesh type: %s — returning empty scene", type(loaded))
            scene = trimesh.Scene()

        mesh_count     = len(scene.geometry)
        triangle_count = sum(
            len(g.faces) for g in scene.geometry.values() if hasattr(g, "faces")
        )
        vertex_count   = sum(
            len(g.vertices) for g in scene.geometry.values() if hasattr(g, "vertices")
        )

        log.info("Geometry : %d meshes | %s triangles | %s vertices",
                 mesh_count,
                 f"{triangle_count:,}", f"{vertex_count:,}")

        # --- Export to GLB ---------------------------------------------------
        log.info("--- Phase: EXPORT ---")
        t_export_start = time.time()

        glb_bytes = scene.export(file_type="glb")

        t_done    = time.time()
        glb_mb    = len(glb_bytes) / 1_048_576
        ratio     = size_mb / max(glb_mb, 0.001)

        log.info("GLB size  : %.1f MB  (%.1fx smaller than source)", glb_mb, ratio)
        log.info("Export    : %.2f s", t_done - t_export_start)
        log.info("Total     : %.2f s  (recv=%.2f  parse=%.2f  export=%.2f)",
                 t_done - t_start,
                 t_recv  - t_start,
                 t_parsed - t_parse_start,
                 t_done   - t_export_start)
        log.info("=== Conversion complete ===")

        return Response(
            content=glb_bytes,
            media_type="model/gltf-binary",
            headers={
                "Content-Disposition": 'attachment; filename="model.glb"',
                "X-Mesh-Count":     str(mesh_count),
                "X-Triangle-Count": str(triangle_count),
                "X-Vertex-Count":   str(vertex_count),
            },
        )

    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Conversion failed after %.2f s", time.time() - t_start)
        raise HTTPException(500, f"Conversion failed: {exc}") from exc
    finally:
        try:
            os.unlink(tmp_path)
            log.info("Temp file deleted: %s", tmp_path)
        except OSError:
            pass
