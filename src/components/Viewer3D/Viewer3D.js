import React, { useEffect, useRef, useCallback } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls';
import occtimportjs from 'occt-import-js';
import './Viewer3D.css';

function buildMeshFromResult(geometryMesh) {
  const geometry = new THREE.BufferGeometry();

  geometry.setAttribute(
    'position',
    new THREE.Float32BufferAttribute(geometryMesh.attributes.position.array, 3)
  );

  if (geometryMesh.attributes.normal) {
    geometry.setAttribute(
      'normal',
      new THREE.Float32BufferAttribute(geometryMesh.attributes.normal.array, 3)
    );
  }

  geometry.name = geometryMesh.name;
  const index = Uint32Array.from(geometryMesh.index.array);
  geometry.setIndex(new THREE.BufferAttribute(index, 1));

  const defaultColor = geometryMesh.color
    ? new THREE.Color(geometryMesh.color[0], geometryMesh.color[1], geometryMesh.color[2])
    : new THREE.Color(0x88aacc);

  const defaultMaterial = new THREE.MeshPhongMaterial({
    color: defaultColor,
    specular: new THREE.Color(0x333333),
    shininess: 40,
    side: THREE.DoubleSide,
  });

  const outlineMaterial = new THREE.LineBasicMaterial({ color: 0x222222, linewidth: 1 });
  let materials = [defaultMaterial];
  let edges = null;

  if (geometryMesh.brep_faces && geometryMesh.brep_faces.length > 0) {
    edges = new THREE.Group();

    for (let faceColor of geometryMesh.brep_faces) {
      const color = faceColor.color
        ? new THREE.Color(faceColor.color[0], faceColor.color[1], faceColor.color[2])
        : defaultMaterial.color;
      materials.push(new THREE.MeshPhongMaterial({ color, specular: 0x222222, shininess: 30, side: THREE.DoubleSide }));
    }

    const triangleCount = geometryMesh.index.array.length / 3;
    let triangleIndex = 0;
    let faceColorGroupIndex = 0;

    while (triangleIndex < triangleCount) {
      const firstIndex = triangleIndex;
      let lastIndex = null;
      let materialIndex = null;

      if (faceColorGroupIndex >= geometryMesh.brep_faces.length) {
        lastIndex = triangleCount;
        materialIndex = 0;
      } else if (triangleIndex < geometryMesh.brep_faces[faceColorGroupIndex].first) {
        lastIndex = geometryMesh.brep_faces[faceColorGroupIndex].first;
        materialIndex = 0;
      } else {
        lastIndex = geometryMesh.brep_faces[faceColorGroupIndex].last + 1;
        materialIndex = faceColorGroupIndex + 1;
        faceColorGroupIndex++;
      }

      geometry.addGroup(firstIndex * 3, (lastIndex - firstIndex) * 3, materialIndex);
      triangleIndex = lastIndex;

      const innerGeometry = new THREE.BufferGeometry();
      innerGeometry.setAttribute('position', geometry.attributes.position);
      if (geometryMesh.attributes.normal) {
        innerGeometry.setAttribute('normal', geometry.attributes.normal);
      }
      innerGeometry.setIndex(new THREE.BufferAttribute(index.slice(firstIndex * 3, lastIndex * 3), 1));
      const edgesGeometry = new THREE.EdgesGeometry(innerGeometry, 30);
      edges.add(new THREE.LineSegments(edgesGeometry, outlineMaterial));
    }
  }

  const mesh = new THREE.Mesh(geometry, materials.length > 1 ? materials : materials[0]);
  mesh.name = geometryMesh.name;
  mesh.userData.defaultMaterials = materials;

  if (edges) {
    edges.renderOrder = mesh.renderOrder + 1;
  }

  return { mesh, edges };
}

/**
 * Parses a STEP file text and extracts the 3-D origin of every
 * AXIS2_PLACEMENT_3D entity.  Used as a fallback when the file
 * contains no BREP / tessellated geometry (assembly-only exports).
 */
