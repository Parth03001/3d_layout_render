import React from 'react';
import './LoadingOverlay.css';

function LoadingOverlay({ isLoading, error, modelType }) {
  if (!isLoading && !error) return null;

  const isWRL = modelType === 'wrl';

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
            <p className="loading-sub">
              {isWRL ? 'Loading WRL file via Three.js VRML loader...' : 'Loading STEP file via OpenCASCADE...'}
            </p>
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
