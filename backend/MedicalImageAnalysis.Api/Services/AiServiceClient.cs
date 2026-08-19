using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;

namespace MedicalImageAnalysis.Api.Services;

public class AiServiceClient : IAiServiceClient
{
    // The AI service speaks snake_case (it's Python); everything below maps
    // onto that automatically rather than by hand-picking properties.
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _httpClient;

    public AiServiceClient(HttpClient httpClient)
    {
        _httpClient = httpClient;
    }

    public async Task<SegmentationJobState> EnqueueSegmentationAsync(
        Stream content, string fileName, string organ, CancellationToken ct = default)
    {
        using var form = new MultipartFormDataContent();
        var fileContent = new StreamContent(content);
        fileContent.Headers.ContentType = MediaTypeHeaderValue.Parse("application/octet-stream");
        form.Add(fileContent, "file", fileName);
        form.Add(new StringContent(organ), "organ");

        using var response = await _httpClient.PostAsync("/jobs", form, ct);
        await ThrowIfFailedAsync(response, "enqueue segmentation job", ct);

        var payload = await response.Content.ReadFromJsonSnakeCaseAsync<JobPayload>(ct);
        return payload!.ToState();
    }

    public async Task<SegmentationJobState?> GetJobAsync(string jobId, CancellationToken ct = default)
    {
        using var response = await _httpClient.GetAsync($"/jobs/{jobId}", ct);
        if (response.StatusCode == HttpStatusCode.NotFound) return null;
        await ThrowIfFailedAsync(response, $"read job {jobId}", ct);

        var payload = await response.Content.ReadFromJsonSnakeCaseAsync<JobPayload>(ct);
        return payload!.ToState();
    }

    public async Task<byte[]> DownloadMaskAsync(string jobId, CancellationToken ct = default)
    {
        using var response = await _httpClient.GetAsync($"/jobs/{jobId}/mask", ct);
        await ThrowIfFailedAsync(response, $"download mask for job {jobId}", ct);
        return await response.Content.ReadAsByteArrayAsync(ct);
    }

    public async Task DeleteJobAsync(string jobId, CancellationToken ct = default)
    {
        using var response = await _httpClient.DeleteAsync($"/jobs/{jobId}", ct);
        // Cleanup is best-effort - the AI service's janitor reclaims anything
        // we fail to delete here.
        if (!response.IsSuccessStatusCode && response.StatusCode != HttpStatusCode.NotFound)
            await ThrowIfFailedAsync(response, $"delete job {jobId}", ct);
    }

    public async Task<bool> CancelJobAsync(string jobId, CancellationToken ct = default)
    {
        using var response = await _httpClient.PostAsync($"/jobs/{jobId}/cancel", null, ct);
        if (response.StatusCode is HttpStatusCode.Conflict or HttpStatusCode.NotFound) return false;
        await ThrowIfFailedAsync(response, $"cancel job {jobId}", ct);
        return true;
    }

    public async Task<(List<OrganOption> Organs, string Default)> GetOrgansAsync(CancellationToken ct = default)
    {
        using var response = await _httpClient.GetAsync("/organs", ct);
        await ThrowIfFailedAsync(response, "list organs", ct);

        var payload = await response.Content.ReadFromJsonSnakeCaseAsync<OrgansPayload>(ct);
        var organs = payload!.Organs
            .Select(o => new OrganOption(o.Key, o.DisplayName))
            .ToList();

        return (organs, payload.Default);
    }

    private static async Task ThrowIfFailedAsync(
        HttpResponseMessage response, string action, CancellationToken ct)
    {
        if (response.IsSuccessStatusCode) return;

        var body = await response.Content.ReadAsStringAsync(ct);
        throw new AiServiceException(
            response.StatusCode,
            $"AI service returned {(int)response.StatusCode} when asked to {action}: {Truncate(body)}");
    }

    private static string Truncate(string value) =>
        value.Length <= 500 ? value : value[..500] + "...";

    // --- wire types --------------------------------------------------------
    // Property names map to the service's snake_case via JsonOptions above.

    private record JobPayload(
        string JobId,
        string Status,
        bool DeadLettered,
        int Progress,
        string Stage,
        string StageLabel,
        int Attempt,
        int MaxAttempts,
        string? Error,
        ResultPayload? Result,
        bool MaskAvailable)
    {
        public SegmentationJobState ToState() => new(
            JobId,
            Status,
            DeadLettered,
            Progress,
            Stage,
            StageLabel,
            Attempt,
            MaxAttempts,
            Error,
            Result is null
                ? null
                : new SegmentationOutcome(
                    Result.VoxelCount,
                    Result.VolumeMl,
                    Result.InferenceTimeMs,
                    Result.ModelName,
                    Result.Organ,
                    Result.OrganDisplayName),
            MaskAvailable);
    }

    private record ResultPayload(
        int VoxelCount,
        double VolumeMl,
        double InferenceTimeMs,
        string ModelName,
        string Organ,
        string OrganDisplayName);

    private record OrgansPayload(List<OrganPayload> Organs, string Default);

    private record OrganPayload(
        string Key,
        string DisplayName);

    internal static JsonSerializerOptions Options => JsonOptions;
}

internal static class HttpContentJsonExtensions
{
    public static async Task<T?> ReadFromJsonSnakeCaseAsync<T>(
        this HttpContent content, CancellationToken ct)
    {
        await using var stream = await content.ReadAsStreamAsync(ct);
        return await JsonSerializer.DeserializeAsync<T>(stream, AiServiceClient.Options, ct);
    }
}
