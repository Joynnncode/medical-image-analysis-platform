"""The browser's side of the conversation, as a small Python client.

Every button in the frontend turns into one of these calls, so a test written
against this client is the click-through, minus the rendering.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path

import requests

DEFAULT_TIMEOUT_S = 60


class ApiClient:
    def __init__(self, base_url: str, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def get(self, path: str, **kwargs) -> requests.Response:
        return requests.get(
            f"{self.base_url}{path}",
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT_S,
            **kwargs,
        )

    def post(self, path: str, **kwargs) -> requests.Response:
        return requests.post(
            f"{self.base_url}{path}",
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT_S,
            **kwargs,
        )

    # --- what the buttons do -------------------------------------------------

    def login_as_guest(self) -> "ApiClient":
        """"Try it as a guest" on the login page."""
        response = self.post("/api/auth/guest")
        response.raise_for_status()
        self.token = response.json()["token"]
        return self

    def register(self, email: str, password: str) -> requests.Response:
        return self.post(
            "/api/auth/register", json={"email": email, "password": password}
        )

    def login(self, email: str, password: str) -> requests.Response:
        return self.post(
            "/api/auth/login", json={"email": email, "password": password}
        )

    def organs(self) -> requests.Response:
        return self.get("/api/organs")

    def upload(self, file_path: Path, file_name: str | None = None) -> requests.Response:
        """Dropping a file on the dashboard's upload zone."""
        name = file_name or file_path.name
        with file_path.open("rb") as handle:
            return requests.post(
                f"{self.base_url}/api/scans",
                headers=self._headers(),
                files={"file": (name, handle, "application/gzip")},
                timeout=DEFAULT_TIMEOUT_S,
            )

    def upload_bytes(self, data: bytes, file_name: str) -> requests.Response:
        return requests.post(
            f"{self.base_url}/api/scans",
            headers=self._headers(),
            files={"file": (file_name, data, "application/octet-stream")},
            timeout=DEFAULT_TIMEOUT_S,
        )

    def scans(self) -> requests.Response:
        return self.get("/api/scans")

    def scan(self, scan_id: str) -> requests.Response:
        return self.get(f"/api/scans/{scan_id}")

    def segment(self, scan_id: str, organ: str = "spleen") -> requests.Response:
        """The "Run segmentation" button."""
        return self.post(f"/api/scans/{scan_id}/segment", params={"organ": organ})

    def original_file(self, scan_id: str) -> requests.Response:
        return self.get(f"/api/scans/{scan_id}/file")

    def mask(self, scan_id: str) -> requests.Response:
        return self.get(f"/api/scans/{scan_id}/mask")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def expired_token(key: str, issuer: str = "MedicalImageAnalysis") -> str:
    """A correctly signed token whose lifetime has already run out.

    Waiting out the real 12-hour expiry is not an option, and neither is
    reaching into the API to shorten it, so the token is minted here with the
    same claims and signing key the API uses.
    """
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(uuid.uuid4()),
        "email": "expired@example.com",
        "jti": str(uuid.uuid4()),
        "iss": issuer,
        "aud": issuer,
        "nbf": now - 7200,
        "iat": now - 7200,
        "exp": now - 3600,
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    signature = hmac.new(
        key.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64url(signature)}"
