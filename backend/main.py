"""
3D Model Converter Backend
==========================
Receives a VRML (.wrl) or STEP (.stp/.step) file via HTTP POST,
converts it to binary glTF (.glb) using trimesh, and streams the
result back.  The browser then loads the compact GLB with THREE.js
GLTFLoader — avoiding the multi-GB string allocation that crashes
the renderer process when parsing VRML directly in JavaScript.

Run:
    cd backend
    pip install -r requirements.txt
    uvicorn main:app --port 8000 --reload
"""

import io
import logging
import os
import tempfile

import numpy as np
import trimesh
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="3D Model Converter API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten for production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-Mesh-Count", "X-Triangle-Count", "X-Vertex-Count"],
)

SUPPORTED = {"wrl", "vrml", "stp", "step"}
MAX_BYTES  = 4 * 1024 ** 3  # 4 GB hard cap


@app.get("/health")
async def health():
    return {"status": "ok", "trimesh": trimesh.__version__}


@app.post("/api/convert")
async def convert_model(file: UploadFile = File(...)):
    filename = file.filename or "model.wrl"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wrl"

    if ext not in SUPPORTED:
        raise HTTPException(400, f"Unsupported format '.{ext}'. Supported: {SUPPORTED}")

    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "File exceeds 4 GB limit")

    size_mb = len(raw) / 1_048_576
    log.info("Received %s  (%.1f MB)", filename, size_mb)

    # Write to a temp file so trimesh can detect format by extension
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        log.info("Parsing with trimesh …")
        loaded = trimesh.load(tmp_path, force="scene")

        # trimesh.load can return a Scene (multi-mesh) or a single Trimesh
        if isinstance(loaded, trimesh.Trimesh):
            scene = trimesh.Scene(geometry={"mesh": loaded})
        elif isinstance(loaded, trimesh.Scene):
            scene = loaded
        else:
            # Point cloud or path — wrap as best we can
            scene = trimesh.Scene()

        mesh_count     = len(scene.geometry)
        triangle_count = sum(len(g.faces)    for g in scene.geometry.values()
                             if hasattr(g, "faces"))
        vertex_count   = sum(len(g.vertices) for g in scene.geometry.values()
                             if hasattr(g, "vertices"))

        log.info("Parsed: %d meshes, %d triangles, %d vertices",
                 mesh_count, triangle_count, vertex_count)
        log.info("Exporting to GLB …")

        glb_bytes = scene.export(file_type="glb")
        log.info("GLB ready: %.1f MB  (%.1fx smaller than source)",
                 len(glb_bytes) / 1_048_576, len(raw) / max(len(glb_bytes), 1))

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
        log.exception("Conversion failed")
        raise HTTPException(500, f"Conversion failed: {exc}") from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
