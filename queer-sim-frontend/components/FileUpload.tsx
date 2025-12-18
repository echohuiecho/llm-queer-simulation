"use client";

import { useState, useRef } from "react";

interface FileUploadProps {
  onUploadComplete: (filename: string) => void;
  currentDir: string;
}

export default function FileUpload({ onUploadComplete, currentDir }: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      uploadFiles(files);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      uploadFiles(e.target.files);
    }
  };

  const uploadFiles = async (files: FileList) => {
    setIsUploading(true);
    setError(null);

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      if (!file.name.endsWith(".txt") && !file.name.endsWith(".md") && !file.name.endsWith(".srt")) {
        setError("Only .txt, .md, and .srt files are supported.");
        continue;
      }

      const formData = new FormData();
      formData.append("file", file);

      try {
        const response = await fetch(`http://localhost:8000/api/rag/upload?dir_name=${currentDir}`, {
          method: "POST",
          body: formData,
        });

        if (!response.ok) {
          throw new Error(`Upload failed for ${file.name}`);
        }

        const result = await response.json();
        onUploadComplete(result.filename);
      } catch (err) {
        console.error(err);
        setError(err instanceof Error ? err.message : "An error occurred during upload.");
      }
    }

    setIsUploading(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return (
    <div className="mt-4">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        style={{
          border: `2px dashed ${isDragging ? "#4a9eff" : "rgba(255, 255, 255, 0.2)"}`,
          background: isDragging ? "rgba(74, 158, 255, 0.1)" : "rgba(255, 255, 255, 0.05)",
          borderRadius: 12,
          padding: "24px",
          textAlign: "center",
          cursor: "pointer",
          transition: "all 0.2s ease",
        }}
      >
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileSelect}
          style={{ display: "none" }}
          multiple
          accept=".txt,.md,.srt"
        />
        {isUploading ? (
          <div style={{ color: "#4a9eff" }}>Uploading and embedding...</div>
        ) : (
          <div>
            <div style={{ fontSize: 24, marginBottom: 8 }}>📁</div>
            <div style={{ fontSize: 14, opacity: 0.7 }}>
              Drag & drop files here, or click to browse
            </div>
            <div style={{ fontSize: 12, opacity: 0.5, marginTop: 4 }}>
              Supports .txt, .md, and .srt
            </div>
          </div>
        )}
      </div>
      {error && (
        <div style={{ color: "#ff4a4a", fontSize: 12, marginTop: 8 }}>
          {error}
        </div>
      )}
    </div>
  );
}
