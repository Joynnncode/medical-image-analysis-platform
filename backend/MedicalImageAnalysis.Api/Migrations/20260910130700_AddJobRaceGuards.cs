using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace MedicalImageAnalysis.Api.Migrations
{
    /// <inheritdoc />
    public partial class AddJobRaceGuards : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_SegmentationJobs_ExternalJobId",
                table: "SegmentationJobs");

            migrationBuilder.DropIndex(
                name: "IX_SegmentationJobs_ScanId",
                table: "SegmentationJobs");

            migrationBuilder.AddColumn<DateTime>(
                name: "MonitorLeaseExpiresAt",
                table: "SegmentationJobs",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "MonitorOwner",
                table: "SegmentationJobs",
                type: "text",
                nullable: true);

            migrationBuilder.CreateIndex(
                name: "IX_SegmentationJobs_ExternalJobId",
                table: "SegmentationJobs",
                column: "ExternalJobId",
                unique: true,
                filter: "\"ExternalJobId\" <> ''");

            migrationBuilder.CreateIndex(
                name: "IX_SegmentationJobs_OneActivePerScan",
                table: "SegmentationJobs",
                column: "ScanId",
                unique: true,
                filter: "\"Status\" IN (0, 1, 2, 3)");

            migrationBuilder.CreateIndex(
                name: "IX_SegmentationJobs_ScanId_CreatedAt",
                table: "SegmentationJobs",
                columns: new[] { "ScanId", "CreatedAt" });

            // Terminal states are immutable, enforced below the application.
            // The conditional updates in SegmentationJobMonitor already imply
            // it; this is the backstop for the case that actually matters -
            // a late monitor flipping a Completed job to Failed while the
            // customer is looking at the result it just collected. An
            // application-level `if` cannot stop a second process, and this
            // failure is silent when it happens.
            //
            // 4/5/7 are Completed/Failed/Canceled. DeadLettered (6) is
            // deliberately NOT in the set, even though SegmentationJob.IsTerminal
            // counts it: the monitor keeps watching dead lettered jobs for an
            // hour precisely so that an operator replaying one from the DLQ is
            // picked up rather than leaving the scan stuck, and that replay
            // moves the job out of 6. Locking 6 down would silently break the
            // replay path that already exists. Terminal to the queue is not the
            // same as terminal to the record.
            migrationBuilder.Sql("""
                CREATE OR REPLACE FUNCTION reject_terminal_job_rewrite()
                RETURNS trigger AS $$
                BEGIN
                    IF OLD."Status" IN (4, 5, 7) AND NEW."Status" <> OLD."Status" THEN
                        RAISE EXCEPTION
                            'segmentation job % is terminal (status %) and cannot be moved to status %',
                            OLD."Id", OLD."Status", NEW."Status"
                            USING ERRCODE = 'check_violation';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """);

            migrationBuilder.Sql("""
                CREATE TRIGGER trg_segmentation_jobs_terminal_immutable
                BEFORE UPDATE ON "SegmentationJobs"
                FOR EACH ROW
                EXECUTE FUNCTION reject_terminal_job_rewrite();
            """);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(
                "DROP TRIGGER IF EXISTS trg_segmentation_jobs_terminal_immutable ON \"SegmentationJobs\";");
            migrationBuilder.Sql("DROP FUNCTION IF EXISTS reject_terminal_job_rewrite();");

            migrationBuilder.DropIndex(
                name: "IX_SegmentationJobs_ExternalJobId",
                table: "SegmentationJobs");

            migrationBuilder.DropIndex(
                name: "IX_SegmentationJobs_OneActivePerScan",
                table: "SegmentationJobs");

            migrationBuilder.DropIndex(
                name: "IX_SegmentationJobs_ScanId_CreatedAt",
                table: "SegmentationJobs");

            migrationBuilder.DropColumn(
                name: "MonitorLeaseExpiresAt",
                table: "SegmentationJobs");

            migrationBuilder.DropColumn(
                name: "MonitorOwner",
                table: "SegmentationJobs");

            migrationBuilder.CreateIndex(
                name: "IX_SegmentationJobs_ExternalJobId",
                table: "SegmentationJobs",
                column: "ExternalJobId",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_SegmentationJobs_ScanId",
                table: "SegmentationJobs",
                column: "ScanId");
        }
    }
}
