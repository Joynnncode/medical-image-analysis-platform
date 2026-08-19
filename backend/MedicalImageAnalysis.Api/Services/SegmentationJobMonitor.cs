using MedicalImageAnalysis.Api.Data;
using MedicalImageAnalysis.Api.Models;
using Microsoft.EntityFrameworkCore;

namespace MedicalImageAnalysis.Api.Services;

/// Follows queued segmentation jobs through to their conclusion.
///
/// Nothing about a job's completion depends on the client that started it
/// still being connected: this polls the AI service, mirrors progress onto
/// the job row, and on success collects the mask and writes the result. A
/// browser refresh, a lost connection, or an API restart all just mean the
/// next pass picks the job up where it was.
public class SegmentationJobMonitor : BackgroundService
{
    private static readonly SegmentationJobStatus[] ActiveStatuses =
    {
        SegmentationJobStatus.Pending,
        SegmentationJobStatus.Queued,
        SegmentationJobStatus.Retrying,
        SegmentationJobStatus.Running,
    };

    private readonly IServiceScopeFactory _scopeFactory;
    private readonly IConfiguration _config;
    private readonly ILogger<SegmentationJobMonitor> _logger;

    public SegmentationJobMonitor(
        IServiceScopeFactory scopeFactory,
        IConfiguration config,
        ILogger<SegmentationJobMonitor> logger)
    {
        _scopeFactory = scopeFactory;
        _config = config;
        _logger = logger;
    }

    private TimeSpan PollInterval =>
        TimeSpan.FromSeconds(_config.GetValue("SegmentationJobs:PollIntervalSeconds", 2));

    /// A job the AI service stops making progress on for this long is
    /// declared lost, rather than sitting "Running" forever.
    private TimeSpan MaxJobLifetime =>
        TimeSpan.FromMinutes(_config.GetValue("SegmentationJobs:MaxJobLifetimeMinutes", 120));

    /// A dead lettered job keeps being watched for a while, at a much lower
    /// rate, so that an operator replaying it from the DLQ (which reuses the
    /// job id) is noticed here instead of leaving the scan stuck on Failed.
    private TimeSpan DeadLetterGrace =>
        TimeSpan.FromMinutes(_config.GetValue("SegmentationJobs:DeadLetterGraceMinutes", 60));

    private TimeSpan DeadLetterPollInterval =>
        TimeSpan.FromSeconds(_config.GetValue("SegmentationJobs:DeadLetterPollIntervalSeconds", 30));

    private string StorageRoot => _config["Storage:Root"] ?? "./storage";

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(PollInterval);
        while (await timer.WaitForNextTickAsync(stoppingToken))
        {
            try
            {
                await PollAsync(stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Segmentation job poll failed");
            }
        }
    }

    private async Task PollAsync(CancellationToken ct)
    {
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var ai = scope.ServiceProvider.GetRequiredService<IAiServiceClient>();

        var now = DateTime.UtcNow;
        var deadLetterCutoff = now - DeadLetterGrace;
        var deadLetterDue = now - DeadLetterPollInterval;

        var jobs = await db.SegmentationJobs
            .Include(j => j.Scan)
            .ThenInclude(s => s!.SegmentationResult)
            .Where(j => ActiveStatuses.Contains(j.Status)
                || (j.Status == SegmentationJobStatus.DeadLettered
                    && j.UpdatedAt > deadLetterCutoff
                    && (j.LastPolledAt == null || j.LastPolledAt < deadLetterDue)))
            .OrderBy(j => j.CreatedAt)
            .ToListAsync(ct);

        foreach (var job in jobs)
        {
            try
            {
                await PollJobAsync(db, ai, job, ct);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                return;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Could not update segmentation job {JobId}", job.ExternalJobId);
            }
        }
    }

