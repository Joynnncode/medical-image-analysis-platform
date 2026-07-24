namespace MedicalImageAnalysis.Api.DTOs;

public record ScanSummaryDto(Guid Id, string FileName, string Status, DateTime UploadedAt);

public record SegmentationResultDto(
    int VoxelCount,
    double VolumeMl,
    double InferenceTimeMs,
    string ModelName
);

public record ScanDetailDto(
    Guid Id,
    string FileName,
    string Status,
    DateTime UploadedAt,
    SegmentationResultDto? Result
);