/**
 * Parses a STEP file text and extracts the 3-D origin of every
 * AXIS2_PLACEMENT_3D entity.  Used as a fallback when the file
 * contains no BREP / tessellated geometry (assembly-only exports).
 *
 * Each ITEM_DEFINED_TRANSFORMATION has a "from" frame (always at the
 * local origin, i.e. 0,0,0) and a "to" frame (the actual placement in
 * the parent's coordinate system).  We skip any point whose distance
 * from the world origin is below a threshold so those identity frames
 * are excluded and we are left with the real placement positions.
 */
function parseAssemblyPositions(text) {
  // 1. Build a map of entity-id → [x, y, z] for all CARTESIAN_POINT entities.
  const cartPoints = {};
  const cpRegex = /#(\d+)=CARTESIAN_POINT\('[^']*',\(([^)]+)\)\)/g;
  let m;
  while ((m = cpRegex.exec(text)) !== null) {
    const coords = m[2].split(',').map(s => parseFloat(s.trim()));
    if (coords.length === 3 && !coords.some(isNaN)) {
      cartPoints[m[1]] = coords;
    }
  }

  // 2. For each AXIS2_PLACEMENT_3D, grab its first reference (#origin).
  //    Deduplicate and skip points that are at (or very close to) the
  //    world origin — those are "identity from-frames", not real positions.
  const seen = new Set();
  const origins = [];
  const MIN_DIST_SQ = 1; // skip anything within 1 mm of origin
  const axisRegex = /#\d+=AXIS2_PLACEMENT_3D\('[^']*',#(\d+)/g;
  while ((m = axisRegex.exec(text)) !== null) {
    const pid = m[1];
    if (!cartPoints[pid] || seen.has(pid)) continue;
    seen.add(pid);
    const [x, y, z] = cartPoints[pid];
    if (x * x + y * y + z * z < MIN_DIST_SQ) continue; // skip identity frames
    origins.push([x, y, z]);
  }
  return origins;
}

