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
            .Select(s => new ScanSummaryDto(s.Id, s.FileName, s.Status.ToString(), s.UploadedAt))
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

        return Ok(new ScanSummaryDto(scan.Id, scan.FileName, scan.Status.ToString(), scan.UploadedAt));
    }

    [HttpGet("{id:guid}")]
    public async Task<ActionResult<ScanDetailDto>> Get(Guid id)
    {
        var scan = await _db.Scans
            .Include(s => s.SegmentationResult)
            .SingleOrDefaultAsync(s => s.Id == id && s.UserId == CurrentUserId);

        if (scan is null) return NotFound();

        return Ok(ToDetailDto(scan));
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
        var scan = await _db.Scans
            .Include(s => s.SegmentationResult)
            .SingleOrDefaultAsync(s => s.Id == id && s.UserId == CurrentUserId);

        if (scan?.SegmentationResult is null) return NotFound();
        if (!System.IO.File.Exists(scan.SegmentationResult.MaskStoredPath)) return NotFound();

        var bytes = await System.IO.File.ReadAllBytesAsync(scan.SegmentationResult.MaskStoredPath);
        return File(bytes, "application/gzip", "mask.nii.gz");
    }

    [HttpPost("{id:guid}/segment")]
    public async Task<ActionResult<ScanDetailDto>> Segment(Guid id, [FromQuery] string organ = "spleen")
    {
        var scan = await _db.Scans
            .Include(s => s.SegmentationResult)
            .SingleOrDefaultAsync(s => s.Id == id && s.UserId == CurrentUserId);

        if (scan is null) return NotFound();
        if (!System.IO.File.Exists(scan.StoredPath)) return NotFound("Original scan file is missing.");

        scan.Status = ScanStatus.Processing;
        await _db.SaveChangesAsync();

        try
        {
            var bytes = await System.IO.File.ReadAllBytesAsync(scan.StoredPath);
            var outcome = await _aiServiceClient.SegmentAsync(bytes, scan.FileName, organ);

            var scanDir = Path.Combine(StorageRoot, "scans", scan.Id.ToString());
            Directory.CreateDirectory(scanDir);
            var maskPath = Path.Combine(scanDir, "mask.nii.gz");
            await System.IO.File.WriteAllBytesAsync(maskPath, outcome.MaskBytes);

            if (scan.SegmentationResult is null)
            {
                scan.SegmentationResult = new SegmentationResult { ScanId = scan.Id };
                _db.SegmentationResults.Add(scan.SegmentationResult);
            }

            scan.SegmentationResult.MaskStoredPath = maskPath;
            scan.SegmentationResult.VoxelCount = outcome.VoxelCount;
            scan.SegmentationResult.VolumeMl = outcome.VolumeMl;
            scan.SegmentationResult.InferenceTimeMs = outcome.InferenceTimeMs;
            scan.SegmentationResult.ModelName = outcome.ModelName;
            scan.SegmentationResult.Organ = outcome.Organ;
            scan.SegmentationResult.OrganDisplayName = outcome.OrganDisplayName;
            scan.SegmentationResult.CreatedAt = DateTime.UtcNow;

            scan.Status = ScanStatus.Completed;
            await _db.SaveChangesAsync();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Segmentation failed for scan {ScanId}", scan.Id);
            scan.Status = ScanStatus.Failed;
            await _db.SaveChangesAsync();
            return StatusCode(502, "Segmentation failed. See server logs for details.");
        }

        return Ok(ToDetailDto(scan));
    }

    private static ScanDetailDto ToDetailDto(Scan scan)
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

        return new ScanDetailDto(scan.Id, scan.FileName, scan.Status.ToString(), scan.UploadedAt, resultDto);
    }
}
