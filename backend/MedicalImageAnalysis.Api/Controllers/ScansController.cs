using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using MedicalImageAnalysis.Api.Data;
using MedicalImageAnalysis.Api.DTOs;
using MedicalImageAnalysis.Api.Models;
using MedicalImageAnalysis.Api.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace MedicalImageAnalysis.Api.Controllers;

[ApiController]
[Route("api/scans")]
[Authorize]
public class ScansController : ControllerBase
{
    private readonly AppDbContext _db;
    private readonly IAiServiceClient _aiServiceClient;
    private readonly IConfiguration _config;
    private readonly ILogger<ScansController> _logger;

    public ScansController(
        AppDbContext db,
        IAiServiceClient aiServiceClient,
        IConfiguration config,
        ILogger<ScansController> logger)
    {
        _db = db;
        _aiServiceClient = aiServiceClient;
        _config = config;
        _logger = logger;
    }

    private Guid CurrentUserId =>
        Guid.Parse(User.FindFirstValue(JwtRegisteredClaimNames.Sub)!);

    private string StorageRoot => _config["Storage:Root"] ?? "./storage";

    [HttpGet]
    public async Task<ActionResult<List<ScanSummaryDto>>> List()
    {
        var scans = await _db.Scans
            .Where(s => s.UserId == CurrentUserId)
            .OrderByDescending(s => s.UploadedAt)
            .Select(s => new ScanSummaryDto(
                s.Id,
                s.FileName,
                s.Status.ToString(),
                s.UploadedAt,
                s.Jobs
                    .OrderByDescending(j => j.CreatedAt)
                    .Select(j => (int?)j.Progress)
                    .FirstOrDefault()))
            .ToListAsync();

        return Ok(scans);
    }

    [HttpPost]
    [RequestSizeLimit(200_000_000)]
    public async Task<ActionResult<ScanSummaryDto>> Upload(IFormFile file)
    {
        if (file is null || file.Length == 0)
            return BadRequest("A file is required.");

        var fileName = file.FileName;
        if (!(fileName.EndsWith(".nii", StringComparison.OrdinalIgnoreCase)
              || fileName.EndsWith(".nii.gz", StringComparison.OrdinalIgnoreCase)))
            return BadRequest("Only .nii or .nii.gz files are supported.");

        var scan = new Scan
        {
            UserId = CurrentUserId,
            FileName = fileName,
        };

        var scanDir = Path.Combine(StorageRoot, "scans", scan.Id.ToString());
        Directory.CreateDirectory(scanDir);
        var storedPath = Path.Combine(scanDir, "original.nii.gz");

        await using (var stream = System.IO.File.Create(storedPath))
        {
            await file.CopyToAsync(stream);
        }

        scan.StoredPath = storedPath;
        _db.Scans.Add(scan);
        await _db.SaveChangesAsync();

        return Ok(new ScanSummaryDto(scan.Id, scan.FileName, scan.Status.ToString(), scan.UploadedAt, null));
    }

    [HttpGet("{id:guid}")]
    public async Task<ActionResult<ScanDetailDto>> Get(Guid id)
    {
        var scan = await LoadScanAsync(id);
        if (scan is null) return NotFound();

        return Ok(ToDetailDto(scan, await LatestJobAsync(id)));
    }

    [HttpGet("{id:guid}/file")]
    public async Task<IActionResult> DownloadOriginal(Guid id)
    {
        var scan = await _db.Scans.SingleOrDefaultAsync(s => s.Id == id && s.UserId == CurrentUserId);
        if (scan is null) return NotFound();
        if (!System.IO.File.Exists(scan.StoredPath)) return NotFound();

        var bytes = await System.IO.File.ReadAllBytesAsync(scan.StoredPath);
        return File(bytes, "application/gzip", scan.FileName);
    }

    [HttpGet("{id:guid}/mask")]
    public async Task<IActionResult> DownloadMask(Guid id)
    {
        var scan = await LoadScanAsync(id);

        if (scan?.SegmentationResult is null) return NotFound();
        if (!System.IO.File.Exists(scan.SegmentationResult.MaskStoredPath)) return NotFound();

        var bytes = await System.IO.File.ReadAllBytesAsync(scan.SegmentationResult.MaskStoredPath);
        return File(bytes, "application/gzip", "mask.nii.gz");
    }

