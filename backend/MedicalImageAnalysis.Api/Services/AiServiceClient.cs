using System.Net.Http.Headers;
using System.Text.Json;

namespace MedicalImageAnalysis.Api.Services;

public class AiServiceClient : IAiServiceClient
{
    private readonly HttpClient _httpClient;

    public AiServiceClient(HttpClient httpClient)
    {
        _httpClient = httpClient;
    }

    public async Task<SegmentationOutcome> SegmentAsync(
        byte[] fileBytes, string fileName, string organ, CancellationToken ct = default)
    {
        using var content = new MultipartFormDataContent();
        var fileContent = new ByteArrayContent(fileBytes);
        fileContent.Headers.ContentType = MediaTypeHeaderValue.Parse("application/octet-stream");
        content.Add(fileContent, "file", fileName);
        content.Add(new StringContent(organ), "organ");

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

    public async Task<(List<OrganOption> Organs, string Default)> GetOrgansAsync(CancellationToken ct = default)
    {
        using var response = await _httpClient.GetAsync("/organs", ct);
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
