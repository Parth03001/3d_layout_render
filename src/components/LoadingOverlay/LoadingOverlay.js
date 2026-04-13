import React from 'react';
import './LoadingOverlay.css';

function LoadingOverlay({ isLoading, error }) {
  if (!isLoading && !error) return null;

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
            <p className="loading-sub">Loading STEP file via OpenCASCADE...</p>
            <p className="loading-note">Large files may take up to 30 seconds</p>
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
