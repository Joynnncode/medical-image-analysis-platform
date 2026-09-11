import type { OrganOption, SegmentationJobStatus, SegmentationRun } from "../api/types";

interface Props {
  runs: SegmentationRun[];
  /** Used to name runs that never produced a result, which is where the
      display name otherwise comes from. */
  organs: OrganOption[];
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

export function RunHistory({ runs, organs, selectedRunId, onSelect }: Props) {
  // A failed or cancelled run has no result to carry a display name, so look
  // the key up; fall back to the key itself if the organ list did not load.
  const organName = (run: SegmentationRun) =>
    run.result?.organDisplayName ??
    organs.find((o) => o.key === run.organ)?.displayName ??
    run.organ;

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
                <span className="run-organ">{organName(run)}</span>
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
