import React from 'react';
import './Toolbar.css';

function Toolbar({
  onResetCamera,
  wireframe,
  onToggleWireframe,
  showEdges,
  onToggleEdges,
  background,
  onCycleBackground,
  onFileUpload,
  stats,
}) {
  const bgLabels = { light: 'Light BG', dark: 'Dark BG', gradient: 'Gradient BG' };

  function handleFileChange(e) {
    const file = e.target.files[0];
    if (file) onFileUpload(file);
    e.target.value = '';
  }

  return (
    <div className="toolbar">
      <div className="toolbar-left">
        <label className="toolbar-btn toolbar-btn--upload" title="Upload STP / STEP / WRL file">
          <input
            type="file"
            accept=".stp,.step,.STP,.STEP,.wrl,.WRL"
            onChange={handleFileChange}
            hidden
          />
          <span className="toolbar-icon">&#8679;</span>
          <span className="toolbar-label">Upload Model</span>
        </label>
      </div>

      <div className="toolbar-center">
        <button
          className="toolbar-btn"
          onClick={onResetCamera}
          title="Reset camera to fit model"
        >
          <span className="toolbar-icon">&#8635;</span>
          <span className="toolbar-label">Reset View</span>
        </button>

        <button
          className={`toolbar-btn ${wireframe ? 'toolbar-btn--active' : ''}`}
          onClick={onToggleWireframe}
          title="Toggle wireframe mode"
        >
          <span className="toolbar-icon">&#9638;</span>
          <span className="toolbar-label">Wireframe</span>
        </button>

        <button
          className={`toolbar-btn ${showEdges ? 'toolbar-btn--active' : ''}`}
          onClick={onToggleEdges}
          title="Toggle edges overlay"
        >
          <span className="toolbar-icon">&#9640;</span>
          <span className="toolbar-label">Edges</span>
        </button>

        <button
          className="toolbar-btn"
          onClick={onCycleBackground}
          title="Cycle background theme"
        >
          <span className="toolbar-icon">&#9788;</span>
          <span className="toolbar-label">{bgLabels[background]}</span>
        </button>
      </div>

      <div className="toolbar-right">
        {stats && (
          <div className="toolbar-stats">
            <span className="stats-item">
              <span className="stats-label">Meshes</span>
              <span className="stats-value">{stats.meshCount.toLocaleString()}</span>
            </span>
            <span className="stats-item">
              <span className="stats-label">Triangles</span>
              <span className="stats-value">{stats.triangles.toLocaleString()}</span>
            </span>
            <span className="stats-item">
              <span className="stats-label">Vertices</span>
              <span className="stats-value">{stats.vertices.toLocaleString()}</span>
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

export default Toolbar;
