namespace MedicalImageAnalysis.Api.DTOs;

public record RegisterRequest(string Email, string Password);

public record LoginRequest(string Email, string Password);

public record AuthResponse(string Token, string Email, DateTime ExpiresAt);
