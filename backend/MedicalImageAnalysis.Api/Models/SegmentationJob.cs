namespace MedicalImageAnalysis.Api.Models;

public enum SegmentationJobStatus
{
    /// Accepted here but not yet acknowledged by the AI service.
    Pending = 0,
    Queued = 1,
    /// Failed an attempt; waiting out the backoff before the next one.
    Retrying = 2,
    Running = 3,
    Completed = 4,
    Failed = 5,
    /// Failed every attempt and was moved to the AI service's dead letter queue.
    DeadLettered = 6,
    Canceled = 7,
}

/// A single segmentation run, tracked from the moment it is handed to the
/// queue until its mask has been collected.
///
/// This exists so that closing the browser tab no longer loses the work:
/// the run belongs to the system, not to an open HTTP connection, and
/// SegmentationJobMonitor picks it up wherever it got to.
public class SegmentationJob
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid ScanId { get; set; }
    public Scan? Scan { get; set; }

    /// Job id assigned by the AI service; the handle for polling it.
    public string ExternalJobId { get; set; } = string.Empty;
    public string Organ { get; set; } = string.Empty;

    public SegmentationJobStatus Status { get; set; } = SegmentationJobStatus.Pending;
    public int Progress { get; set; }
    public string Stage { get; set; } = "queued";
    public string StageLabel { get; set; } = string.Empty;
    public int Attempt { get; set; }
    public int MaxAttempts { get; set; } = 1;
    public string? ErrorMessage { get; set; }

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? LastPolledAt { get; set; }
    public DateTime? CompletedAt { get; set; }

    public bool IsTerminal => Status
        is SegmentationJobStatus.Completed
        or SegmentationJobStatus.Failed
        or SegmentationJobStatus.DeadLettered
        or SegmentationJobStatus.Canceled;
}
