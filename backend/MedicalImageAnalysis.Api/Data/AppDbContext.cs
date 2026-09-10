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

        // Filtered, because a job is inserted before the AI service has given
        // it an id: the Pending row carries an empty ExternalJobId, and two
        // of those must not collide with each other.
        modelBuilder.Entity<SegmentationJob>()
            .HasIndex(j => j.ExternalJobId)
            .IsUnique()
            .HasFilter("\"ExternalJobId\" <> ''");

        // LatestJobAsync asks for a scan's newest job on every scan read, and
        // declaring the filtered index below replaces the index EF would
        // otherwise create for the foreign key - without this one, that
        // lookup degrades to a scan of the table.
        modelBuilder.Entity<SegmentationJob>()
            .HasIndex(j => new { j.ScanId, j.CreatedAt });

        // At most one job in flight per scan, enforced by the database rather
        // than by reading first and inserting second - two requests can both
        // pass that read. The literals are SegmentationJobStatus values
        // Pending/Queued/Retrying/Running; the enum is persisted as an int
        // and its members are only ever appended, so they are stable.
        modelBuilder.Entity<SegmentationJob>()
            .HasIndex(j => j.ScanId)
            .IsUnique()
            .HasFilter("\"Status\" IN (0, 1, 2, 3)")
            .HasDatabaseName("IX_SegmentationJobs_OneActivePerScan");
    }
}
