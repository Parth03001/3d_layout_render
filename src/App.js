import React, { useState, useRef, useCallback } from 'react';
import Viewer3D from './components/Viewer3D/Viewer3D';
import Toolbar from './components/Toolbar/Toolbar';
import LoadingOverlay from './components/LoadingOverlay/LoadingOverlay';
import './App.css';

// Python backend base URL — override via REACT_APP_BACKEND_URL env var
const BACKEND_URL = (process.env.REACT_APP_BACKEND_URL || 'http://localhost:8003').replace(/\/$/, '');

const BACKGROUNDS = {
  light: '#f5f5f5',
  dark: '#111118',
  gradient: '#1a1a2e',
};

const BG_CYCLE = ['light', 'dark', 'gradient'];
const DEFAULT_MODEL_URL = `${process.env.PUBLIC_URL}/models/model.stp`;

function App() {
  const [modelUrl, setModelUrl] = useState(DEFAULT_MODEL_URL);
  const [modelType, setModelType] = useState('stp');
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [loadWarning, setLoadWarning] = useState(null);
  const [stats, setStats] = useState(null);
  const [wireframe, setWireframe] = useState(false);
  const [showEdges, setShowEdges] = useState(true);
  const [bgIndex, setBgIndex] = useState(0);
  const [loadPhase, setLoadPhase] = useState(null);
  const [loadProgress, setLoadProgress] = useState(null);
  const viewerControlsRef = useRef(null);

  const handleLoadStart = useCallback(() => {
    setIsLoading(true);
    setLoadError(null);
    setLoadWarning(null);
    setStats(null);
    setLoadPhase(null);
    setLoadProgress(null);
  }, []);

  const handleLoadProgress = useCallback(({ phase, progress }) => {
    setLoadPhase(phase);
    setLoadProgress(progress ?? null);
  }, []);

  const handleLoadComplete = useCallback((info) => {
    setIsLoading(false);
    setLoadPhase(null);
    setLoadProgress(null);
    setStats(info);
    setLoadWarning(info.warning || null);
  }, []);

  const handleLoadError = useCallback((msg) => {
    setIsLoading(false);
    setLoadPhase(null);
    setLoadProgress(null);
    setLoadError(msg);
  }, []);

  async function handleFileUpload(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    const isWRL = ext === 'wrl';
    const fileMB = (file.size / 1024 / 1024).toFixed(1);

    console.log(`[App] File selected: "${file.name}"  ${fileMB} MB  ext=${ext}`);

    // STEP files — continue using browser-side OpenCASCADE WASM
    if (!isWRL) {
      console.log('[App] STEP file -> browser-side OpenCASCADE (no backend needed)');
      setModelType('stp');
      setModelUrl(URL.createObjectURL(file));
      return;
    }

    // WRL files — probe the Python backend, fall back to worker if unavailable
    console.log(`[App] WRL file -> probing backend at ${BACKEND_URL}/health ...`);
    let backendAvailable = false;
    try {
      // AbortSignal.timeout() has spotty browser support — use AbortController instead
      const ctrl = new AbortController();
      const tid  = setTimeout(() => ctrl.abort(), 3000);
      const r    = await fetch(`${BACKEND_URL}/health`, { signal: ctrl.signal });
      clearTimeout(tid);
      backendAvailable = r.ok;
      console.log(`[App] Backend health -> HTTP ${r.status}  available=${backendAvailable}`);
    } catch (err) {
      console.warn('[App] Backend health check failed:', err.message,
        '-> will use browser-side worker fallback');
    }

    if (!backendAvailable) {
      console.log(`[App] Backend unavailable. File=${fileMB} MB, warn threshold=200 MB`);
      const WRL_WARN = 200 * 1024 * 1024;
      if (file.size > WRL_WARN) {
        const ok = window.confirm(
          `The Python backend is not running.\n\n` +
          `Start it with:\n  cd backend\n  pip install -r requirements.txt\n  uvicorn main:app --port 8000\n\n` +
          `Without the backend this ${fileMB} MB WRL file may crash the browser tab.\n\nLoad in browser anyway?`
        );
        if (!ok) { console.log('[App] User cancelled'); return; }
      }
      console.log('[App] -> falling back to browser-side VRML worker');
      setModelType('wrl');
      setModelUrl(URL.createObjectURL(file));
      return;
    }

    // Backend is available — upload and convert
    console.log(`[App] -> uploading ${fileMB} MB to ${BACKEND_URL}/api/convert`);
    setIsLoading(true);
    setLoadError(null);
    setLoadWarning(null);
    setStats(null);
    setLoadPhase('uploading');
    setLoadProgress(0);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const glbBytes = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', `${BACKEND_URL}/api/convert`);
        xhr.responseType = 'arraybuffer';

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            const pct = ((e.loaded / e.total) * 100).toFixed(1);
            console.log(`[App] Upload: ${pct}%  (${(e.loaded/1048576).toFixed(1)}/${(e.total/1048576).toFixed(1)} MB)`);
            setLoadPhase('uploading');
            setLoadProgress(e.loaded / e.total);
          }
        };

        xhr.upload.onload = () => {
          console.log('[App] Upload complete -> backend is now converting ...');
          setLoadPhase('converting');
          setLoadProgress(null);
        };

        xhr.onload = () => {
          if (xhr.status === 200) {
            const glbMB = (xhr.response.byteLength / 1048576).toFixed(1);
            console.log(`[App] Backend returned GLB: ${glbMB} MB`);
            resolve(new Uint8Array(xhr.response));
          } else {
            let detail = `HTTP ${xhr.status}`;
            try { detail = JSON.parse(new TextDecoder().decode(xhr.response)).detail || detail; }
            catch { /* raw */ }
            console.error('[App] Backend error:', detail);
            reject(new Error(detail));
          }
        };

        xhr.onerror = () => {
          console.error('[App] XHR network error — is the backend actually running on port 8000?');
          reject(new Error('Network error reaching backend'));
        };

        xhr.send(formData);
      });

      // Backend done — hand GLB blob URL to Viewer3D (GLTFLoader)
      console.log('[App] Backend conversion done -> handing GLB to Viewer3D (GLTFLoader)');
      setIsLoading(false);
      setLoadPhase(null);
      setLoadProgress(null);

      const glbBlob = new Blob([glbBytes], { type: 'model/gltf-binary' });
      setModelType('glb');
      setModelUrl(URL.createObjectURL(glbBlob));

    } catch (err) {
      console.error('[App] handleFileUpload error:', err);
      setIsLoading(false);
      setLoadPhase(null);
      setLoadProgress(null);
      setLoadError('Backend conversion failed: ' + err.message);
    }
  }

  async function handleLoadPath(filePath) {
    console.log(`[App] Load-by-path: "${filePath}"`);

    setIsLoading(true);
    setLoadError(null);
    setLoadWarning(null);
    setStats(null);
    setLoadPhase('converting');
    setLoadProgress(null);

    try {
      const ctrl = new AbortController();
      const tid  = setTimeout(() => ctrl.abort(), 3000);
      const health = await fetch(`${BACKEND_URL}/health`, { signal: ctrl.signal });
      clearTimeout(tid);
      if (!health.ok) throw new Error('Backend not healthy');
      console.log('[App] Backend available -> calling /api/convert-path');
    } catch (err) {
      setIsLoading(false);
      setLoadPhase(null);
      setLoadError(
        'Python backend is not running.\n' +
        'Start it with:  cd backend && uvicorn main:app --port 8000'
      );
      return;
    }

    try {
      const res = await fetch(`${BACKEND_URL}/api/convert-path`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: filePath }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const glbBuffer = await res.arrayBuffer();
      const glbMB = (glbBuffer.byteLength / 1048576).toFixed(1);
      console.log(`[App] Received GLB: ${glbMB} MB -> handing to Viewer3D`);

      setIsLoading(false);
      setLoadPhase(null);
      setLoadProgress(null);

      const glbBlob = new Blob([glbBuffer], { type: 'model/gltf-binary' });
      setModelType('glb');
      setModelUrl(URL.createObjectURL(glbBlob));

    } catch (err) {
      console.error('[App] convert-path error:', err);
      setIsLoading(false);
      setLoadPhase(null);
      setLoadProgress(null);
      setLoadError('Backend conversion failed: ' + err.message);
    }
  }

  function handleResetCamera() {
    viewerControlsRef.current?.resetCamera();
  }

  function handleToggleWireframe() {
    setWireframe((prev) => !prev);
  }

  function handleToggleEdges() {
    setShowEdges((prev) => !prev);
  }

  function handleCycleBackground() {
    setBgIndex((prev) => (prev + 1) % BG_CYCLE.length);
  }

  const currentBg = BG_CYCLE[bgIndex];

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header-brand">
          <span className="app-header-icon">&#9719;</span>
          <span className="app-header-title">3D Layout Viewer</span>
          <span className="app-header-subtitle">STEP / STP / WRL CAD Model Renderer</span>
        </div>
        <div className="app-header-meta">
          <span className="app-header-badge">OpenCASCADE + Three.js</span>
        </div>
      </header>

      <Toolbar
        onResetCamera={handleResetCamera}
        wireframe={wireframe}
        onToggleWireframe={handleToggleWireframe}
        showEdges={showEdges}
        onToggleEdges={handleToggleEdges}
        background={currentBg}
        onCycleBackground={handleCycleBackground}
        onFileUpload={handleFileUpload}
        onLoadPath={handleLoadPath}
        stats={stats}
      />

      {loadWarning && (
        <div className="warning-banner">
          <span className="warning-banner__icon">&#9888;</span>
          <span className="warning-banner__text">{loadWarning}</span>
          <button className="warning-banner__close" onClick={() => setLoadWarning(null)}>&#10005;</button>
        </div>
      )}

      <div className="app-viewer">
        <Viewer3D
          modelUrl={modelUrl}
          modelType={modelType}
          onLoadStart={handleLoadStart}
          onLoadComplete={handleLoadComplete}
          onLoadError={handleLoadError}
          onLoadProgress={handleLoadProgress}
          wireframe={wireframe}
          showEdges={showEdges}
          backgroundColor={BACKGROUNDS[currentBg]}
          controlsRef={viewerControlsRef}
        />
        <LoadingOverlay
          isLoading={isLoading}
          error={loadError}
          modelType={modelType}
          phase={loadPhase}
          progress={loadProgress}
        />
      </div>
    </div>
  );
}

export default App;
