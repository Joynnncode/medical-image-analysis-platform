export interface AuthResponse {
  token: string;
  email: string;
  expiresAt: string;
}

export type ScanStatus = "Uploaded" | "Processing" | "Completed" | "Failed";

export interface ScanSummary {
  id: string;
  fileName: string;
  status: ScanStatus;
  uploadedAt: string;
}

export interface SegmentationResult {
  voxelCount: number;
  volumeMl: number;
  inferenceTimeMs: number;
  modelName: string;
  organ: string;
  organDisplayName: string;
}

export interface ScanDetail extends ScanSummary {
  result: SegmentationResult | null;
}

export interface OrganOption {
  key: string;
  displayName: string;
}

export interface OrgansList {
  organs: OrganOption[];
  default: string;
}
