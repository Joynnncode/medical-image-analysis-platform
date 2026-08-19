using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace MedicalImageAnalysis.Api.Migrations
{
    /// <inheritdoc />
    public partial class AddSegmentationJobs : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "SegmentationJobs",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    ScanId = table.Column<Guid>(type: "uuid", nullable: false),
                    ExternalJobId = table.Column<string>(type: "text", nullable: false),
                    Organ = table.Column<string>(type: "text", nullable: false),
                    Status = table.Column<int>(type: "integer", nullable: false),
                    Progress = table.Column<int>(type: "integer", nullable: false),
                    Stage = table.Column<string>(type: "text", nullable: false),
                    StageLabel = table.Column<string>(type: "text", nullable: false),
                    Attempt = table.Column<int>(type: "integer", nullable: false),
                    MaxAttempts = table.Column<int>(type: "integer", nullable: false),
                    ErrorMessage = table.Column<string>(type: "text", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    UpdatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    LastPolledAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    CompletedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_SegmentationJobs", x => x.Id);
                    table.ForeignKey(
                        name: "FK_SegmentationJobs_Scans_ScanId",
                        column: x => x.ScanId,
                        principalTable: "Scans",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_SegmentationJobs_ExternalJobId",
                table: "SegmentationJobs",
                column: "ExternalJobId",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_SegmentationJobs_ScanId",
                table: "SegmentationJobs",
                column: "ScanId");

            migrationBuilder.CreateIndex(
                name: "IX_SegmentationJobs_Status_UpdatedAt",
                table: "SegmentationJobs",
                columns: new[] { "Status", "UpdatedAt" });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "SegmentationJobs");
        }
    }
}
