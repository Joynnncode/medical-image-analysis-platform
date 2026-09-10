namespace MedicalImageAnalysis.Api.Models;

/// The output of one segmentation run.
///
/// There is one of these per successful run rather than one per scan: a user
/// who segments the spleen and then the liver has asked two questions, and
/// the second answer is not a correction of the first. Re-running the same
/// organ is also a new row - what changed between the two is exactly what
/// someone would want to look at.
public class SegmentationResult
{
    public Guid Id { get; set; } = Guid.NewGuid();

    public Guid ScanId { get; set; }
    public Scan? Scan { get; set; }

    /// The run that produced this. Null only for results written before runs
    /// were tracked, where the producing job is genuinely unknown - guessing
    /// at one would invent history rather than record it.
    public Guid? JobId { get; set; }
    public SegmentationJob? Job { get; set; }

    /// Empty once the mask file has been reclaimed by the retention policy.
    /// The measurements below are the history and are never deleted; the mask
    /// is a large derived artifact that a re-run reproduces.
    public string MaskStoredPath { get; set; } = string.Empty;
    public DateTime? MaskReclaimedAt { get; set; }

    public bool HasMask => MaskReclaimedAt is null && !string.IsNullOrEmpty(MaskStoredPath);

    public string ModelName { get; set; } = string.Empty;
    public string Organ { get; set; } = string.Empty;
    public string OrganDisplayName { get; set; } = string.Empty;
    public int VoxelCount { get; set; }
    public double VolumeMl { get; set; }
    public double InferenceTimeMs { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
