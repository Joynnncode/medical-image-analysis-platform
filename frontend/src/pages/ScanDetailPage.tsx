import axios from "axios";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { wakeAiService } from "../api/aiService";
import { apiClient } from "../api/client";
import type { OrganOption, ScanDetail } from "../api/types";
import { NiivueViewer } from "../components/NiivueViewer";

export function ScanDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [organs, setOrgans] = useState<OrganOption[]>([]);
  const [selectedOrgan, setSelectedOrgan] = useState("spleen");
  const [loading, setLoading] = useState(true);
  const [wakingAi, setWakingAi] = useState(false);
  const [segmenting, setSegmenting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchScan = async () => {
    if (!id) return;
    const { data } = await apiClient.get<ScanDetail>(`/scans/${id}`);
    setScan(data);
  };

  const fetchOrgans = async () => {
    const { data } = await apiClient.get<{ organs: OrganOption[]; default: string }>(
      "/organs"
    );
    setOrgans(data.organs);
    setSelectedOrgan(data.default);
  };

  useEffect(() => {
    let abandoned = false;

    // The scan is the API's own to answer, so it loads regardless of what the
    // AI service is doing.
    setLoading(true);
    fetchScan().finally(() => {
      if (!abandoned) setLoading(false);
    });

    // The organ list comes from the AI service by way of the API, which makes
    // it the first thing a suspended service turns into an error: an empty
    // dropdown, before the user has clicked anything. Knock from the browser
    // first - that is the request a sleeping service holds open while it boots.
    (async () => {
      setWakingAi(true);
      const state = await wakeAiService();
      if (abandoned) return;
      setWakingAi(false);

      if (state === "unreachable") {
        setError("The AI service is not responding. Reload the page to try again.");
        return;
      }

      try {
        await fetchOrgans();
      } catch (err) {
        console.error(err);
        setError("Could not load the organ list. Reload the page to try again.");
      }
    })();

    return () => {
      abandoned = true;
    };
  }, [id]);

  const handleSegment = async () => {
    if (!id) return;
    setSegmenting(true);
    setError(null);
    try {
      const { data } = await apiClient.post<ScanDetail>(
        `/scans/${id}/segment?organ=${selectedOrgan}`
      );
      setScan(data);
    } catch (err) {
      console.error(err);
      // A 503 means the AI service was busy and never started this run -
      // telling the user it failed would be reporting work that never
      // happened, and they would have no reason to try again.
      setError(
        axios.isAxiosError(err) && err.response?.status === 503
          ? "Another segmentation is already running. Try again in a moment."
          : "Segmentation failed. Check the API / AI service logs."
      );
    } finally {
      setSegmenting(false);
    }
  };

  if (loading) return <div className="page">Loading...</div>;
  if (!scan) return <div className="page">Scan not found.</div>;

  const hasResult = scan.result !== null;

  return (
    <div className="page">
      <Link to="/" className="text-muted" style={{ fontSize: "0.85rem" }}>
        &larr; Back to scans
      </Link>
      <div className="page-header" style={{ marginTop: "0.75rem" }}>
        <h1 style={{ fontSize: "1.4rem" }}>{scan.fileName}</h1>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          <select
            className="input"
            style={{ width: "auto" }}
            value={selectedOrgan}
            onChange={(e) => setSelectedOrgan(e.target.value)}
            disabled={segmenting || wakingAi}
          >
            {organs.map((organ) => (
              <option key={organ.key} value={organ.key}>
                {organ.displayName}
              </option>
            ))}
          </select>
          <button
            className="btn btn-primary"
            onClick={handleSegment}
            disabled={segmenting || wakingAi}
          >
            {wakingAi
              ? "Waking AI service..."
              : segmenting
                ? "Running segmentation..."
                : "Run segmentation"}
          </button>
        </div>
      </div>

      {wakingAi && (
        <div className="notice">
          Waking the AI service. Free-tier hosting suspends it after about 15
          minutes idle, and starting it back up takes around 40 seconds -
          segmentation is available as soon as it answers.
        </div>
      )}

      {error && <div className="form-error">{error}</div>}

      {scan.result && (
        <div className="stats-grid">
          <div className="stat-tile">
            <div className="stat-label">Organ</div>
            <div className="stat-value" style={{ fontSize: "0.95rem" }}>
              {scan.result.organDisplayName}
            </div>
          </div>
          <div className="stat-tile">
            <div className="stat-label">Voxel count</div>
            <div className="stat-value">{scan.result.voxelCount.toLocaleString()}</div>
          </div>
          <div className="stat-tile">
            <div className="stat-label">Volume (mL)</div>
            <div className="stat-value">{scan.result.volumeMl.toFixed(1)}</div>
          </div>
          <div className="stat-tile">
            <div className="stat-label">Inference time</div>
            <div className="stat-value">{scan.result.inferenceTimeMs.toFixed(0)} ms</div>
          </div>
          <div className="stat-tile">
            <div className="stat-label">Model</div>
            <div className="stat-value" style={{ fontSize: "0.95rem" }}>
              {scan.result.modelName}
            </div>
          </div>
        </div>
      )}

      <NiivueViewer scanId={scan.id} hasMask={hasResult} />
    </div>
  );
}
