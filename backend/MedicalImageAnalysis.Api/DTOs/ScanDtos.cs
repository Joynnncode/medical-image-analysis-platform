namespace MedicalImageAnalysis.Api.DTOs;

public record ScanSummaryDto(
    Guid Id,
    string FileName,
    string Status,
    DateTime UploadedAt,
    int? Progress
);

public record SegmentationResultDto(
    int VoxelCount,
    double VolumeMl,
    double InferenceTimeMs,
    string ModelName,
    string Organ,
    string OrganDisplayName,
    /// False once the retention policy has reclaimed the mask file. The
    /// measurements above are still true; there is just nothing to overlay.
    bool MaskAvailable,
    /// When this run produced these numbers. The page needs it to say which
    /// run the figures on screen came from, which is the whole point of
    /// showing an earlier result under a failed one.
    DateTime CreatedAt
);

/// One segmentation run, with whatever it produced.
///
/// Failed runs are rows here too. A history that only lists the successes
/// cannot answer "did this ever go wrong", which is most of what someone
/// opens a history for.
public record SegmentationRunDto(
    Guid Id,
    string Status,
    string Organ,
    int Attempt,
    int MaxAttempts,
    string? Error,
    DateTime CreatedAt,
    DateTime? CompletedAt,
    SegmentationResultDto? Result
);

/// Live state of the segmentation run the client is waiting on.
public record SegmentationJobDto(
    string Status,
    string Organ,
    int Progress,
    string Stage,
    string StageLabel,
    int Attempt,
    int MaxAttempts,
    string? Error,
    DateTime CreatedAt,
    DateTime UpdatedAt
);

public record ScanDetailDto(
    Guid Id,
    string FileName,
    string Status,
    DateTime UploadedAt,
    SegmentationResultDto? Result,
    SegmentationJobDto? Job
);

public record OrganOptionDto(string Key, string DisplayName);

public record OrgansListDto(List<OrganOptionDto> Organs, string Default);
