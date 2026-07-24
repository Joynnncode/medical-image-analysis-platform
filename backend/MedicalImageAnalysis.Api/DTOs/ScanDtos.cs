namespace MedicalImageAnalysis.Api.DTOs;

public record ScanSummaryDto(Guid Id, string FileName, string Status, DateTime UploadedAt);

public record SegmentationResultDto(
    int VoxelCount,
    double VolumeMl,
    double InferenceTimeMs,
    string ModelName,
    string Organ,
    string OrganDisplayName
);

public record ScanDetailDto(
    Guid Id,
    string FileName,
    string Status,
    DateTime UploadedAt,
    SegmentationResultDto? Result
);

public record OrganOptionDto(string Key, string DisplayName);

public record OrgansListDto(List<OrganOptionDto> Organs, string Default);
