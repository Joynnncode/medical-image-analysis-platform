"""The states that are tedious to reach by clicking.

A busy AI service, a failing one, a session that has run out, a file that is
not a scan. Most of these need the AI service to misbehave on cue, which is
why the stub takes instructions.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from api_client import ApiClient, expired_token
from harness import TEST_JWT_KEY


# --- authentication ---------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/api/scans", "/api/scans/00000000-0000-0000-0000-000000000000"],
)
def test_protected_routes_refuse_a_visitor_with_no_token(anonymous, path):
    assert anonymous.get(path).status_code == 401


def test_a_garbage_token_is_refused(stack):
    assert ApiClient(stack.api_url, "not-a-jwt").scans().status_code == 401


def test_a_token_whose_lifetime_ran_out_is_refused(stack):
    """Tokens last 12 hours. Once one has expired the API answers 401 on every
    route, which is what the frontend's session handling keys off."""
    stale = ApiClient(stack.api_url, expired_token(TEST_JWT_KEY))
    assert stale.scans().status_code == 401


def test_a_token_signed_with_the_wrong_key_is_refused(stack):
    forged = ApiClient(stack.api_url, expired_token("a-different-key-of-sufficient-length"))
    assert forged.scans().status_code == 401


# --- what gets uploaded -----------------------------------------------------


@pytest.mark.parametrize("file_name", ["scan.txt", "scan.png", "scan", "scan.nii.zip"])
def test_only_nifti_files_are_accepted(guest, small_scan_bytes, file_name):
    response = guest.upload_bytes(small_scan_bytes, file_name)
    assert response.status_code == 400


def test_an_empty_file_is_rejected(guest):
    assert guest.upload_bytes(b"", "empty.nii.gz").status_code == 400


def test_segmenting_a_scan_that_does_not_exist_is_a_404(guest):
    missing = "00000000-0000-0000-0000-000000000000"
    assert guest.segment(missing).status_code == 404


def test_the_mask_is_not_there_before_a_segmentation_runs(guest, small_scan_bytes):
    scan_id = guest.upload_bytes(small_scan_bytes, "small.nii.gz").json()["id"]
    assert guest.scan(scan_id).json()["result"] is None
    assert guest.mask(scan_id).status_code == 404


# --- the AI service misbehaving ---------------------------------------------


def test_a_busy_ai_service_leaves_the_scan_alone(stack, guest, small_scan_bytes):
    """The AI service runs one segmentation at a time and refuses the rest.

    Nothing ran, so this is not a failed segmentation: the scan has to come
    back to the status it had. Marking it Failed here reports an error for
    work that was never attempted.
    """
    scan_id = guest.upload_bytes(small_scan_bytes, "small.nii.gz").json()["id"]

    stack.set_ai_behaviour(mode="busy")
    refused = guest.segment(scan_id)

    assert refused.status_code == 503
    assert refused.headers.get("Retry-After") == "30"
    assert guest.scan(scan_id).json()["status"] == "Uploaded"


def test_a_busy_ai_service_does_not_erase_an_earlier_result(
    stack, guest, small_scan_bytes
):
    """A scan that already has a perfectly good result should not start
    looking broken because the next click arrived at a bad moment."""
    scan_id = guest.upload_bytes(small_scan_bytes, "small.nii.gz").json()["id"]
    guest.segment(scan_id, organ="spleen")

    stack.set_ai_behaviour(mode="busy")
    assert guest.segment(scan_id, organ="liver").status_code == 503

    after = guest.scan(scan_id).json()
    assert after["status"] == "Completed"
    assert after["result"]["organ"] == "spleen"
    assert guest.mask(scan_id).status_code == 200


def test_two_segmentations_at_once_are_not_both_run(stack, small_scan_bytes):
    """The same backpressure, reached the way a real collision reaches it:
    two clicks overlapping, rather than the stub being told to refuse."""
    owner = ApiClient(stack.api_url).login_as_guest()
    other = ApiClient(stack.api_url).login_as_guest()

    first_scan = owner.upload_bytes(small_scan_bytes, "small.nii.gz").json()["id"]
    second_scan = other.upload_bytes(small_scan_bytes, "small.nii.gz").json()["id"]

    # Hold the single inference slot open long enough for both requests to be
    # in flight at the same time.
    stack.set_ai_behaviour(mode="ok", delay_seconds=3.0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(owner.segment, first_scan),
            pool.submit(other.segment, second_scan),
        ]
        statuses = sorted(future.result().status_code for future in futures)

    assert statuses == [200, 503]


def test_a_failing_ai_service_marks_the_scan_failed(stack, guest, small_scan_bytes):
    """A run that was attempted and broke is a different thing from one that
    was refused, and the scan should say so."""
    scan_id = guest.upload_bytes(small_scan_bytes, "small.nii.gz").json()["id"]

    stack.set_ai_behaviour(mode="fail")
    response = guest.segment(scan_id)

    assert response.status_code == 502
    assert guest.scan(scan_id).json()["status"] == "Failed"


def test_an_organ_the_service_does_not_know_is_not_segmented(guest, small_scan_bytes):
    scan_id = guest.upload_bytes(small_scan_bytes, "small.nii.gz").json()["id"]
    response = guest.segment(scan_id, organ="left-earlobe")

    assert response.status_code == 502
    assert guest.scan(scan_id).json()["result"] is None


def test_the_stack_recovers_after_a_failure(stack, guest, small_scan_bytes):
    """A failed run must not leave anything stuck. The next click works."""
    scan_id = guest.upload_bytes(small_scan_bytes, "small.nii.gz").json()["id"]

    stack.set_ai_behaviour(mode="fail")
    assert guest.segment(scan_id).status_code == 502

    stack.set_ai_behaviour(mode="ok")
    retried = guest.segment(scan_id)
    assert retried.status_code == 200
    assert retried.json()["status"] == "Completed"
