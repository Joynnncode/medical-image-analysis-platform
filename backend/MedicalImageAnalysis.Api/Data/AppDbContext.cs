using MedicalImageAnalysis.Api.Models;
using Microsoft.EntityFrameworkCore;

namespace MedicalImageAnalysis.Api.Data;

public class AppDbContext : DbContext
{
    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }

    public DbSet<User> Users => Set<User>();
    public DbSet<Scan> Scans => Set<Scan>();
    public DbSet<SegmentationResult> SegmentationResults => Set<SegmentationResult>();
    public DbSet<SegmentationJob> SegmentationJobs => Set<SegmentationJob>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<User>()
            .HasIndex(u => u.Email)
            .IsUnique();

        modelBuilder.Entity<Scan>()
            .HasOne(s => s.User)
            .WithMany(u => u.Scans)
            .HasForeignKey(s => s.UserId)
            .OnDelete(DeleteBehavior.Cascade);

        modelBuilder.Entity<SegmentationResult>()
            .HasOne(r => r.Scan)
            .WithOne(s => s.SegmentationResult)
            .HasForeignKey<SegmentationResult>(r => r.ScanId)
            .OnDelete(DeleteBehavior.Cascade);

        modelBuilder.Entity<SegmentationJob>()
            .HasOne(j => j.Scan)
            .WithMany(s => s.Jobs)
            .HasForeignKey(j => j.ScanId)
            .OnDelete(DeleteBehavior.Cascade);

        // The monitor's hot query is "every job that isn't finished yet".
        modelBuilder.Entity<SegmentationJob>()
            .HasIndex(j => new { j.Status, j.UpdatedAt });

        modelBuilder.Entity<SegmentationJob>()
            .HasIndex(j => j.ExternalJobId)
            .IsUnique();
    }
}
