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

    public async Task<SegmentationOutcome> SegmentAsync(byte[] fileBytes, string fileName, CancellationToken ct = default)
    {
        using var content = new MultipartFormDataContent();
        var fileContent = new ByteArrayContent(fileBytes);
        fileContent.Headers.ContentType = MediaTypeHeaderValue.Parse("application/octet-stream");
        content.Add(fileContent, "file", fileName);

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

        return new SegmentationOutcome(
            Convert.FromBase64String(maskBase64),
            voxelCount,
            volumeMl,
            inferenceTimeMs,
            modelName
        );
    }
}
