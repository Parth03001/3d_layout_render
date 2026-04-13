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
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [stats, setStats] = useState(null);
  const [wireframe, setWireframe] = useState(false);
  const [showEdges, setShowEdges] = useState(true);
  const [bgIndex, setBgIndex] = useState(0);
  const viewerControlsRef = useRef(null);

  const handleLoadStart = useCallback(() => {
    setIsLoading(true);
    setLoadError(null);
    setStats(null);
  }, []);

  const handleLoadComplete = useCallback((info) => {
    setIsLoading(false);
    setStats(info);
  }, []);

  const handleLoadError = useCallback((msg) => {
    setIsLoading(false);
    setLoadError(msg);
  }, []);

  function handleFileUpload(file) {
    const url = URL.createObjectURL(file);
    setModelUrl(url);
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
          <span className="app-header-subtitle">STEP / STP CAD Model Renderer</span>
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

      <div className="app-viewer">
        <Viewer3D
          modelUrl={modelUrl}
          onLoadStart={handleLoadStart}
          onLoadComplete={handleLoadComplete}
          onLoadError={handleLoadError}
          wireframe={wireframe}
          showEdges={showEdges}
          backgroundColor={BACKGROUNDS[currentBg]}
          controlsRef={viewerControlsRef}
        />
        <LoadingOverlay isLoading={isLoading} error={loadError} />
      </div>
    </div>
  );
}

export default App;
