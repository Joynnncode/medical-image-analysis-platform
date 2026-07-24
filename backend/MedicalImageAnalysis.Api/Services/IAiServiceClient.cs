namespace MedicalImageAnalysis.Api.Services;

public record SegmentationOutcome(
    byte[] MaskBytes,
    int VoxelCount,
    double VolumeMl,
    double InferenceTimeMs,
    string ModelName,
    string Organ,
    string OrganDisplayName
);

public record OrganOption(string Key, string DisplayName);

public interface IAiServiceClient
{
    Task<SegmentationOutcome> SegmentAsync(
        byte[] fileBytes, string fileName, string organ, CancellationToken ct = default);

    Task<(List<OrganOption> Organs, string Default)> GetOrgansAsync(CancellationToken ct = default);
}
