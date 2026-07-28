namespace MedicalImageAnalysis.Api.Models;

public class User
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public string Email { get; set; } = string.Empty;
    public string PasswordHash { get; set; } = string.Empty;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public bool IsGuest { get; set; }

    public ICollection<Scan> Scans { get; set; } = new List<Scan>();
}
