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
    string OrganDisplayName
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
