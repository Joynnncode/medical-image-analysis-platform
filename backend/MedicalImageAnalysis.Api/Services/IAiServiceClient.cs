using System.Net;

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

/// Thrown when the AI service answers with an error status, so callers can
/// distinguish "busy, come back later" (503) from a genuine fault.
public class AiServiceException : Exception
{
    public AiServiceException(HttpStatusCode statusCode, string message) : base(message)
        => StatusCode = statusCode;

    public HttpStatusCode StatusCode { get; }

    public bool IsBackpressure => StatusCode == HttpStatusCode.ServiceUnavailable;
}

public interface IAiServiceClient
{
    Task<SegmentationOutcome> SegmentAsync(
        byte[] fileBytes, string fileName, string organ, CancellationToken ct = default);

    Task<(List<OrganOption> Organs, string Default)> GetOrgansAsync(CancellationToken ct = default);
}
