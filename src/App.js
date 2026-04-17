import React, { useState, useRef, useCallback } from 'react';
import Viewer3D from './components/Viewer3D/Viewer3D';
import Toolbar from './components/Toolbar/Toolbar';
import LoadingOverlay from './components/LoadingOverlay/LoadingOverlay';
import './App.css';

// Python backend base URL — override via REACT_APP_BACKEND_URL env var
const BACKEND_URL = (process.env.REACT_APP_BACKEND_URL || 'http://localhost:8000').replace(/\/$/, '');

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

    // STEP files — continue using browser-side OpenCASCADE WASM
    if (!isWRL) {
      setModelType('stp');
      setModelUrl(URL.createObjectURL(file));
      return;
    }

    // WRL files — try the Python backend first.
    // The backend parses the VRML in Python (no V8 heap limit) and returns
    // a compact GLB.  If the backend is not running we fall back to the
    // Web Worker path with a size warning.
    let backendAvailable = false;
    try {
      const r = await fetch(`${BACKEND_URL}/health`, {
        signal: AbortSignal.timeout(2500),
      });
      backendAvailable = r.ok;
    } catch { /* backend not running */ }

    if (!backendAvailable) {
      // Fall back to browser-side worker, warn for large files
      const WRL_WARN = 200 * 1024 * 1024; // 200 MB
      if (file.size > WRL_WARN) {
        const mb = (file.size / 1024 / 1024).toFixed(0);
        const ok = window.confirm(
          `The Python backend is not running.\n\n` +
          `Start it with:\n  cd backend\n  pip install -r requirements.txt\n  uvicorn main:app --port 8000\n\n` +
          `Without the backend this ${mb} MB WRL file may crash the browser tab.\n\n` +
          `Load in browser anyway?`
        );
        if (!ok) return;
      }
      setModelType('wrl');
      setModelUrl(URL.createObjectURL(file));
      return;
    }

    // ── Backend is available — upload and convert ────────────────────────
    // Show the loading overlay immediately so the user sees progress
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
            setLoadPhase('uploading');
            setLoadProgress(e.loaded / e.total);
          }
        };

        // Once all bytes are uploaded the backend is converting
        xhr.upload.onload = () => {
          setLoadPhase('converting');
          setLoadProgress(null);
        };

        xhr.onload = () => {
          if (xhr.status === 200) {
            resolve(new Uint8Array(xhr.response));
          } else {
            try {
              const msg = JSON.parse(new TextDecoder().decode(xhr.response));
              reject(new Error(msg.detail || `HTTP ${xhr.status}`));
            } catch {
              reject(new Error(`Backend returned HTTP ${xhr.status}`));
            }
          }
        };

        xhr.onerror = () => reject(new Error('Network error reaching backend'));
        xhr.send(formData);
      });

      // Backend conversion done — hand off to Viewer3D (GLTFLoader)
      // Clear the manual loading state; Viewer3D's onLoadStart takes over
      setIsLoading(false);
      setLoadPhase(null);
      setLoadProgress(null);

      const glbBlob = new Blob([glbBytes], { type: 'model/gltf-binary' });
      setModelType('glb');
      setModelUrl(URL.createObjectURL(glbBlob));

    } catch (err) {
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
