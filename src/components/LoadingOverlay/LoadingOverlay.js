import React from 'react';
import './LoadingOverlay.css';

const PHASE_LABELS = {
  downloading: 'Downloading file…',
  parsing:     'Parsing geometry…',
  building:    'Building 3D meshes…',
};

function LoadingOverlay({ isLoading, error, modelType, phase, progress }) {
  if (!isLoading && !error) return null;

  const isWRL = modelType === 'wrl';
  const phaseLabel = PHASE_LABELS[phase] || (isWRL ? 'Loading VRML file…' : 'Loading STEP file…');
  const pct = progress != null ? Math.round(progress * 100) : null;

  return (
    <div className={`loading-overlay ${error ? 'loading-overlay--error' : ''}`}>
      <div className="loading-card">
        {isLoading && !error && (
          <>
            <div className="loading-spinner">
              <div className="spinner-ring"></div>
              <div className="spinner-ring spinner-ring--2"></div>
              <div className="spinner-ring spinner-ring--3"></div>
            </div>
            <p className="loading-title">Parsing 3D Model</p>
            <p className="loading-sub">{phaseLabel}</p>

            <div className="loading-progress-track">
              <div
                className={`loading-progress-bar${pct == null ? ' loading-progress-bar--indeterminate' : ''}`}
                style={pct != null ? { width: `${pct}%` } : undefined}
              />
            </div>
            {pct != null && (
              <p className="loading-pct">{pct}%</p>
            )}

            <p className="loading-note">
              {isWRL
                ? 'Large WRL files (1 GB+) may take several minutes — please wait'
                : 'Large files may take up to 30 seconds'}
            </p>
          </>
        )}

        {error && (
          <>
            <div className="loading-error-icon">&#9888;</div>
            <p className="loading-title">Load Error</p>
            <p className="loading-sub">{error}</p>
          </>
        )}
      </div>
    </div>
  );
}

export default LoadingOverlay;
