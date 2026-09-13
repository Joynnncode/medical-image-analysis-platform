"""Signing in with GitHub, against the fake GitHub in `stub_github.py`.

A test follows the redirects one at a time, the way a browser would, keeping
cookies between hops. The handshake ends on the frontend's /auth/github with
the session in the URL fragment, which is where these tests read it from.
"""

import secrets
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

from api_client import ApiClient

# The API's default CORS origin, which is also where it sends people back to.
FRONTEND = "http://localhost:5173"


def sign_in_with_github(stack, session: requests.Session | None = None,
                        start: str = "/api/auth/github/login") -> str:
    """Click "Continue with GitHub" and follow redirects until the browser
    would leave for the frontend. Returns that final URL."""
    browser = session or requests.Session()
    url = f"{stack.api_url}{start}"
    for _ in range(8):
        if url.startswith(FRONTEND):
            return url
        response = browser.get(url, allow_redirects=False, timeout=30)
        assert response.status_code == 302, (
            f"{url} answered {response.status_code}: {response.text[:300]}"
        )
        url = urljoin(url, response.headers["Location"])
    raise AssertionError(f"Still redirecting after 8 hops, last at {url}")


def a_github_account() -> tuple[int, str]:
    number = secrets.randbelow(10**9) + 1
    return number, f"user{number}"


def session_from(landing_url: str) -> dict[str, str]:
    parts = urlsplit(landing_url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{FRONTEND}/auth/github"
    return {key: values[0] for key, values in parse_qs(parts.fragment).items()}


def test_signing_in_with_github_ends_on_the_frontend_with_a_working_token(stack):
    github_id, login = a_github_account()
    stack.set_github_user(github_id, login)

    landing = sign_in_with_github(stack)
    session = session_from(landing)

    assert session["name"] == login
    assert ApiClient(stack.api_url, session["token"]).scans().status_code == 200


def test_the_token_travels_in_the_fragment_and_never_the_query_string(stack):
    """A query string reaches the frontend host's logs and Referer headers."""
    stack.set_github_user(*a_github_account())
    landing = sign_in_with_github(stack)
    assert urlsplit(landing).query == ""
    assert "token=" in urlsplit(landing).fragment


def test_signing_in_again_returns_to_the_same_account_even_after_a_rename(stack, small_scan_bytes):
    github_id, login = a_github_account()
    stack.set_github_user(github_id, login)
    first = ApiClient(stack.api_url, session_from(sign_in_with_github(stack))["token"])
    scan_id = first.upload_bytes(small_scan_bytes, "mine.nii.gz").json()["id"]

    stack.set_github_user(github_id, f"{login}-renamed")
    again = session_from(sign_in_with_github(stack))

    assert again["name"] == f"{login}-renamed"
    scans = ApiClient(stack.api_url, again["token"]).scans().json()
    assert scan_id in [scan["id"] for scan in scans]


def test_two_github_accounts_do_not_see_each_others_scans(stack, small_scan_bytes):
    stack.set_github_user(*a_github_account())
    alice = ApiClient(stack.api_url, session_from(sign_in_with_github(stack))["token"])
    scan_id = alice.upload_bytes(small_scan_bytes, "alice.nii.gz").json()["id"]

    stack.set_github_user(*a_github_account())
    bob = ApiClient(stack.api_url, session_from(sign_in_with_github(stack))["token"])

    assert scan_id not in [scan["id"] for scan in bob.scans().json()]
    assert bob.scan(scan_id).status_code == 404


def test_declining_on_github_goes_back_to_the_login_page_saying_so(stack):
    stack.set_github_user(*a_github_account(), decline=True)
    assert sign_in_with_github(stack) == f"{FRONTEND}/login?error=github"


def test_a_callback_this_browser_never_started_is_refused(stack):
    """A code and state arriving without the correlation cookie set when the
    sign-in began: someone else's callback link, replayed or forged."""
    landing = sign_in_with_github(
        stack, start="/api/auth/github/callback?code=anything&state=forged"
    )
    assert landing == f"{FRONTEND}/login?error=github"


def test_opening_the_completion_step_directly_is_refused(stack):
    landing = sign_in_with_github(stack, start="/api/auth/github/complete")
    assert landing == f"{FRONTEND}/login?error=github"
