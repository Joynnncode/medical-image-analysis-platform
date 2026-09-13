"""Fixtures that put a running stack in front of every test."""

import tempfile
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from api_client import ApiClient
from harness import REPO_ROOT, start_stack

SAMPLE_SCAN = REPO_ROOT / "sample_scan.nii.gz"


def pytest_addoption(parser):
    parser.addoption(
        "--keep-logs",
        action="store_true",
        default=False,
        help="Keep the stack's log directory after the run and print its path.",
    )


@pytest.fixture(scope="session")
def stack(request):
    """The API, the AI stub and a throwaway database, up for the whole run."""
    stack, stop = start_stack(keep_logs=request.config.getoption("--keep-logs"))
    yield stack
    stop()


@pytest.fixture(autouse=True)
def ai_stub_answers_normally(request):
    """Undo any per-test change to how the stub behaves.

    Without this a test that leaves the stub "busy" quietly breaks the next
    one, and the failure points at the wrong place.

    Asked for by name rather than as a parameter so that tests which never
    touch the stack (the metric tests) do not drag it up just to reset it.
    """
    yield
    if "stack" in request.fixturenames:
        request.getfixturevalue("stack").set_ai_behaviour(mode="ok")


@pytest.fixture
def anonymous(stack) -> ApiClient:
    """A visitor who has not logged in."""
    return ApiClient(stack.api_url)


@pytest.fixture
def guest(stack) -> ApiClient:
    """A visitor who clicked "Try it as a guest"."""
    return ApiClient(stack.api_url).login_as_guest()


@pytest.fixture(scope="session")
def sample_scan_path() -> Path:
    """The real cropped spleen CT the dashboard offers for download."""
    if not SAMPLE_SCAN.exists():
        pytest.skip(f"{SAMPLE_SCAN.name} is not in the repo")
    return SAMPLE_SCAN


@pytest.fixture(scope="session")
def small_scan_bytes() -> bytes:
    """A tiny synthetic volume, for tests that care about a code path rather
    than about the data. Uploading and segmenting it costs milliseconds."""
    rng = np.random.default_rng(0)
    volume = rng.integers(low=-200, high=300, size=(24, 24, 16)).astype(np.float32)
    affine = np.diag([1.5, 1.5, 2.0, 1.0])

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "small.nii.gz"
        nib.save(nib.Nifti1Image(volume, affine), path)
        return path.read_bytes()


def load_nifti(data: bytes):
    """Read a .nii.gz straight out of an HTTP response body."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "response.nii.gz"
        path.write_bytes(data)
        image = nib.load(path)
        # Detach from the temp file before it goes away.
        return nib.Nifti1Image(image.get_fdata(), image.affine, image.header)
