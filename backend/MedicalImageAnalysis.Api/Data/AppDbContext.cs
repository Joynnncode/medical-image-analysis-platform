using MedicalImageAnalysis.Api.Models;
using Microsoft.EntityFrameworkCore;

namespace MedicalImageAnalysis.Api.Data;

public class AppDbContext : DbContext
{
    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }

    public DbSet<User> Users => Set<User>();
    public DbSet<Scan> Scans => Set<Scan>();
    public DbSet<SegmentationResult> SegmentationResults => Set<SegmentationResult>();

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
    }
}
