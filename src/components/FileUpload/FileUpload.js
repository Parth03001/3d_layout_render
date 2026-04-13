import React, { useState, useRef } from 'react';
import './FileUpload.css';

function FileUpload({ onFile }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  function handleDrop(e) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file && isValidFile(file)) onFile(file);
  }

  function handleDragOver(e) {
    e.preventDefault();
    setDragging(true);
  }

  function handleDragLeave() {
    setDragging(false);
  }

  function handleChange(e) {
    const file = e.target.files[0];
    if (file && isValidFile(file)) onFile(file);
    e.target.value = '';
  }

  function isValidFile(file) {
    return /\.(stp|step)$/i.test(file.name);
  }

  return (
    <div
      className={`file-upload ${dragging ? 'file-upload--dragging' : ''}`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onClick={() => inputRef.current.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".stp,.step,.STP,.STEP"
        onChange={handleChange}
        hidden
      />
      <div className="file-upload-icon">&#9712;</div>
      <p className="file-upload-text">
        Drop a <strong>.stp</strong> / <strong>.step</strong> file here
      </p>
      <p className="file-upload-hint">or click to browse</p>
    </div>
  );
}

export default FileUpload;
