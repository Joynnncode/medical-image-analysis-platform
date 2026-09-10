using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using MedicalImageAnalysis.Api.Data;
using MedicalImageAnalysis.Api.DTOs;
using MedicalImageAnalysis.Api.Models;
using MedicalImageAnalysis.Api.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Npgsql;

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

        var result = scan?.LatestResult;
        if (result is null) return NotFound();

        // Reclaimed by the retention policy: the run and its measurements are
        // still on the record, the file is not. Distinguishable from "no such
        // scan" on purpose - the two mean different things to a caller.
        if (!result.HasMask) return StatusCode(410, "The mask for this run is no longer stored.");
        if (!System.IO.File.Exists(result.MaskStoredPath)) return NotFound();

        var bytes = await System.IO.File.ReadAllBytesAsync(result.MaskStoredPath);
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

        // Claim the scan first, then do the expensive part. Reading the latest
        // job and inserting afterwards lets two simultaneous requests both pass
        // the read and both enqueue: two full inferences, and a second result
        // nobody asked for. The insert is the claim - a partial unique index on
        // ScanId over the non-terminal statuses means the second one cannot
        // land, so the database decides the winner rather than the interleaving
        // of two application-level reads.
        var job = new SegmentationJob
        {
            ScanId = scan.Id,
            Organ = organ,
            Status = SegmentationJobStatus.Pending,
        };
        _db.SegmentationJobs.Add(job);

        try
        {
            await _db.SaveChangesAsync();
        }
        catch (DbUpdateException ex) when (IsUniqueViolation(ex))
        {
            _db.Entry(job).State = EntityState.Detached;
            _logger.LogInformation(
                "Refused a second segmentation for scan {ScanId}: one is already in flight", id);
            return Conflict("A segmentation job is already running for this scan.");
        }

        SegmentationJobState state;
        try
        {
            await using var stream = System.IO.File.OpenRead(scan.StoredPath);
            state = await _aiServiceClient.EnqueueSegmentationAsync(stream, scan.FileName, organ);
        }
        catch (AiServiceException ex) when (ex.IsBackpressure)
        {
            // Nothing was queued, so this is a refusal and not a failed run.
            // Drop the claim rather than leaving a Failed job on the scan's
            // record for work that was never attempted.
            _logger.LogWarning("Segmentation queue rejected scan {ScanId}: {Message}", id, ex.Message);
            _db.SegmentationJobs.Remove(job);
            await _db.SaveChangesAsync();
            Response.Headers.RetryAfter = "30";
            return StatusCode(503, "The segmentation queue is full. Please try again shortly.");
        }
        catch (AiServiceException ex) when (ex.StatusCode == System.Net.HttpStatusCode.BadRequest)
        {
            _logger.LogWarning("AI service rejected scan {ScanId}: {Message}", id, ex.Message);
            await ReleaseClaimAsFailedAsync(job, scan, "The AI service rejected this scan.");
            return BadRequest("The AI service rejected this scan. Check the file and organ.");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Could not queue segmentation for scan {ScanId}", id);
            await ReleaseClaimAsFailedAsync(job, scan, "Could not reach the segmentation service.");
            return StatusCode(502, "Could not reach the segmentation service.");
        }

        job.ExternalJobId = state.JobId;
        job.Status = SegmentationJobStatus.Queued;
        job.Progress = state.Progress;
        job.Stage = state.Stage;
        job.StageLabel = state.StageLabel;
        job.Attempt = state.Attempt;
        job.MaxAttempts = state.MaxAttempts;
        job.UpdatedAt = DateTime.UtcNow;
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

    /// Every run this scan has had, newest first, failures included.
    [HttpGet("{id:guid}/runs")]
    public async Task<ActionResult<List<SegmentationRunDto>>> ListRuns(Guid id)
    {
        if (!await _db.Scans.AnyAsync(s => s.Id == id && s.UserId == CurrentUserId))
            return NotFound();

        var runs = await _db.SegmentationJobs
            .Where(j => j.ScanId == id)
            .Include(j => j.Result)
            .OrderByDescending(j => j.CreatedAt)
            .ToListAsync();

        return Ok(runs.Select(j => new SegmentationRunDto(
            j.Id,
            j.Status.ToString(),
            j.Organ,
            j.Attempt,
            j.MaxAttempts,
            j.ErrorMessage,
            j.CreatedAt,
            j.CompletedAt,
            j.Result is null ? null : ToResultDto(j.Result)
        )).ToList());
    }

    [HttpGet("{id:guid}/runs/{runId:guid}/mask")]
    public async Task<IActionResult> DownloadRunMask(Guid id, Guid runId)
    {
        if (!await _db.Scans.AnyAsync(s => s.Id == id && s.UserId == CurrentUserId))
            return NotFound();

        var result = await _db.SegmentationResults
            .SingleOrDefaultAsync(r => r.JobId == runId && r.ScanId == id);

        if (result is null) return NotFound();
        if (!result.HasMask) return StatusCode(410, "The mask for this run is no longer stored.");
        if (!System.IO.File.Exists(result.MaskStoredPath)) return NotFound();

        var bytes = await System.IO.File.ReadAllBytesAsync(result.MaskStoredPath);
        return File(bytes, "application/gzip", "mask.nii.gz");
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

    /// The claim was taken but the work never started. Recorded as Failed
    /// rather than deleted: the user asked for a segmentation and did not get
    /// one, and a scan that silently returns to idle gives them nothing to
    /// read. Terminal, so it also releases the one-active-job claim.
    private async Task ReleaseClaimAsFailedAsync(SegmentationJob job, Scan scan, string reason)
    {
        job.Status = SegmentationJobStatus.Failed;
        job.ErrorMessage = reason;
        job.UpdatedAt = DateTime.UtcNow;
        job.CompletedAt = DateTime.UtcNow;
        scan.Status = ScanStatus.Failed;
        await _db.SaveChangesAsync();
    }

    private static bool IsUniqueViolation(DbUpdateException ex) =>
        ex.InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation };

    private Task<Scan?> LoadScanAsync(Guid id) =>
        _db.Scans
            .Include(s => s.Results)
            .SingleOrDefaultAsync(s => s.Id == id && s.UserId == CurrentUserId);

    private Task<SegmentationJob?> LatestJobAsync(Guid scanId) =>
        _db.SegmentationJobs
            .Where(j => j.ScanId == scanId)
            .OrderByDescending(j => j.CreatedAt)
            .FirstOrDefaultAsync();

    private static ScanDetailDto ToDetailDto(Scan scan, SegmentationJob? job)
    {
        var latest = scan.LatestResult;
        SegmentationResultDto? resultDto = latest is null ? null : ToResultDto(latest);

        return new ScanDetailDto(
            scan.Id,
            scan.FileName,
            scan.Status.ToString(),
            scan.UploadedAt,
            resultDto,
            job is null ? null : ToJobDto(job));
    }

    private static SegmentationResultDto ToResultDto(SegmentationResult result) => new(
        result.VoxelCount,
        result.VolumeMl,
        result.InferenceTimeMs,
        result.ModelName,
        result.Organ,
        result.OrganDisplayName,
        result.HasMask,
        result.CreatedAt
    );

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