    /// Queues a segmentation run and returns immediately with 202.
    ///
    /// The work itself happens on the AI service's workers; follow
    /// GET /api/scans/{id}/job for progress. Nothing here waits on the model.
    [HttpPost("{id:guid}/segment")]
    public async Task<ActionResult<ScanDetailDto>> Segment(Guid id, [FromQuery] string organ = "spleen")
    {
        var scan = await LoadScanAsync(id);
        if (scan is null) return NotFound();
        if (!System.IO.File.Exists(scan.StoredPath)) return NotFound("Original scan file is missing.");

        var existing = await LatestJobAsync(id);
        if (existing is not null && !existing.IsTerminal)
            return Conflict("A segmentation job is already running for this scan.");

        SegmentationJobState state;
        try
        {
            await using var stream = System.IO.File.OpenRead(scan.StoredPath);
            state = await _aiServiceClient.EnqueueSegmentationAsync(stream, scan.FileName, organ);
        }
        catch (AiServiceException ex) when (ex.IsBackpressure)
        {
            _logger.LogWarning("Segmentation queue rejected scan {ScanId}: {Message}", id, ex.Message);
            Response.Headers.RetryAfter = "30";
            return StatusCode(503, "The segmentation queue is full. Please try again shortly.");
        }
        catch (AiServiceException ex) when (ex.StatusCode == System.Net.HttpStatusCode.BadRequest)
        {
            _logger.LogWarning("AI service rejected scan {ScanId}: {Message}", id, ex.Message);
            return BadRequest("The AI service rejected this scan. Check the file and organ.");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Could not queue segmentation for scan {ScanId}", id);
            return StatusCode(502, "Could not reach the segmentation service.");
        }

        var job = new SegmentationJob
        {
            ScanId = scan.Id,
            ExternalJobId = state.JobId,
            Organ = organ,
            Status = SegmentationJobStatus.Queued,
            Progress = state.Progress,
            Stage = state.Stage,
            StageLabel = state.StageLabel,
            Attempt = state.Attempt,
            MaxAttempts = state.MaxAttempts,
        };
        _db.SegmentationJobs.Add(job);
        scan.Status = ScanStatus.Queued;
        await _db.SaveChangesAsync();

        _logger.LogInformation(
            "Queued segmentation job {JobId} for scan {ScanId} (organ={Organ})",
            state.JobId, scan.Id, organ);

        return Accepted($"/api/scans/{scan.Id}/job", ToDetailDto(scan, job));
    }

    /// Cheap endpoint for progress polling - no scan or result payload.
    [HttpGet("{id:guid}/job")]
    public async Task<ActionResult<SegmentationJobDto>> GetJob(Guid id)
    {
        if (!await _db.Scans.AnyAsync(s => s.Id == id && s.UserId == CurrentUserId))
            return NotFound();

        var job = await LatestJobAsync(id);
        if (job is null) return NotFound("This scan has never been segmented.");

        return Ok(ToJobDto(job));
    }

    [HttpDelete("{id:guid}/job")]
    public async Task<IActionResult> CancelJob(Guid id)
    {
        var scan = await LoadScanAsync(id);
        if (scan is null) return NotFound();

        var job = await LatestJobAsync(id);
        if (job is null || job.IsTerminal)
            return Conflict("There is no segmentation job to cancel.");

        bool cancelled;
        try
        {
            cancelled = await _aiServiceClient.CancelJobAsync(job.ExternalJobId);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Could not cancel segmentation job {JobId}", job.ExternalJobId);
            return StatusCode(502, "Could not reach the segmentation service.");
        }

        if (!cancelled)
            return Conflict("The job had already finished or could not be cancelled.");

        job.Status = SegmentationJobStatus.Canceled;
        job.CompletedAt = DateTime.UtcNow;
        job.UpdatedAt = DateTime.UtcNow;
        scan.Status = scan.IdleStatus;
        await _db.SaveChangesAsync();

        return NoContent();
    }

    private Task<Scan?> LoadScanAsync(Guid id) =>
        _db.Scans
            .Include(s => s.SegmentationResult)
            .SingleOrDefaultAsync(s => s.Id == id && s.UserId == CurrentUserId);

    private Task<SegmentationJob?> LatestJobAsync(Guid scanId) =>
        _db.SegmentationJobs
            .Where(j => j.ScanId == scanId)
            .OrderByDescending(j => j.CreatedAt)
            .FirstOrDefaultAsync();

    private static ScanDetailDto ToDetailDto(Scan scan, SegmentationJob? job)
    {
        SegmentationResultDto? resultDto = scan.SegmentationResult is null
            ? null
            : new SegmentationResultDto(
                scan.SegmentationResult.VoxelCount,
                scan.SegmentationResult.VolumeMl,
                scan.SegmentationResult.InferenceTimeMs,
                scan.SegmentationResult.ModelName,
                scan.SegmentationResult.Organ,
                scan.SegmentationResult.OrganDisplayName
            );

        return new ScanDetailDto(
            scan.Id,
            scan.FileName,
            scan.Status.ToString(),
            scan.UploadedAt,
            resultDto,
            job is null ? null : ToJobDto(job));
    }

    private static SegmentationJobDto ToJobDto(SegmentationJob job) => new(
        job.Status.ToString(),
        job.Organ,
        job.Progress,
        job.Stage,
        job.StageLabel,
        job.Attempt,
        job.MaxAttempts,
        job.ErrorMessage,
        job.CreatedAt,
        job.UpdatedAt
    );
}
