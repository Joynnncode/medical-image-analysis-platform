using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace MedicalImageAnalysis.Api.Migrations
{
    /// <inheritdoc />
    public partial class AddOrganToSegmentationResult : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "Organ",
                table: "SegmentationResults",
                type: "text",
                nullable: false,
                defaultValue: "");

            migrationBuilder.AddColumn<string>(
                name: "OrganDisplayName",
                table: "SegmentationResults",
                type: "text",
                nullable: false,
                defaultValue: "");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "Organ",
                table: "SegmentationResults");

            migrationBuilder.DropColumn(
                name: "OrganDisplayName",
                table: "SegmentationResults");
        }
    }
}
