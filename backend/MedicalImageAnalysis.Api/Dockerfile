FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

COPY MedicalImageAnalysis.Api.csproj .
RUN dotnet restore MedicalImageAnalysis.Api.csproj

COPY . .
RUN dotnet publish MedicalImageAnalysis.Api.csproj -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /app .

EXPOSE 8080

# Render (and similar PaaS) inject a PORT env var and expect the app to
# bind to it; docker-compose local dev doesn't set one, so this falls
# back to 8080 to match the existing compose port mapping.
ENTRYPOINT ["sh", "-c", "ASPNETCORE_URLS=http://+:${PORT:-8080} dotnet MedicalImageAnalysis.Api.dll"]
