using MedicalImageAnalysis.Api.Models;

namespace MedicalImageAnalysis.Api.Services;

public interface ITokenService
{
    (string Token, DateTime ExpiresAt) CreateToken(User user);
}
