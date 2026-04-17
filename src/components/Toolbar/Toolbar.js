import React, { useState } from 'react';
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
  onLoadPath,
  stats,
}) {
  const [pathValue, setPathValue] = useState('');
  const bgLabels = { light: 'Light BG', dark: 'Dark BG', gradient: 'Gradient BG' };

  function handleFileChange(e) {
    const file = e.target.files[0];
    if (file) onFileUpload(file);
    e.target.value = '';
  }

  function handlePathSubmit(e) {
    e.preventDefault();
    const trimmed = pathValue.trim();
    if (trimmed) onLoadPath(trimmed);
  }

  return (
    <div className="toolbar-wrapper">
      {/* ── Row 1: controls ── */}
      <div className="toolbar">
        <div className="toolbar-left">
          <label className="toolbar-btn toolbar-btn--upload" title="Upload STP / STEP file">
            <input
              type="file"
              accept=".stp,.step,.STP,.STEP"
              onChange={handleFileChange}
              hidden
            />
            <span className="toolbar-icon">&#8679;</span>
            <span className="toolbar-label">Upload STEP</span>
          </label>
        </div>

        <div className="toolbar-center">
          <button className="toolbar-btn" onClick={onResetCamera} title="Reset camera">
            <span className="toolbar-icon">&#8635;</span>
            <span className="toolbar-label">Reset View</span>
          </button>

          <button
            className={`toolbar-btn ${wireframe ? 'toolbar-btn--active' : ''}`}
            onClick={onToggleWireframe}
            title="Toggle wireframe"
          >
            <span className="toolbar-icon">&#9638;</span>
            <span className="toolbar-label">Wireframe</span>
          </button>

          <button
            className={`toolbar-btn ${showEdges ? 'toolbar-btn--active' : ''}`}
            onClick={onToggleEdges}
            title="Toggle edges"
          >
            <span className="toolbar-icon">&#9640;</span>
            <span className="toolbar-label">Edges</span>
          </button>

          <button className="toolbar-btn" onClick={onCycleBackground} title="Cycle background">
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

      {/* ── Row 2: WRL path loader ── */}
      <form className="path-bar" onSubmit={handlePathSubmit}>
        <span className="path-bar__label">WRL path</span>
        <input
          className="path-bar__input"
          type="text"
          value={pathValue}
          onChange={(e) => setPathValue(e.target.value)}
          placeholder='Paste full path to .wrl file, e.g.  C:\Users\You\model.wrl'
          spellCheck={false}
        />
        <button
          className="path-bar__btn"
          type="submit"
          disabled={!pathValue.trim()}
          title="Send path to backend — file is read directly from disk (no upload)"
        >
          Load via Backend
        </button>
      </form>
    </div>
  );
}

export default Toolbar;
