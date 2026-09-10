using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace MedicalImageAnalysis.Api.Migrations
{
    /// <inheritdoc />
    public partial class AddRunHistory : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_SegmentationResults_ScanId",
                table: "SegmentationResults");

            migrationBuilder.AddColumn<Guid>(
                name: "JobId",
                table: "SegmentationResults",
                type: "uuid",
                nullable: true);

            migrationBuilder.AddColumn<DateTime>(
                name: "MaskReclaimedAt",
                table: "SegmentationResults",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.CreateIndex(
                name: "IX_SegmentationResults_JobId",
                table: "SegmentationResults",
                column: "JobId",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_SegmentationResults_ScanId_CreatedAt",
                table: "SegmentationResults",
                columns: new[] { "ScanId", "CreatedAt" });

            migrationBuilder.AddForeignKey(
                name: "FK_SegmentationResults_SegmentationJobs_JobId",
                table: "SegmentationResults",
                column: "JobId",
                principalTable: "SegmentationJobs",
                principalColumn: "Id",
                onDelete: ReferentialAction.SetNull);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropForeignKey(
                name: "FK_SegmentationResults_SegmentationJobs_JobId",
                table: "SegmentationResults");

            migrationBuilder.DropIndex(
                name: "IX_SegmentationResults_JobId",
                table: "SegmentationResults");

            migrationBuilder.DropIndex(
                name: "IX_SegmentationResults_ScanId_CreatedAt",
                table: "SegmentationResults");

            migrationBuilder.DropColumn(
                name: "JobId",
                table: "SegmentationResults");

            migrationBuilder.DropColumn(
                name: "MaskReclaimedAt",
                table: "SegmentationResults");

            migrationBuilder.CreateIndex(
                name: "IX_SegmentationResults_ScanId",
                table: "SegmentationResults",
                column: "ScanId",
                unique: true);
        }
    }
}
