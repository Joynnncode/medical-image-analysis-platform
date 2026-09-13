# End-to-end tests

Everything a visitor does in the browser, asserted instead of clicked.

```bash
./tests/run.sh
```

About eight seconds, plus a `dotnet build` the first time. The first run also
creates `tests/.venv` and installs into it.

```bash
./tests/run.sh test_click_path.py     # just the happy path
./tests/run.sh -k busy                # one behaviour
./tests/run.sh --keep-logs            # keep the API and stub logs, print where
./tests/run.sh -x                     # stop at the first failure
```

## What a run brings up

| | |
|---|---|
| Postgres | a throwaway database (`medimg_test_<random>`) created on whatever server is already running, and dropped afterwards. The dev database is never opened. |
| AI service | the stub in `stub_ai_service.py`, not the real one |
| GitHub | the stub in `stub_github.py`, for the OAuth sign-in |
| API | the real thing, built from source, on a port picked at random |
| Storage | a temp directory, removed with the rest |
| Frontend | not started |

Needs a Postgres server (`brew services start postgresql@16`), the .NET SDK,
and Python 3.11. No Docker.

## Why the AI service is a stub

The real service spends minutes in torch and needs hundreds of megabytes to
answer one request, which makes it a bad thing to put in a suite meant to run
on every change. The stub speaks the same HTTP contract, returns a real NIfTI
mask, and takes instructions: a test can ask it to be busy, or to fail, and
get that answer immediately instead of arranging a real collision.

So these tests cover the platform, not the model. Everything downstream of
inference is real: storage, the database, auth, the DTOs the frontend reads,
the mask a viewer would load. Only the segmentation itself is fake. For
whether the segmentation is any *good*, see [`evaluation/`](../evaluation).

Two things keep the stub from drifting from the service it stands in for. It
loads the organ registry from `ai-service/app/organs.py` itself, so a new
organ appears in both at once. And it computes voxel counts and volumes with
the same arithmetic as `app/model.py`, so a test can check the numbers the API
reports against the mask it hands back.

## What is covered

`test_click_path.py` is the walkthrough: guest login, upload, the organ list,
segmentation, the numbers on the page, and both files the 3D viewer loads.
It checks that the mask comes back on the same voxel grid as the scan, which
is the difference between an overlay and a mess.

`test_failure_modes.py` is the part that is tedious to reach by hand. A
session that has expired, a file that is not a scan, someone else's scan, and
the three ways the AI service can be unhelpful: busy, broken, or asked for an
organ it does not know. The distinction between *refused* and *failed* has its
own tests, because a scan that was never segmented should not be reported as a
failure, and one that already had a good result should not start looking
broken because the next click arrived at a bad moment.

`test_github_login.py` walks "Continue with GitHub" one redirect at a time
against a fake GitHub: the token arriving in the fragment and never a query
string, the same GitHub id finding its own scans after a rename, two accounts
kept apart, and a declined consent screen or a forged callback landing back
on the login page rather than on an error. The real github.com is not
exercised; its half of the handshake is the stub's.

`test_evaluation_metrics.py` is the arithmetic behind `evaluation/`. Pure
functions, no stack, milliseconds.

## Not covered

The browser. Every button turns into an HTTP call and those calls are what the
suite makes, but nothing here renders React, so a component that fails to draw
a correct response still passes. Niivue's rendering is likewise out of scope.

Cold starts on Render, which is where several of this repo's bugs have come
from, cannot be reproduced locally: nothing here sleeps.
