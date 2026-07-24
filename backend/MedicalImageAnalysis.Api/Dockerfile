FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

COPY MedicalImageAnalysis.Api.csproj .
RUN dotnet restore MedicalImageAnalysis.Api.csproj

COPY . .
RUN dotnet publish MedicalImageAnalysis.Api.csproj -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /app .

ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080

ENTRYPOINT ["dotnet", "MedicalImageAnalysis.Api.dll"]
