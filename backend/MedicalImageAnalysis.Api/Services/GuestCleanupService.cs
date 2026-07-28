using MedicalImageAnalysis.Api.Data;
using Microsoft.EntityFrameworkCore;

namespace MedicalImageAnalysis.Api.Services;

// Deletes guest accounts (and their scan files) older than RetentionPeriod.
public class GuestCleanupService : BackgroundService
{
    private static readonly TimeSpan RetentionPeriod = TimeSpan.FromHours(24);
    private static readonly TimeSpan CheckInterval = TimeSpan.FromHours(1);

    private readonly IServiceScopeFactory _scopeFactory;
    private readonly IConfiguration _config;
    private readonly ILogger<GuestCleanupService> _logger;

    public GuestCleanupService(
        IServiceScopeFactory scopeFactory,
        IConfiguration config,
        ILogger<GuestCleanupService> logger)
    {
        _scopeFactory = scopeFactory;
        _config = config;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(CheckInterval);
        do
        {
            try
            {
                await CleanupAsync(stoppingToken);
            }
            catch (Exception ex) when (!stoppingToken.IsCancellationRequested)
            {
                _logger.LogError(ex, "Guest cleanup pass failed");
            }
        }
        while (await timer.WaitForNextTickAsync(stoppingToken));
    }

    private async Task CleanupAsync(CancellationToken cancellationToken)
    {
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var storageRoot = _config["Storage:Root"] ?? "./storage";

        var cutoff = DateTime.UtcNow - RetentionPeriod;
        var staleGuests = await db.Users
            .Where(u => u.IsGuest && u.CreatedAt < cutoff)
            .Include(u => u.Scans)
            .ToListAsync(cancellationToken);

        if (staleGuests.Count == 0) return;

        foreach (var scan in staleGuests.SelectMany(g => g.Scans))
        {
            var scanDir = Path.Combine(storageRoot, "scans", scan.Id.ToString());
            if (Directory.Exists(scanDir))
                Directory.Delete(scanDir, recursive: true);
        }

        db.Users.RemoveRange(staleGuests);
        await db.SaveChangesAsync(cancellationToken);

        _logger.LogInformation("Guest cleanup removed {Count} expired guest account(s)", staleGuests.Count);
    }
}
