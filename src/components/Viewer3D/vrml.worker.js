/* eslint-disable no-restricted-globals */
import * as THREE from 'three';
import { VRMLLoader } from 'three/examples/jsm/loaders/VRMLLoader';

/**
 * Web Worker for VRML parsing.
 *
 * Running VRMLLoader here keeps the massive string allocation + recursive
 * lexer off the main thread, preventing the renderer-process OOM that causes
 * Chrome's STATUS_BREAKPOINT crash when large WRL files are loaded.
 *
 * The parsed scene's geometry is serialised into plain typed arrays and
 * transferred (zero-copy) back to the main thread, which then builds the
 * final THREE.js objects from those arrays.
 */
self.onmessage = function (event) {
  const { url } = event.data;

  let loader;
  try {
    loader = new VRMLLoader();
  } catch (e) {
    self.postMessage({ type: 'error', message: 'Failed to create VRMLLoader: ' + e.message });
    return;
  }

  loader.load(
    url,

    // onLoad
    (vrmlScene) => {
      const meshes = [];
      let meshCount = 0;
      let totalTriangles = 0;
      let totalVertices = 0;

      vrmlScene.traverse((child) => {
        if (!child.isMesh) return;
        meshCount++;

        const geo = child.geometry;
        const posAttr = geo.attributes.position;
        if (!posAttr) return;

        // Clone into new typed arrays so we can transfer them without
        // detaching buffers that THREE.js still holds references to.
        const posArr  = new Float32Array(posAttr.array);
        const normAttr = geo.attributes.normal;
        const normArr  = normAttr ? new Float32Array(normAttr.array) : null;
        const idxArr   = geo.index ? new Uint32Array(geo.index.array) : null;

        totalVertices  += posAttr.count;
        totalTriangles += idxArr ? idxArr.length / 3 : posAttr.count / 3;

        // Serialise material colours (MeshPhong / MeshBasic etc.)
        const rawMats = Array.isArray(child.material) ? child.material : [child.material];
        const colors  = rawMats.map((m) =>
          m && m.color ? [m.color.r, m.color.g, m.color.b] : null
        );

        meshes.push({ posArr, normArr, idxArr, colors, name: child.name || '' });
      });

      // Free the THREE.js scene inside the worker now that we have the raw arrays.
      vrmlScene.traverse((child) => {
        if (child.isMesh) {
          child.geometry.dispose();
          (Array.isArray(child.material) ? child.material : [child.material])
            .forEach((m) => m && m.dispose && m.dispose());
        }
      });

      // Collect all transferable ArrayBuffers for zero-copy postMessage.
      const transferables = [];
      for (const m of meshes) {
        transferables.push(m.posArr.buffer);
        if (m.normArr) transferables.push(m.normArr.buffer);
        if (m.idxArr)  transferables.push(m.idxArr.buffer);
      }

      self.postMessage(
        {
          type: 'complete',
          meshes,
          meshCount,
          totalTriangles: Math.round(totalTriangles),
          totalVertices,
        },
        transferables
      );
    },

    // onProgress (XHR ProgressEvent)
    (xhr) => {
      if (xhr.total > 0) {
        self.postMessage({ type: 'progress', loaded: xhr.loaded, total: xhr.total });
      }
    },

    // onError
    (err) => {
      self.postMessage({ type: 'error', message: String(err.message || err) });
    }
  );
};
