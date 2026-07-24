namespace MedicalImageAnalysis.Api.Services;

public record SegmentationOutcome(
    byte[] MaskBytes,
    int VoxelCount,
    double VolumeMl,
    double InferenceTimeMs,
    string ModelName
);

public interface IAiServiceClient
{
    Task<SegmentationOutcome> SegmentAsync(byte[] fileBytes, string fileName, CancellationToken ct = default);
}
