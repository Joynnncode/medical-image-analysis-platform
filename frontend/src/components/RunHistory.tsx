import type { SegmentationJobStatus, SegmentationRun } from "../api/types";

interface Props {
  runs: SegmentationRun[];
  /** The run currently being viewed. */
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
}

const BADGE_CLASS: Record<SegmentationJobStatus, string> = {
  Pending: "badge-queued",
  Queued: "badge-queued",
  Retrying: "badge-queued",
  Running: "badge-processing",
  Completed: "badge-completed",
  Failed: "badge-failed",
  DeadLettered: "badge-failed",
  Canceled: "badge-uploaded",
};

function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function RunHistory({ runs, selectedRunId, onSelect }: Props) {
  return (
    <div className="run-history">
      <div className="run-history-head">
        {runs.length} run{runs.length === 1 ? "" : "s"} on this scan
      </div>
      <ul className="run-list">
        {runs.map((run) => {
          const selected = run.id === selectedRunId;
          return (
            <li key={run.id}>
              <button
                type="button"
                className={selected ? "run-row is-selected" : "run-row"}
                onClick={() => onSelect(run.id)}
                aria-current={selected}
              >
                <span className={`badge ${BADGE_CLASS[run.status]}`}>{run.status}</span>
                <span className="run-organ">
                  {run.result?.organDisplayName ?? run.organ}
                </span>
                <span className="run-detail text-muted">
                  {run.result
                    ? `${run.result.volumeMl.toFixed(1)} mL`
                    : run.error
                      ? run.error
                      : "no result"}
                </span>
                <span className="run-when text-muted">{when(run.createdAt)}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
