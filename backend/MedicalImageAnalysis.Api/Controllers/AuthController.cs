using System.Security.Claims;
using AspNet.Security.OAuth.GitHub;
using MedicalImageAnalysis.Api.Data;
using MedicalImageAnalysis.Api.DTOs;
using MedicalImageAnalysis.Api.Models;
using MedicalImageAnalysis.Api.Services;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace MedicalImageAnalysis.Api.Controllers;

[ApiController]
[Route("api/auth")]
public class AuthController : ControllerBase
{
    // Holds GitHub's answer for the one hop between the OAuth callback and
    // GitHubComplete, which swaps it for this API's own JWT.
    public const string ExternalScheme = "GitHubExternal";

    private readonly AppDbContext _db;
    private readonly ITokenService _tokenService;
    private readonly IAuthenticationSchemeProvider _schemes;
    private readonly IConfiguration _config;
    private readonly PasswordHasher<User> _passwordHasher = new();

    public AuthController(
        AppDbContext db,
        ITokenService tokenService,
        IAuthenticationSchemeProvider schemes,
        IConfiguration config)
    {
        _db = db;
        _tokenService = tokenService;
        _schemes = schemes;
        _config = config;
    }

    [HttpPost("register")]
    public async Task<ActionResult<AuthResponse>> Register(RegisterRequest request)
    {
        var email = request.Email.Trim().ToLowerInvariant();

        if (string.IsNullOrWhiteSpace(email) || !email.Contains('@'))
            return BadRequest("A valid email is required.");
        if (string.IsNullOrWhiteSpace(request.Password) || request.Password.Length < 8)
            return BadRequest("Password must be at least 8 characters.");

        if (await _db.Users.AnyAsync(u => u.Email == email))
            return Conflict("An account with this email already exists.");

        var user = new User { Email = email };
        user.PasswordHash = _passwordHasher.HashPassword(user, request.Password);

        _db.Users.Add(user);
        await _db.SaveChangesAsync();

        var (token, expiresAt) = _tokenService.CreateToken(user);
        return Ok(new AuthResponse(token, user.Email, expiresAt));
    }

    [HttpPost("guest")]
    public async Task<ActionResult<AuthResponse>> Guest()
    {
        var user = new User { Email = $"guest-{Guid.NewGuid():N}@guest.local", IsGuest = true };
        user.PasswordHash = _passwordHasher.HashPassword(user, Guid.NewGuid().ToString());

        _db.Users.Add(user);
        await _db.SaveChangesAsync();

        var (token, expiresAt) = _tokenService.CreateToken(user);
        return Ok(new AuthResponse(token, "Guest", expiresAt));
    }

    [HttpPost("login")]
    public async Task<ActionResult<AuthResponse>> Login(LoginRequest request)
    {
        var email = request.Email.Trim().ToLowerInvariant();
        var user = await _db.Users.SingleOrDefaultAsync(u => u.Email == email);
        if (user is null)
            return Unauthorized("Invalid email or password.");

        var result = _passwordHasher.VerifyHashedPassword(user, user.PasswordHash, request.Password);
        if (result == PasswordVerificationResult.Failed)
            return Unauthorized("Invalid email or password.");

        var (token, expiresAt) = _tokenService.CreateToken(user);
        return Ok(new AuthResponse(token, user.Email, expiresAt));
    }

    // The "Continue with GitHub" button is a plain link to here, not an XHR:
    // the OAuth dance is a chain of full-page redirects, and it ends back on
    // the frontend with a token rather than answering this request with one.
    [HttpGet("github/login")]
    public async Task<IActionResult> GitHubLogin()
    {
        if (!await GitHubConfiguredAsync())
            return Redirect(FrontendUrl("/login?error=github-unavailable"));

        var properties = new AuthenticationProperties { RedirectUri = Url.Action(nameof(GitHubComplete)) };
        return Challenge(properties, GitHubAuthenticationDefaults.AuthenticationScheme);
    }

    [HttpGet("github/complete")]
    public async Task<IActionResult> GitHubComplete()
    {
        if (!await GitHubConfiguredAsync())
            return Redirect(FrontendUrl("/login?error=github-unavailable"));

        var external = await HttpContext.AuthenticateAsync(ExternalScheme);
        await HttpContext.SignOutAsync(ExternalScheme);

        var principal = external.Succeeded ? external.Principal : null;
        var login = principal?.FindFirstValue(ClaimTypes.Name);
        if (!long.TryParse(principal?.FindFirstValue(ClaimTypes.NameIdentifier), out var gitHubId)
            || string.IsNullOrEmpty(login))
        {
            return Redirect(FrontendUrl("/login?error=github"));
        }

        // Matched on the GitHub id alone, never on email. A shared address is
        // not proof that whoever holds this GitHub account also owns the
        // password account registered under it.
        var user = await _db.Users.SingleOrDefaultAsync(u => u.GitHubId == gitHubId);
        if (user is null)
        {
            user = new User { GitHubId = gitHubId, Email = $"github-{gitHubId}@github.local" };
            _db.Users.Add(user);
        }
        user.GitHubLogin = login;
        await _db.SaveChangesAsync();

        var (token, expiresAt) = _tokenService.CreateToken(user);

        // In the fragment, not the query string: a fragment never leaves the
        // browser, so the token stays out of the frontend host's access logs
        // and out of any Referer header the next page sends.
        var fragment = string.Join("&",
            $"token={Uri.EscapeDataString(token)}",
            $"name={Uri.EscapeDataString(login)}",
            $"expiresAt={Uri.EscapeDataString(expiresAt.ToString("O"))}");
        return Redirect(FrontendUrl($"/auth/github#{fragment}"));
    }

    private async Task<bool> GitHubConfiguredAsync() =>
        await _schemes.GetSchemeAsync(GitHubAuthenticationDefaults.AuthenticationScheme) is not null;

    // Never taken from the request, so these redirects cannot be pointed at
    // somebody else's site. The first CORS origin already is the frontend in
    // every deployment, so it needs no setting of its own.
    private string FrontendUrl(string path)
    {
        var baseUrl = _config["Frontend:BaseUrl"]
            ?? _config.GetSection("Cors:AllowedOrigins").Get<string[]>()?.FirstOrDefault()
            ?? "http://localhost:5173";
        return baseUrl.TrimEnd('/') + path;
    }
}
