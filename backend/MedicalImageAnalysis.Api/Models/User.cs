namespace MedicalImageAnalysis.Api.Models;

public class User
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public string Email { get; set; } = string.Empty;
    public string PasswordHash { get; set; } = string.Empty;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public bool IsGuest { get; set; }

    // Set for accounts that sign in with GitHub. The numeric id is what
    // identifies them: a GitHub login can be renamed, the id cannot.
    public long? GitHubId { get; set; }
    public string? GitHubLogin { get; set; }

    public ICollection<Scan> Scans { get; set; } = new List<Scan>();
}