    private async Task PollJobAsync(
        AppDbContext db, IAiServiceClient ai, SegmentationJob job, CancellationToken ct)
    {
        job.LastPolledAt = DateTime.UtcNow;

        var state = await ai.GetJobAsync(job.ExternalJobId, ct);

        if (state is null)
        {
            // Redis lost the job (expired, or flushed). Nothing is coming.
            if (!job.IsTerminal)
            {
                Fail(job, "The AI service no longer has a record of this job.");
                _logger.LogWarning("Segmentation job {JobId} vanished from the AI service", job.ExternalJobId);
            }
            await db.SaveChangesAsync(ct);
            return;
        }

        if (!job.IsTerminal && DateTime.UtcNow - job.CreatedAt > MaxJobLifetime)
        {
            Fail(job, $"Job exceeded the {MaxJobLifetime.TotalMinutes:0} minute limit and was abandoned.");
            await db.SaveChangesAsync(ct);
            return;
        }

        job.Progress = state.Progress;
        job.Stage = state.Stage;
        job.StageLabel = state.StageLabel;
        job.Attempt = state.Attempt;
        job.MaxAttempts = state.MaxAttempts;
        job.UpdatedAt = DateTime.UtcNow;

        switch (state.Status)
        {
            case "queued":
                job.Status = SegmentationJobStatus.Queued;
                SetScanStatus(job, ScanStatus.Queued);
                break;

            case "retrying":
                job.Status = SegmentationJobStatus.Retrying;
                job.ErrorMessage = state.Error;
                SetScanStatus(job, ScanStatus.Queued);
                break;

            case "running":
                job.Status = SegmentationJobStatus.Running;
                SetScanStatus(job, ScanStatus.Processing);
                break;

            case "completed":
                await CompleteAsync(db, ai, job, state, ct);
                break;

            case "failed":
                job.Status = state.DeadLettered
                    ? SegmentationJobStatus.DeadLettered
                    : SegmentationJobStatus.Failed;
                job.ErrorMessage = state.Error ?? "Segmentation failed.";
                job.CompletedAt ??= DateTime.UtcNow;
                SetScanStatus(job, ScanStatus.Failed);
                _logger.LogWarning(
                    "Segmentation job {JobId} failed after {Attempt}/{MaxAttempts} attempts: {Error}",
                    job.ExternalJobId, state.Attempt, state.MaxAttempts, job.ErrorMessage);
                break;

            case "canceled":
                job.Status = SegmentationJobStatus.Canceled;
                job.CompletedAt ??= DateTime.UtcNow;
                SetScanStatus(job, ScanStatus.Uploaded);
                break;

            default:
                _logger.LogWarning(
                    "Unrecognised status '{Status}' for segmentation job {JobId}",
                    state.Status, job.ExternalJobId);
                break;
        }

        await db.SaveChangesAsync(ct);
    }

    private async Task CompleteAsync(
        AppDbContext db,
        IAiServiceClient ai,
        SegmentationJob job,
        SegmentationJobState state,
        CancellationToken ct)
    {
        if (state.Result is null)
        {
            Fail(job, "The AI service reported success but returned no result.");
            return;
        }

        var scan = job.Scan!;
        var maskBytes = await ai.DownloadMaskAsync(job.ExternalJobId, ct);

        var scanDir = Path.Combine(StorageRoot, "scans", scan.Id.ToString());
        Directory.CreateDirectory(scanDir);
        var maskPath = Path.Combine(scanDir, "mask.nii.gz");
        await File.WriteAllBytesAsync(maskPath, maskBytes, ct);

        var result = scan.SegmentationResult;
        if (result is null)
        {
            result = new SegmentationResult { ScanId = scan.Id };
            scan.SegmentationResult = result;
            db.SegmentationResults.Add(result);
        }

        result.MaskStoredPath = maskPath;
        result.VoxelCount = state.Result.VoxelCount;
        result.VolumeMl = state.Result.VolumeMl;
        result.InferenceTimeMs = state.Result.InferenceTimeMs;
        result.ModelName = state.Result.ModelName;
        result.Organ = state.Result.Organ;
        result.OrganDisplayName = state.Result.OrganDisplayName;
        result.CreatedAt = DateTime.UtcNow;

        job.Status = SegmentationJobStatus.Completed;
        job.Progress = 100;
        job.Stage = "done";
        job.StageLabel = string.IsNullOrEmpty(state.StageLabel) ? "Done" : state.StageLabel;
        job.ErrorMessage = null;
        job.CompletedAt = DateTime.UtcNow;
        scan.Status = ScanStatus.Completed;

        _logger.LogInformation(
            "Segmentation job {JobId} completed for scan {ScanId} ({Voxels} voxels, {Ms:0} ms)",
            job.ExternalJobId, scan.Id, state.Result.VoxelCount, state.Result.InferenceTimeMs);

        // Persist before releasing the payload: if this throws, the job is
        // still collectable on the next pass.
        await db.SaveChangesAsync(ct);

        try
        {
            await ai.DeleteJobAsync(job.ExternalJobId, ct);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Could not release job {JobId} on the AI service", job.ExternalJobId);
        }
    }

    private static void Fail(SegmentationJob job, string message)
    {
        job.Status = SegmentationJobStatus.Failed;
        job.ErrorMessage = message;
        job.UpdatedAt = DateTime.UtcNow;
        job.CompletedAt ??= DateTime.UtcNow;
        if (job.Scan is not null) job.Scan.Status = ScanStatus.Failed;
    }

    private static void SetScanStatus(SegmentationJob job, ScanStatus status)
    {
        if (job.Scan is not null && job.Scan.Status != status)
            job.Scan.Status = status;
    }
}
