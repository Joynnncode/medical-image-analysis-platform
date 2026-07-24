namespace MedicalImageAnalysis.Api.Models;

public class SegmentationResult
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid ScanId { get; set; }
    public Scan? Scan { get; set; }
    public string MaskStoredPath { get; set; } = string.Empty;
    public string ModelName { get; set; } = string.Empty;
    public string Organ { get; set; } = string.Empty;
    public string OrganDisplayName { get; set; } = string.Empty;
    public int VoxelCount { get; set; }
    public double VolumeMl { get; set; }
    public double InferenceTimeMs { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
