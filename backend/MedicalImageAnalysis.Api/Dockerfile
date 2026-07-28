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

# Config comes from env vars in production, not live-edited files, and
# small/shared containers can have very low inotify watch limits - avoid
# ASP.NET Core's default appsettings.json file-watcher hitting that limit
# and crashing the app on startup.
ENV DOTNET_hostBuilder__reloadConfigOnChange=false

# Render (and similar PaaS) inject a PORT env var and expect the app to
# bind to it; docker-compose local dev doesn't set one, so this falls
# back to 8080 to match the existing compose port mapping.
ENTRYPOINT ["sh", "-c", "ASPNETCORE_URLS=http://+:${PORT:-8080} dotnet MedicalImageAnalysis.Api.dll"]
