namespace MedicalImageAnalysis.Api.Models;

public enum ScanStatus
{
    Uploaded,
    Processing,
    Completed,
    Failed,
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

    public SegmentationResult? SegmentationResult { get; set; }
}
