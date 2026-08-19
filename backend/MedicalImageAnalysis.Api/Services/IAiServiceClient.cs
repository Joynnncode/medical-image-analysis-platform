using System.Net;

namespace MedicalImageAnalysis.Api.Services;

public record SegmentationOutcome(
    int VoxelCount,
    double VolumeMl,
    double InferenceTimeMs,
    string ModelName,
    string Organ,
    string OrganDisplayName
);

/// Snapshot of a queued segmentation job as the AI service sees it.
public record SegmentationJobState(
    string JobId,
    string Status,          // queued | retrying | running | completed | failed | canceled
    bool DeadLettered,
    int Progress,
    string Stage,
    string StageLabel,
    int Attempt,
    int MaxAttempts,
    string? Error,
    SegmentationOutcome? Result,
    bool MaskAvailable
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
    /// Hands the volume to the queue. Returns as soon as it is accepted -
    /// it does not wait for the segmentation to run.
    Task<SegmentationJobState> EnqueueSegmentationAsync(
        Stream content, string fileName, string organ, CancellationToken ct = default);

    /// Current state of a job, or null if the AI service has no record of it.
    Task<SegmentationJobState?> GetJobAsync(string jobId, CancellationToken ct = default);

    Task<byte[]> DownloadMaskAsync(string jobId, CancellationToken ct = default);

    /// Drops the job and its stored payload once the mask has been collected.
    Task DeleteJobAsync(string jobId, CancellationToken ct = default);

    Task<bool> CancelJobAsync(string jobId, CancellationToken ct = default);

    Task<(List<OrganOption> Organs, string Default)> GetOrgansAsync(CancellationToken ct = default);
}
