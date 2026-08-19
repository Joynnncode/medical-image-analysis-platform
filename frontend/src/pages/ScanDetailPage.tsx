import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AxiosError } from "axios";
import { apiClient } from "../api/client";
import type { OrganOption, ScanDetail, SegmentationJob } from "../api/types";
import { isJobActive } from "../api/types";
import { NiivueViewer } from "../components/NiivueViewer";

const POLL_INTERVAL_MS = 1500;

function enqueueError(err: unknown): string {
  const status = (err as AxiosError)?.response?.status;
  if (status === 409) return "A segmentation job is already running for this scan.";
  if (status === 503) return "The segmentation queue is busy right now. Try again in a moment.";
  return "Could not queue segmentation. Check the API / AI service logs.";
}

function failureMessage(job: SegmentationJob): string {
  const attempts =
    job.maxAttempts > 1 ? ` after ${job.attempt} of ${job.maxAttempts} attempts` : "";
  const suffix =
    job.status === "DeadLettered"
      ? " It has been moved to the dead letter queue for inspection."
      : "";
  return `Segmentation failed${attempts}: ${job.error ?? "unknown error"}.${suffix}`;
}

export function ScanDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [job, setJob] = useState<SegmentationJob | null>(null);
  const [organs, setOrgans] = useState<OrganOption[]>([]);
  const [selectedOrgan, setSelectedOrgan] = useState("spleen");
  const [loading, setLoading] = useState(true);
  const [enqueueing, setEnqueueing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchScan = async () => {
    if (!id) return;
    const { data } = await apiClient.get<ScanDetail>(`/scans/${id}`);
    setScan(data);
    setJob(data.job);
    // A job that failed before this page was even opened should still say so.
    if (data.job && (data.job.status === "Failed" || data.job.status === "DeadLettered")) {
      setError(failureMessage(data.job));
    }
  };

  const fetchOrgans = async () => {
    const { data } = await apiClient.get<{ organs: OrganOption[]; default: string }>(
      "/organs"
    );
    setOrgans(data.organs);
    setSelectedOrgan(data.default);
  };

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchScan(), fetchOrgans()]).finally(() => setLoading(false));
  }, [id]);

  // Follow the job to its conclusion. The run belongs to the server, so this
  // picks up whatever is in flight - including a job started before this page
  // was loaded, or one still going after a refresh.
  useEffect(() => {
    if (!id || !isJobActive(job)) return;

    let abandoned = false;
    const timer = setTimeout(async () => {
      try {
        const { data } = await apiClient.get<SegmentationJob>(`/scans/${id}/job`);
        if (abandoned) return;
        setJob(data);

        if (!isJobActive(data)) {
          if (data.status === "Failed" || data.status === "DeadLettered") {
            setError(failureMessage(data));
          }
          await fetchScan();
        }
      } catch (err) {
        if (abandoned) return;
        console.error(err);
        setError("Lost track of the segmentation job. Reload to check its status.");
        setJob(null);
      }
    }, POLL_INTERVAL_MS);

    return () => {
      abandoned = true;
      clearTimeout(timer);
    };
  }, [id, job]);

  const handleSegment = async () => {
    if (!id) return;
    setEnqueueing(true);
    setError(null);
    try {
      const { data } = await apiClient.post<ScanDetail>(
        `/scans/${id}/segment?organ=${selectedOrgan}`
      );
      setScan(data);
      setJob(data.job);
    } catch (err) {
      console.error(err);
      setError(enqueueError(err));
    } finally {
      setEnqueueing(false);
    }
  };

  const handleCancel = async () => {
    if (!id) return;
    setCancelling(true);
    try {
      await apiClient.delete(`/scans/${id}/job`);
      await fetchScan();
    } catch (err) {
      console.error(err);
      setError("Could not cancel the job - it may have already finished.");
    } finally {
      setCancelling(false);
    }
  };

  if (loading) return <div className="page">Loading...</div>;
  if (!scan) return <div className="page">Scan not found.</div>;

  const active = isJobActive(job);
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
            disabled={active || enqueueing}
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
            disabled={active || enqueueing}
          >
            {active ? "Segmentation queued" : enqueueing ? "Queueing..." : "Run segmentation"}
          </button>
        </div>
      </div>

      {job && active && (
        <div className="job-progress">
          <div className="job-progress-head">
            <span>{job.stageLabel || job.stage}</span>
            <span className="job-progress-percent">
              {job.status === "Queued" || job.status === "Pending" ? "" : `${job.progress}%`}
            </span>
          </div>
          <div className="progress-track">
            <div
              className={
                job.status === "Queued" || job.status === "Pending"
                  ? "progress-bar is-indeterminate"
                  : "progress-bar"
              }
              style={{ width: `${job.progress}%` }}
            />
          </div>
          <div className="job-progress-meta">
            <span>
              {job.status === "Retrying"
                ? `Attempt ${job.attempt} failed - retrying (up to ${job.maxAttempts})`
                : job.maxAttempts > 1 && job.attempt > 1
                  ? `Attempt ${job.attempt} of ${job.maxAttempts}`
                  : "You can close this page - the job keeps running."}
            </span>
            <button className="btn-link" onClick={handleCancel} disabled={cancelling}>
              {cancelling ? "Cancelling..." : "Cancel"}
            </button>
          </div>
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

      <NiivueViewer
        scanId={scan.id}
        hasMask={hasResult}
        maskVersion={job?.status === "Completed" ? job.updatedAt : undefined}
      />
    </div>
  );
}
