import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "../api/client";
import type { ScanSummary } from "../api/types";

function statusBadgeClass(status: string) {
  return `badge badge-${status.toLowerCase()}`;
}

export function DashboardPage() {
  const [scans, setScans] = useState<ScanSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchScans = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get<ScanSummary[]>("/scans");
      setScans(data);
    } catch (err) {
      console.error(err);
      setError("Failed to load scans.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchScans();
  }, []);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      await apiClient.post("/scans", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      await fetchScans();
    } catch (err) {
      console.error(err);
      setError("Upload failed. Only .nii / .nii.gz files are supported.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h1 style={{ fontSize: "1.6rem" }}>Your scans</h1>
      </div>

      <div className="disclaimer">
        Educational / demo project only. Not a medical device and not intended for clinical
        diagnosis or real patient data.
      </div>

      <div className="upload-dropzone">
        <p style={{ marginBottom: "1rem" }}>Upload a CT scan in NIfTI format (.nii or .nii.gz)</p>
        <input
          ref={fileInputRef}
          type="file"
          accept=".nii,.nii.gz,.gz"
          onChange={handleFileChange}
          disabled={uploading}
          style={{ display: "none" }}
          id="file-upload"
        />
        <label htmlFor="file-upload" className="btn btn-primary" style={{ cursor: "pointer" }}>
          {uploading ? "Uploading..." : "Choose file"}
        </label>
      </div>

      {error && <div className="form-error">{error}</div>}

      {loading ? (
        <p className="text-muted">Loading...</p>
      ) : scans.length === 0 ? (
        <p className="text-muted">No scans yet. Upload one to get started.</p>
      ) : (
        <div className="scan-list">
          {scans.map((scan) => (
            <Link key={scan.id} to={`/scans/${scan.id}`} className="scan-row">
              <div className="scan-row-info">
                <span>{scan.fileName}</span>
                <span className="scan-row-date">
                  {new Date(scan.uploadedAt).toLocaleString()}
                </span>
              </div>
              <span className={statusBadgeClass(scan.status)}>{scan.status}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
