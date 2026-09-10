namespace MedicalImageAnalysis.Api.Models;

public enum ScanStatus
{
    Uploaded = 0,
    Processing = 1,
    Completed = 2,
    Failed = 3,
    // Appended, not inserted: these are persisted as ints, so renumbering
    // the existing members would silently rewrite the meaning of every row.
    Queued = 4,
}

public class Scan
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid UserId { get; set; }
    public User? User { get; set; }
    public string FileName { get; set; } = string.Empty;
    public string StoredPath { get; set; } = string.Empty;
    public ScanStatus Status { get; set; } = ScanStatus.Uploaded;
    public DateTime UploadedAt { get; set; } = DateTime.UtcNow;

    /// Every result this scan has ever produced, one per successful run.
    public List<SegmentationResult> Results { get; set; } = new();

    /// Every segmentation run ever queued for this scan, newest last.
    public List<SegmentationJob> Jobs { get; set; } = new();

    /// The result a viewer sees by default. Requires Results to be loaded.
    public SegmentationResult? LatestResult =>
        Results.OrderByDescending(r => r.CreatedAt).FirstOrDefault();

    /// What the scan's status reverts to when no job is in flight.
    /// Requires Results to have been loaded.
    public ScanStatus IdleStatus =>
        Results.Count > 0 ? ScanStatus.Completed : ScanStatus.Uploaded;
}
