"""The path a visitor actually walks, asserted instead of clicked.

Guest login, upload, pick an organ, segment, read the numbers, load the
overlay. If this file is green, the demo works.
"""

import uuid

import numpy as np
import pytest

from api_client import ApiClient
from conftest import load_nifti


def test_the_api_is_up(anonymous):
    assert anonymous.get("/health").json() == {"status": "ok"}


def test_the_organ_list_comes_from_the_ai_service(anonymous):
    """The dropdown on the dashboard is filled from the service's own
    registry, not from a list copied into the frontend."""
    response = anonymous.organs()
    assert response.status_code == 200

    body = response.json()
    keys = [organ["key"] for organ in body["organs"]]

    assert body["default"] in keys
    assert "spleen" in keys
    assert len(keys) == len(set(keys))
    for organ in body["organs"]:
        assert organ["displayName"]


def test_guest_login_gives_a_working_session(anonymous):
    response = anonymous.post("/api/auth/guest")
    assert response.status_code == 200

    body = response.json()
    assert body["token"]
    assert body["email"] == "Guest"
    assert body["expiresAt"]

    # The token is the whole point: it has to open a route that needs one.
    assert ApiClient(anonymous.base_url, body["token"]).scans().status_code == 200


def test_a_new_guest_starts_with_no_scans(guest):
    assert guest.scans().json() == []


def test_upload_then_segment_then_read_the_overlay(guest, sample_scan_path):
    """The full click-through on the real sample scan."""
    upload = guest.upload(sample_scan_path)
    assert upload.status_code == 200, upload.text

    scan = upload.json()
    scan_id = scan["id"]
    assert scan["fileName"] == sample_scan_path.name
    assert scan["status"] == "Uploaded"

    # It shows up on the dashboard.
    listed = guest.scans().json()
    assert [s["id"] for s in listed] == [scan_id]

    # Run segmentation.
    segmented = guest.segment(scan_id, organ="spleen")
    assert segmented.status_code == 200, segmented.text

    detail = segmented.json()
    assert detail["status"] == "Completed"

    result = detail["result"]
    assert result is not None
    assert result["organ"] == "spleen"
    assert result["organDisplayName"] == "Spleen"
    assert result["modelName"] == "spleen_ct_segmentation"
    assert result["voxelCount"] > 0
    assert result["volumeMl"] > 0
    assert result["inferenceTimeMs"] > 0

    # Re-reading the scan gives the same thing, so the result was persisted
    # rather than only returned.
    assert guest.scan(scan_id).json() == detail

    # The viewer loads two files: the scan and the mask.
    original_response = guest.original_file(scan_id)
    assert original_response.status_code == 200
    original = load_nifti(original_response.content)

    mask_response = guest.mask(scan_id)
    assert mask_response.status_code == 200
    mask = load_nifti(mask_response.content)

    # Niivue overlays the mask voxel-for-voxel, so a mask on a different grid
    # is a broken overlay however good the segmentation was.
    assert mask.shape == original.shape
    np.testing.assert_allclose(mask.affine, original.affine, atol=1e-5)

    # The numbers on the page describe the mask that was handed back.
    mask_data = mask.get_fdata()
    assert set(np.unique(mask_data)) <= {0.0, 1.0}
    assert int(np.count_nonzero(mask_data)) == result["voxelCount"]

    voxel_volume_mm3 = abs(np.linalg.det(original.affine[:3, :3]))
    assert result["volumeMl"] == pytest.approx(
        result["voxelCount"] * voxel_volume_mm3 / 1000.0, rel=1e-3
    )


def test_a_second_segmentation_replaces_the_first(guest, small_scan_bytes):
    """Picking a different organ and running again updates the one result the
    scan carries, rather than accumulating rows or leaving the old numbers."""
    scan_id = guest.upload_bytes(small_scan_bytes, "small.nii.gz").json()["id"]

    first = guest.segment(scan_id, organ="spleen").json()["result"]
    assert first["organ"] == "spleen"

    second = guest.segment(scan_id, organ="liver").json()["result"]
    assert second["organ"] == "liver"
    assert second["organDisplayName"] == "Liver"
    assert second["modelName"] == "wholeBody_ct_segmentation"

    assert guest.scan(scan_id).json()["result"]["organ"] == "liver"


@pytest.mark.parametrize("organ", ["spleen", "liver", "kidney_left", "urinary_bladder"])
def test_every_organ_in_the_dropdown_can_be_segmented(guest, small_scan_bytes, organ):
    scan_id = guest.upload_bytes(small_scan_bytes, "small.nii.gz").json()["id"]
    response = guest.segment(scan_id, organ=organ)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["organ"] == organ


def test_register_then_log_in(anonymous):
    email = f"tester-{uuid.uuid4().hex[:8]}@example.com"
    password = "correct-horse-battery"

    registered = anonymous.register(email, password)
    assert registered.status_code == 200
    assert registered.json()["email"] == email

    logged_in = anonymous.login(email, password)
    assert logged_in.status_code == 200
    assert logged_in.json()["token"]

    assert anonymous.login(email, "wrong-password").status_code == 401


def test_scans_are_private_to_the_account_that_uploaded_them(stack, small_scan_bytes):
    owner = ApiClient(stack.api_url).login_as_guest()
    stranger = ApiClient(stack.api_url).login_as_guest()

    scan_id = owner.upload_bytes(small_scan_bytes, "small.nii.gz").json()["id"]
    owner.segment(scan_id)

    assert stranger.scans().json() == []
    # Not 403: another account's scan should be indistinguishable from one
    # that does not exist.
    assert stranger.scan(scan_id).status_code == 404
    assert stranger.original_file(scan_id).status_code == 404
    assert stranger.mask(scan_id).status_code == 404
    assert stranger.segment(scan_id).status_code == 404
