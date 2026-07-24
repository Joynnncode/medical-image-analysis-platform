using MedicalImageAnalysis.Api.DTOs;
using MedicalImageAnalysis.Api.Services;
using Microsoft.AspNetCore.Mvc;

namespace MedicalImageAnalysis.Api.Controllers;

[ApiController]
[Route("api/organs")]
public class OrgansController : ControllerBase
{
    private readonly IAiServiceClient _aiServiceClient;

    public OrgansController(IAiServiceClient aiServiceClient)
    {
        _aiServiceClient = aiServiceClient;
    }

    [HttpGet]
    public async Task<ActionResult<OrgansListDto>> List()
    {
        var (organs, defaultOrgan) = await _aiServiceClient.GetOrgansAsync();
        return Ok(new OrgansListDto(
            organs.Select(o => new OrganOptionDto(o.Key, o.DisplayName)).ToList(),
            defaultOrgan
        ));
    }
}
