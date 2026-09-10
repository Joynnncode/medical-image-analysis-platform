using System.Linq.Expressions;
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

    /// Identifies this monitor in the lease. Per instance rather than per
    /// machine: two API processes on one host are exactly the case the lease
    /// exists for.
    private readonly string _owner = $"{Environment.MachineName}/{Environment.ProcessId}/{Guid.NewGuid():N}";

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

    /// How long a monitor's claim on a job holds. It has to outlast a whole
    /// pass over one job, mask download included, or a second monitor takes
    /// over work that is still going on. It is also how long a job waits if
    /// the API instance holding it dies mid-collection.
    private TimeSpan MonitorLease =>
        TimeSpan.FromSeconds(_config.GetValue("SegmentationJobs:MonitorLeaseSeconds", 60));

    /// A job is claimed in Postgres before the volume is sent to the AI
    /// service, so there is a window where it has no external id and the
    /// request that owns it is still uploading. Past this, the request that
    /// created it is taken to be dead and the claim is released.
    ///
    /// Two minutes is generous for what the handoff actually is: the API
    /// streaming a file it already has on disk to a service in the same
    /// region, which enqueues it and answers. It does not wait for a model.
    /// The trade being made is against the other side - an API instance that
    /// dies mid-handoff locks that scan out of new segmentations for exactly
    /// this long.
    private TimeSpan PendingHandoffTimeout =>
        TimeSpan.FromMinutes(_config.GetValue("SegmentationJobs:PendingHandoffTimeoutMinutes", 2));

    /// How many masks a scan keeps. The result rows are never deleted - the
    /// measurements are the history, and they cost a few dozen bytes each.
    /// What this bounds is the mask files, which are tens of MB apiece and
    /// which a re-run reproduces.
    private int MaskRetentionCount =>
        Math.Max(1, _config.GetValue("SegmentationJobs:MaskRetentionCount", 5));

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

    /// What this monitor considers its work: jobs still in flight, plus dead
    /// lettered ones inside the grace window and due for their slower poll.
    ///
    /// Shared by the listing pass and the per-job reload so that "is this
    /// still mine to do?" has one definition rather than two that can drift.
    private static Expression<Func<SegmentationJob, bool>> IsCandidate(
        DateTime deadLetterCutoff, DateTime deadLetterDue) =>
        j => ActiveStatuses.Contains(j.Status)
            || (j.Status == SegmentationJobStatus.DeadLettered
                && j.UpdatedAt > deadLetterCutoff
                && (j.LastPolledAt == null || j.LastPolledAt < deadLetterDue));

    private async Task PollAsync(CancellationToken ct)
    {
        var now = DateTime.UtcNow;
        var deadLetterCutoff = now - DeadLetterGrace;
        var deadLetterDue = now - DeadLetterPollInterval;

        List<Guid> jobIds;
        using (var listing = _scopeFactory.CreateScope())
        {
            var db = listing.ServiceProvider.GetRequiredService<AppDbContext>();
            jobIds = await db.SegmentationJobs
                .Where(IsCandidate(deadLetterCutoff, deadLetterDue))
                .OrderBy(j => j.CreatedAt)
                .Select(j => j.Id)
                .ToListAsync(ct);
        }

        foreach (var jobId in jobIds)
        {
            // A scope - and so a DbContext - per job rather than per pass.
            // The jobs in a pass are independent, but one shared change
            // tracker makes them anything but: SaveChanges writes every
            // tracked change, not this job's. A job whose write is rejected -
            // which is precisely what the terminal-state trigger does to the
            // monitor that lost a race - stays Modified in the tracker, so
            // the next job's SaveChanges resubmits it, is rejected again, and
            // rolls back the innocent job with it. One loser would take every
            // job behind it in the pass down, and each would be logged under
            // the loser's id. Measured before this change: job B, polled
            // successfully, never reached the database and reported job A's
            // error as its own.
            using var scope = _scopeFactory.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
            var ai = scope.ServiceProvider.GetRequiredService<IAiServiceClient>();

            SegmentationJob? job = null;
            try
            {
                job = await db.SegmentationJobs
                    .Include(j => j.Scan)
                    .ThenInclude(s => s!.Results)
                    .Where(IsCandidate(deadLetterCutoff, deadLetterDue))
                    .FirstOrDefaultAsync(j => j.Id == jobId, ct);

                // Finished, or taken past the candidate set, between the
                // listing and here. Nothing to do and nothing wrong.
                if (job is null) continue;

                if (!await ClaimAsync(db, job, ct)) continue;
                await PollJobAsync(db, ai, job, ct);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                return;
            }
            catch (Exception ex)
            {
                _logger.LogError(
                    ex,
                    "Could not update segmentation job {JobId} ({ExternalJobId})",
                    jobId,
                    job?.ExternalJobId ?? "not loaded");
            }
        }
    }

    /// Takes the lease on a job, or reports that someone else holds it.
    ///
    /// One conditional UPDATE rather than a read followed by a write: two
    /// monitors reading "nobody holds this" and then both writing their own
    /// name is the same defect this whole change is about, and it is the more
    /// expensive one here - both would download the mask and both would write
    /// the result. Zero rows updated means the other one won.
    private async Task<bool> ClaimAsync(AppDbContext db, SegmentationJob job, CancellationToken ct)
    {
        var now = DateTime.UtcNow;
        var expiry = now + MonitorLease;

        var claimed = await db.SegmentationJobs
            .Where(j => j.Id == job.Id
                && (j.MonitorOwner == null
                    || j.MonitorOwner == _owner
                    || j.MonitorLeaseExpiresAt == null
                    || j.MonitorLeaseExpiresAt < now))
            .ExecuteUpdateAsync(s => s
                .SetProperty(j => j.MonitorOwner, _owner)
                .SetProperty(j => j.MonitorLeaseExpiresAt, expiry), ct);

        return claimed > 0;
    }

    private async Task PollJobAsync(
        AppDbContext db, IAiServiceClient ai, SegmentationJob job, CancellationToken ct)
    {
        // Claimed, but the AI service has not given it an id yet - the request
        // that created it is still uploading the volume. Looking up an empty
        // id would find nothing and kill a request that is doing fine, so only
        // give up once no such request could still be running.
        if (string.IsNullOrEmpty(job.ExternalJobId))
        {
            if (DateTime.UtcNow - job.CreatedAt > PendingHandoffTimeout)
            {
                Fail(job, "The scan was never handed to the segmentation service.");
                _logger.LogWarning(
                    "Segmentation job {JobId} was never handed over and has been abandoned", job.Id);
                await db.SaveChangesAsync(ct);
            }
            return;
        }

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

        // Keyed on the job, not the scan. A retry of this same run overwrites
        // its own file, so a duplicate execution leaves one mask rather than
        // two; a new run gets its own directory, so asking a second question
        // does not erase the answer to the first. Deterministic per run is
        // what makes those two different outcomes from the same rule.
        var runDir = Path.Combine(StorageRoot, "scans", scan.Id.ToString(), "runs", job.Id.ToString());
        Directory.CreateDirectory(runDir);
        var maskPath = Path.Combine(runDir, "mask.nii.gz");
        await File.WriteAllBytesAsync(maskPath, maskBytes, ct);

        // One result per run, found by the job rather than the scan, so a
        // retry updates the row this run already wrote instead of adding one.
        var result = await db.SegmentationResults
            .SingleOrDefaultAsync(r => r.JobId == job.Id, ct);
        if (result is null)
        {
            result = new SegmentationResult { ScanId = scan.Id, JobId = job.Id };
            db.SegmentationResults.Add(result);
        }

        result.MaskStoredPath = maskPath;
        result.MaskReclaimedAt = null;
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

        // Only once the new result is durable. Reclaiming first would leave a
        // scan with one fewer mask than it has results if this pass then died.
        await PruneMasksAsync(db, scan.Id, ct);

        try
        {
            await ai.DeleteJobAsync(job.ExternalJobId, ct);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Could not release job {JobId} on the AI service", job.ExternalJobId);
        }
    }

    /// Reclaims every mask on a scan beyond the newest MaskRetentionCount.
    private async Task PruneMasksAsync(AppDbContext db, Guid scanId, CancellationToken ct)
    {
        var stale = await db.SegmentationResults
            .Where(r => r.ScanId == scanId && r.MaskReclaimedAt == null)
            .OrderByDescending(r => r.CreatedAt)
            .Skip(MaskRetentionCount)
            .ToListAsync(ct);

        if (stale.Count == 0) return;

        var reclaimed = 0;
        foreach (var result in stale)
        {
            try
            {
                if (File.Exists(result.MaskStoredPath)) File.Delete(result.MaskStoredPath);

                var dir = Path.GetDirectoryName(result.MaskStoredPath);
                if (dir is not null && Directory.Exists(dir)
                    && !Directory.EnumerateFileSystemEntries(dir).Any())
                    Directory.Delete(dir);
            }
            catch (Exception ex)
            {
                // A file that would not delete is wasted space, not a wrong
                // answer. Marking it reclaimed anyway would tell the UI the
                // mask is gone when it is still there, so leave the row alone
                // and let the next run try again.
                _logger.LogWarning(ex, "Could not reclaim mask at {Path}", result.MaskStoredPath);
                continue;
            }

            result.MaskReclaimedAt = DateTime.UtcNow;
            reclaimed++;
        }

        if (reclaimed == 0) return;

        await db.SaveChangesAsync(ct);
        _logger.LogInformation(
            "Reclaimed {Count} mask(s) for scan {ScanId}, keeping the newest {Keep}",
            reclaimed, scanId, MaskRetentionCount);
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