function Viewer3D({ modelUrl, onLoadStart, onLoadComplete, onLoadError, showEdges, wireframe, backgroundColor, controlsRef }) {
  const mountRef = useRef(null);
  const rendererRef = useRef(null);
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const orbitControlsRef = useRef(null);
  const modelGroupRef = useRef(null);
  const animFrameRef = useRef(null);
  const edgeGroupsRef = useRef([]);

  const fitCameraToModel = useCallback(() => {
    const modelGroup = modelGroupRef.current;
    const camera = cameraRef.current;
    const controls = orbitControlsRef.current;
    if (!modelGroup || !camera || !controls) return;

    const box = new THREE.Box3().setFromObject(modelGroup);
    if (box.isEmpty()) return;

    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    const fov = camera.fov * (Math.PI / 180);
    const distance = (maxDim / 2) / Math.tan(fov / 2) * 2.2;

    camera.position.set(
      center.x + distance * 0.7,
      center.y + distance * 0.5,
      center.z + distance * 0.7
    );
    camera.near = distance * 0.001;
    camera.far = distance * 100;
    camera.updateProjectionMatrix();
    controls.target.copy(center);
    controls.update();
  }, []);

  // Expose controls to parent
  useEffect(() => {
    if (!controlsRef) return;
    controlsRef.current = {
      resetCamera: fitCameraToModel,
      toggleWireframe: (enabled) => {
        const modelGroup = modelGroupRef.current;
        if (!modelGroup) return;
        modelGroup.traverse((child) => {
          if (child.isMesh) {
            const mats = Array.isArray(child.material) ? child.material : [child.material];
            mats.forEach((m) => { m.wireframe = enabled; });
          }
        });
      },
      toggleEdges: (enabled) => {
        edgeGroupsRef.current.forEach((eg) => { eg.visible = enabled; });
      },
    };
  }, [controlsRef, fitCameraToModel]);

  // Initialize Three.js scene
  useEffect(() => {
    const mount = mountRef.current;
    const width = mount.clientWidth;
    const height = mount.clientHeight;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    mount.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000000);
    camera.position.set(5000, 15000, 10000);
    camera.up.set(0, 0, 1);
    cameraRef.current = camera;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf5f5f5);
    sceneRef.current = scene;

    // Grid helper — rotated to XY plane so it lies flat in a Z-up world.
    // 400 000 mm = 400 m covers large factory-floor layouts comfortably.
    const gridHelper = new THREE.GridHelper(400000, 40, 0x555577, 0x333355);
    gridHelper.rotation.x = Math.PI / 2;
    scene.add(gridHelper);

    // Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
    dirLight.position.set(10000, 20000, 10000);
    scene.add(dirLight);

    const fillLight = new THREE.DirectionalLight(0xc8d8ff, 0.4);
    fillLight.position.set(-8000, -5000, -8000);
    scene.add(fillLight);

    const modelGroup = new THREE.Group();
    scene.add(modelGroup);
    modelGroupRef.current = modelGroup;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controls.minDistance = 1;
    controls.maxDistance = 500000;
    orbitControlsRef.current = controls;

    const animate = () => {
      animFrameRef.current = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    const handleResize = () => {
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(mount);

    return () => {
      resizeObserver.disconnect();
      cancelAnimationFrame(animFrameRef.current);
      controls.dispose();
      renderer.dispose();
      if (mount.contains(renderer.domElement)) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, []);

  // Load model when URL changes
  useEffect(() => {
    if (!modelUrl) return;

    let cancelled = false;

    async function load() {
      onLoadStart && onLoadStart();
      try {
        console.log('[Viewer3D] Initialising OpenCASCADE WASM…');
        const occt = await occtimportjs({
          locateFile: (path) => {
            const base = (process.env.PUBLIC_URL || '').replace(/\/$/, '');
            return `${base}/${path}`;
          },
        });
        console.log('[Viewer3D] WASM ready. Fetching model:', modelUrl);

        const response = await fetch(modelUrl);
        if (!response.ok) throw new Error(`HTTP ${response.status} — could not fetch model`);
        const buffer = await response.arrayBuffer();
        const fileBuffer = new Uint8Array(buffer);
        console.log('[Viewer3D] File fetched — size:', fileBuffer.length, 'bytes');

        const result = occt.ReadStepFile(fileBuffer, null);
        console.log('[Viewer3D] ReadStepFile → success:', result.success,
          '| meshes:', result.meshes ? result.meshes.length : 'undefined');
        if (!result.success) throw new Error('STEP parsing failed — invalid or unsupported file');

        if (cancelled) return;

        const modelGroup = modelGroupRef.current;
        // Clear any previously loaded model.
        while (modelGroup.children.length > 0) {
          const child = modelGroup.children[0];
          if (child.geometry) child.geometry.dispose();
          modelGroup.remove(child);
        }
        edgeGroupsRef.current = [];

        let totalTriangles = 0;
        let totalVertices = 0;
        const group = new THREE.Group();

        if (result.meshes.length > 0) {
          // ── Normal path: BREP / tessellated geometry found ──────────────
          for (const meshData of result.meshes) {
            const { mesh, edges } = buildMeshFromResult(meshData);
            group.add(mesh);
            totalTriangles += meshData.index.array.length / 3;
            totalVertices += meshData.attributes.position.array.length / 3;
            if (edges) {
              group.add(edges);
              edgeGroupsRef.current.push(edges);
            }
          }
        } else {
          // ── Fallback: assembly-only export — no solid geometry ───────────
          // The file contains STEP assembly structure (PRODUCT hierarchy +
          // AXIS2_PLACEMENT_3D transforms) but no renderable BREP faces.
          // Extract every coordinate-system origin and render them as a
          // point cloud so the factory layout is still visible.
          console.warn('[Viewer3D] No mesh geometry returned. Parsing STEP text for assembly positions…');
          const fileText = new TextDecoder().decode(buffer);
          const positions = parseAssemblyPositions(fileText);
          console.log('[Viewer3D] Assembly positions found:', positions.length);

          if (positions.length === 0) {
            throw new Error(
              'No 3D geometry found in this STEP file. ' +
              'It appears to be an assembly-only export without solid bodies. ' +
              'Please re-export from CATIA with "Save as STEP with geometry" enabled.'
            );
          }

          // Build a BufferGeometry point cloud from the extracted origins.
          const posArray = new Float32Array(positions.length * 3);
          positions.forEach(([x, y, z], i) => {
            posArray[i * 3]     = x;
            posArray[i * 3 + 1] = y;
            posArray[i * 3 + 2] = z;
          });
          const ptGeom = new THREE.BufferGeometry();
          ptGeom.setAttribute('position', new THREE.Float32BufferAttribute(posArray, 3));

          // Draw a soft circle onto a canvas so the points look round, not square.
          const ptCanvas = document.createElement('canvas');
          ptCanvas.width = 64; ptCanvas.height = 64;
          const ctx = ptCanvas.getContext('2d');
          const grad = ctx.createRadialGradient(32, 32, 4, 32, 32, 28);
          grad.addColorStop(0, 'rgba(100,180,255,1)');
          grad.addColorStop(0.6, 'rgba(60,130,220,0.8)');
          grad.addColorStop(1, 'rgba(30,80,180,0)');
          ctx.fillStyle = grad;
          ctx.beginPath(); ctx.arc(32, 32, 30, 0, Math.PI * 2); ctx.fill();
          const ptTex = new THREE.CanvasTexture(ptCanvas);

          const ptMat = new THREE.PointsMaterial({
            map: ptTex,
            size: 2500,           // 2.5 m — visible at factory scale
            sizeAttenuation: true,
            transparent: true,
            depthWrite: false,
            color: 0xffffff,      // tint applied via texture colours above
          });
          group.add(new THREE.Points(ptGeom, ptMat));
          totalVertices = positions.length;

          console.warn(
            '[Viewer3D] Rendering', positions.length,
            'component-placement origins as a point cloud.',
            'Re-export the STEP file with geometry to see solid bodies.'
          );
        }

        modelGroup.add(group);
        fitCameraToModel();

        onLoadComplete && onLoadComplete({
          meshCount: result.meshes.length,
          triangles: Math.round(totalTriangles),
          vertices: Math.round(totalVertices),
          // Non-null only when no solid geometry was found in the file.
          warning: result.meshes.length === 0
            ? `No 3D geometry in this STEP file — showing ${totalVertices.toLocaleString()} component locations. ` +
              `Re-export from CATIA using File → Save As → STEP and ensure "Include geometry" is enabled.`
            : null,
        });
      } catch (err) {
        if (!cancelled) {
          console.error('[Viewer3D] Load error:', err);
          onLoadError && onLoadError(err.message || 'Unknown error');
        }
      }
    }

    load();
    return () => { cancelled = true; };
  }, [modelUrl, fitCameraToModel, onLoadStart, onLoadComplete, onLoadError]);

  // Wireframe option
  useEffect(() => {
    const modelGroup = modelGroupRef.current;
    if (!modelGroup) return;
    modelGroup.traverse((child) => {
      if (child.isMesh) {
        const mats = Array.isArray(child.material) ? child.material : [child.material];
        mats.forEach((m) => { m.wireframe = !!wireframe; });
      }
    });
  }, [wireframe]);

  // Edges visibility
  useEffect(() => {
    edgeGroupsRef.current.forEach((eg) => { eg.visible = !!showEdges; });
  }, [showEdges]);

  // Background color
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    scene.background = new THREE.Color(backgroundColor || 0xf5f5f5);
  }, [backgroundColor]);

  return (
    <div className="viewer3d-container" ref={mountRef}>
      <div className="viewer3d-hint">
        Left-click drag: Rotate &nbsp;|&nbsp; Right-click drag: Pan &nbsp;|&nbsp; Scroll: Zoom
      </div>
    </div>
  );
}

export default Viewer3D;
