"""A stand-in for github.com, for the GitHub sign-in tests.

Signing in with GitHub is a handshake between a browser, the API and GitHub,
and the real GitHub cannot take part in a test run: it wants a person at the
consent screen and an OAuth app whose callback is a public URL. This speaks
the three endpoints the API's OAuth handler uses, the same way GitHub does:

  * `GET /login/oauth/authorize` sends the browser straight back to the
    callback with a one-time code, as GitHub does once the user has agreed,
  * `POST /login/oauth/access_token` trades the code for a token, and answers
    a bad code with a 200 carrying an `error`, which is what GitHub does,
  * `GET /user` returns the profile for that token.

`POST /__control` picks who is signing in next, or makes them decline on the
consent screen. Prefixed like the AI stub's, to keep it visibly not part of
the contract under test.
"""

import secrets
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

CLIENT_ID = "test-github-client-id"
CLIENT_SECRET = "test-github-client-secret"

app = FastAPI(title="GitHub stub")


class Control(BaseModel):
    id: int = 1
    login: str = "octocat"
    decline: bool = False


_control = Control()
_codes: dict[str, Control] = {}
_tokens: dict[str, Control] = {}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/__control")
def set_control(control: Control):
    global _control
    _control = control
    return _control


@app.get("/login/oauth/authorize")
def authorize(client_id: str, redirect_uri: str, state: str):
    if client_id != CLIENT_ID:
        raise HTTPException(status_code=404, detail="Unknown OAuth app")

    if _control.decline:
        query = {"error": "access_denied", "state": state}
    else:
        code = secrets.token_hex(10)
        _codes[code] = _control
        query = {"code": code, "state": state}
    return RedirectResponse(f"{redirect_uri}?{urlencode(query)}", status_code=302)


@app.post("/login/oauth/access_token")
def access_token(
    client_id: str = Form(),
    client_secret: str = Form(),
    code: str = Form(),
):
    # Codes are single-use on GitHub too.
    user = _codes.pop(code, None)
    if client_id != CLIENT_ID or client_secret != CLIENT_SECRET or user is None:
        return {"error": "bad_verification_code"}

    token = secrets.token_hex(20)
    _tokens[token] = user
    return {"access_token": token, "token_type": "bearer", "scope": ""}


@app.get("/user")
def user(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    profile = _tokens.get(token)
    if profile is None:
        raise HTTPException(status_code=401, detail="Bad credentials")

    # No email: with the default scope GitHub only includes one the user has
    # made public, and the API must not depend on it.
    return {"id": profile.id, "login": profile.login, "name": None, "email": None}
