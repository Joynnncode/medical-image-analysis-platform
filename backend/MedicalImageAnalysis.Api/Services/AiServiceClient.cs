using System.Net.Http.Headers;
using System.Text.Json;

namespace MedicalImageAnalysis.Api.Services;

public class AiServiceClient : IAiServiceClient
{
    // A free-tier host suspends a service that has been idle and answers the
    // first request against it with an error while it boots, rather than
    // holding the connection until it is ready. Left alone that turns every
    // first segmentation after a quiet spell into a failure the user has to
    // click through - so wait for the service to wake before sending work.
    // Measured against Render: a suspended service does not answer with an
    // error while it boots - the connection is simply held open until it is
    // ready. Six probes with a 5s timeout all timed out during a boot, while
    // one long request was held for 41s and then returned 200. So waking it
    // means asking once and waiting, not polling: any per-request timeout
    // shorter than the boot never sees the answer.
    private static readonly TimeSpan WakeProbeTimeout = TimeSpan.FromSeconds(90);
    private const int WakeAttempts = 2;
    private const int TransientRetries = 3;

    private readonly HttpClient _httpClient;

    public AiServiceClient(HttpClient httpClient)
    {
        _httpClient = httpClient;
    }

    /// Waits for the AI service to be ready to serve, so the caller's real
    /// request doesn't land on one that is still starting.
    ///
    /// Gives up quietly once the attempts are spent: the request that follows
    /// is a better place to report a service that is genuinely down.
    private async Task WaitUntilAwakeAsync(CancellationToken ct)
    {
        for (var attempt = 1; attempt <= WakeAttempts; attempt++)
        {
            // Bound each attempt separately. If the host's edge gives up on a
            // boot that is taking too long, the boot itself keeps going, so a
            // second ask usually lands on a service that is now up.
            using var attemptCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            attemptCts.CancelAfter(WakeProbeTimeout);

            try
            {
                using var response = await _httpClient.GetAsync("/health", attemptCts.Token);
                if (response.IsSuccessStatusCode) return;
            }
            catch (HttpRequestException) { }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested) { }
        }
    }

    public async Task<SegmentationOutcome> SegmentAsync(
        byte[] fileBytes, string fileName, string organ, CancellationToken ct = default)
    {
        using var content = new MultipartFormDataContent();
        var fileContent = new ByteArrayContent(fileBytes);
        fileContent.Headers.ContentType = MediaTypeHeaderValue.Parse("application/octet-stream");
        content.Add(fileContent, "file", fileName);
        content.Add(new StringContent(organ), "organ");

        // Wake it first: a retry here would re-upload the volume and re-run a
        // minutes-long inference, so it is worth paying for the certainty.
        await WaitUntilAwakeAsync(ct);

        using var response = await _httpClient.PostAsync("/segment", content, ct);
        if (!response.IsSuccessStatusCode)
        {
            var error = await response.Content.ReadAsStringAsync(ct);
            throw new InvalidOperationException($"AI service returned {response.StatusCode}: {error}");
        }

        await using var stream = await response.Content.ReadAsStreamAsync(ct);
        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct);
        var root = doc.RootElement;

        var maskBase64 = root.GetProperty("mask_base64").GetString()!;
        var voxelCount = root.GetProperty("voxel_count").GetInt32();
        var volumeMl = root.GetProperty("volume_ml").GetDouble();
        var inferenceTimeMs = root.GetProperty("inference_time_ms").GetDouble();
        var modelName = root.GetProperty("model_name").GetString()!;
        var organKey = root.GetProperty("organ").GetString()!;
        var organDisplayName = root.GetProperty("organ_display_name").GetString()!;

        return new SegmentationOutcome(
            Convert.FromBase64String(maskBase64),
            voxelCount,
            volumeMl,
            inferenceTimeMs,
            modelName,
            organKey,
            organDisplayName
        );
    }

    private async Task<HttpResponseMessage> GetWithRetryAsync(string path, CancellationToken ct)
    {
        var delay = TimeSpan.FromSeconds(2);

        for (var attempt = 1; ; attempt++)
        {
            HttpResponseMessage? response = null;
            try
            {
                response = await _httpClient.GetAsync(path, ct);
                if (response.IsSuccessStatusCode || attempt > TransientRetries) return response;
            }
            catch (Exception ex) when (
                attempt <= TransientRetries
                && (ex is HttpRequestException
                    || (ex is TaskCanceledException && !ct.IsCancellationRequested)))
            {
                // Falls through to the delay below.
            }

            response?.Dispose();
            await Task.Delay(delay, ct);
            delay = TimeSpan.FromSeconds(Math.Min(delay.TotalSeconds * 2, 10));
        }
    }

    public async Task<(List<OrganOption> Organs, string Default)> GetOrgansAsync(CancellationToken ct = default)
    {
        // Cheap and idempotent, so this one just retries - it is the first
        // call the scan page makes, and it is usually what wakes the service.
        using var response = await GetWithRetryAsync("/organs", ct);
        response.EnsureSuccessStatusCode();

        await using var stream = await response.Content.ReadAsStreamAsync(ct);
        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct);
        var root = doc.RootElement;

        var organs = root.GetProperty("organs")
            .EnumerateArray()
            .Select(o => new OrganOption(
                o.GetProperty("key").GetString()!,
                o.GetProperty("display_name").GetString()!))
            .ToList();

        var defaultOrgan = root.GetProperty("default").GetString()!;

        return (organs, defaultOrgan);
    }
}
