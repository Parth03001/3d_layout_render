import React, { useState, useRef, useCallback } from 'react';
import Viewer3D from './components/Viewer3D/Viewer3D';
import Toolbar from './components/Toolbar/Toolbar';
import LoadingOverlay from './components/LoadingOverlay/LoadingOverlay';
import './App.css';

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

  function handleFileUpload(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    const isWRL = ext === 'wrl';

    // Warn before loading very large WRL files — the VRML lexer is memory-
    // intensive even inside a worker, and extremely large files can still
    // exhaust the browser process.
    const WRL_WARN_BYTES = 300 * 1024 * 1024; // 300 MB
    if (isWRL && file.size > WRL_WARN_BYTES) {
      const mb = (file.size / 1024 / 1024).toFixed(0);
      const ok = window.confirm(
        `This WRL file is ${mb} MB.\n\n` +
        `Very large VRML files may cause the browser tab to crash during parsing.\n\n` +
        `Proceed anyway?`
      );
      if (!ok) return;
    }

    setModelType(isWRL ? 'wrl' : 'stp');
    setModelUrl(URL.createObjectURL(file));
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
