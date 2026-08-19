export interface AuthResponse {
  token: string;
  email: string;
  expiresAt: string;
}

export type ScanStatus = "Uploaded" | "Queued" | "Processing" | "Completed" | "Failed";

interface ScanBase {
  id: string;
  fileName: string;
  status: ScanStatus;
  uploadedAt: string;
}

/** Row in the scan list. `progress` is the latest job's, if there is one. */
export interface ScanSummary extends ScanBase {
  progress: number | null;
}

export interface SegmentationResult {
  voxelCount: number;
  volumeMl: number;
  inferenceTimeMs: number;
  modelName: string;
  organ: string;
  organDisplayName: string;
}

export type SegmentationJobStatus =
  | "Pending"
  | "Queued"
  | "Retrying"
  | "Running"
  | "Completed"
  | "Failed"
  | "DeadLettered"
  | "Canceled";

/** A queued segmentation run. Progress is reported by the worker itself. */
export interface SegmentationJob {
  status: SegmentationJobStatus;
  organ: string;
  progress: number;
  stage: string;
  stageLabel: string;
  attempt: number;
  maxAttempts: number;
  error: string | null;
  createdAt: string;
  updatedAt: string;
}

/** Statuses where the job is still expected to make progress. */
export const ACTIVE_JOB_STATUSES: ReadonlySet<SegmentationJobStatus> = new Set([
  "Pending",
  "Queued",
  "Retrying",
  "Running",
]);

export function isJobActive(job: SegmentationJob | null): boolean {
  return job !== null && ACTIVE_JOB_STATUSES.has(job.status);
}

export interface ScanDetail extends ScanBase {
  result: SegmentationResult | null;
  job: SegmentationJob | null;
}

export interface OrganOption {
  key: string;
  displayName: string;
}

export interface OrgansList {
  organs: OrganOption[];
  default: string;
}
