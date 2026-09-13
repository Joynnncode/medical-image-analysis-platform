using System.Text;
using MedicalImageAnalysis.Api.Controllers;
using MedicalImageAnalysis.Api.Data;
using MedicalImageAnalysis.Api.Services;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.EntityFrameworkCore;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllers();
builder.Services.AddOpenApi();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(options =>
{
    options.SwaggerDoc("v1", new OpenApiInfo { Title = "Medical Image Analysis API", Version = "v1" });
    options.AddSecurityDefinition("Bearer", new OpenApiSecurityScheme
    {
        Name = "Authorization",
        Type = SecuritySchemeType.Http,
        Scheme = "Bearer",
        BearerFormat = "JWT",
        In = ParameterLocation.Header,
        Description = "Enter a JWT token (no 'Bearer ' prefix needed)",
    });
    options.AddSecurityRequirement(_ => new OpenApiSecurityRequirement
    {
        { new OpenApiSecuritySchemeReference("Bearer", null), new List<string>() },
    });
});

builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseNpgsql(builder.Configuration.GetConnectionString("Default")));

builder.Services.AddScoped<ITokenService, TokenService>();
builder.Services.AddHostedService<GuestCleanupService>();

builder.Services.AddHttpClient<IAiServiceClient, AiServiceClient>(client =>
{
    var baseUrl = builder.Configuration["AiService:BaseUrl"] ?? "http://localhost:8001";
    client.BaseAddress = new Uri(baseUrl);
    client.Timeout = TimeSpan.FromMinutes(5);
});

var jwtKey = builder.Configuration["Jwt:Key"]
    ?? throw new InvalidOperationException("Jwt:Key must be configured (see appsettings.json / environment variables).");
var jwtIssuer = builder.Configuration["Jwt:Issuer"] ?? "MedicalImageAnalysis";

var authentication = builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(options =>
    {
        // Keep claim types as issued (e.g. "sub") instead of ASP.NET Core's
        // default remapping to long-form ClaimTypes URIs.
        options.MapInboundClaims = false;
        options.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuer = true,
            ValidIssuer = jwtIssuer,
            ValidateAudience = true,
            ValidAudience = jwtIssuer,
            ValidateLifetime = true,
            ValidateIssuerSigningKey = true,
            IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(jwtKey)),
        };
    });

// GitHub sign-in is optional. Without an OAuth app configured the API runs as
// before, and the login button's endpoint sends visitors back to say so.
var gitHubClientId = builder.Configuration["GitHub:ClientId"];
var gitHubClientSecret = builder.Configuration["GitHub:ClientSecret"];
if (!string.IsNullOrEmpty(gitHubClientId) && !string.IsNullOrEmpty(gitHubClientSecret))
{
    authentication
        .AddCookie(AuthController.ExternalScheme, options =>
        {
            options.Cookie.Name = "medimg.github";
            options.Cookie.SameSite = SameSiteMode.Lax;
            options.ExpireTimeSpan = TimeSpan.FromMinutes(5);
        })
        .AddGitHub(options =>
        {
            options.ClientId = gitHubClientId;
            options.ClientSecret = gitHubClientSecret;
            options.SignInScheme = AuthController.ExternalScheme;
            options.CallbackPath = "/api/auth/github/callback";

            // GitHub comes back to the callback with a top-level GET, which a
            // Lax cookie survives. The default (None, Always Secure) would be
            // dropped by anything talking plain HTTP, local runs included.
            options.CorrelationCookie.SameSite = SameSiteMode.Lax;
            options.CorrelationCookie.SecurePolicy = CookieSecurePolicy.SameAsRequest;

            // Only the tests set these, to point the handshake at a fake GitHub.
            options.AuthorizationEndpoint = builder.Configuration["GitHub:AuthorizationEndpoint"] ?? options.AuthorizationEndpoint;
            options.TokenEndpoint = builder.Configuration["GitHub:TokenEndpoint"] ?? options.TokenEndpoint;
            options.UserInformationEndpoint = builder.Configuration["GitHub:UserInformationEndpoint"] ?? options.UserInformationEndpoint;

            // Declining on GitHub's consent page, or a stale or forged state,
            // lands here. GitHubComplete finds no sign-in and reports it on
            // the frontend's login page instead of a raw 500.
            options.Events.OnRemoteFailure = context =>
            {
                context.Response.Redirect("/api/auth/github/complete");
                context.HandleResponse();
                return Task.CompletedTask;
            };
        });
}

// Render terminates HTTPS at its proxy and forwards plain HTTP. Without the
// forwarded scheme the OAuth redirect_uri goes out as http://, which does not
// match the callback registered with GitHub. The proxy's addresses are not
// published, so no list of known proxies can be kept.
builder.Services.Configure<ForwardedHeadersOptions>(options =>
{
    options.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
    options.KnownIPNetworks.Clear();
    options.KnownProxies.Clear();
});

builder.Services.AddAuthorization();

var allowedOrigins = builder.Configuration.GetSection("Cors:AllowedOrigins").Get<string[]>()
    ?? new[] { "http://localhost:5173" };

builder.Services.AddCors(options =>
{
    options.AddPolicy("Frontend", policy =>
    {
        policy.WithOrigins(allowedOrigins)
            .AllowAnyHeader()
            .AllowAnyMethod();
    });
});

var app = builder.Build();

app.UseForwardedHeaders();

using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    db.Database.Migrate();
}

if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();
}

app.UseSwagger();
app.UseSwaggerUI();

app.UseCors("Frontend");

app.UseAuthentication();
app.UseAuthorization();

app.MapControllers();
app.MapGet("/health", () => Results.Ok(new { status = "ok" }));

app.Run();
