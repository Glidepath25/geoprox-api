# GeoProx API (MVP)

## Setup
```bash
python -m venv .venv
. .venv/Scripts/activate   # Windows PowerShell
pip install -r requirements.txt
```

## Overpass data service

For Overspan, set the `OVERSPAN_API_KEY` environment variable. GeoProx then uses
`https://api.overspan.dev/api/interpreter` and sends the key in an Authorization
header from the backend. Its queries and assessment rules remain the same.

The App Runner configuration loads this variable from the `OVERSPAN_API_KEY`
JSON field in the existing `apprunner_MVP2` secret in Secrets Manager
(Ireland / eu-west-1). Add this field before deploying the configuration.
App Runner loads the secret during deployment.

Set the `OVERPASS_ENDPOINTS` environment variable in the hosting service to use
your own or a provider's Overpass interpreter. Supply full HTTPS URLs separated
by commas or whitespace, in the order they should be tried. For example:

```text
OVERPASS_ENDPOINTS=https://your-overpass.example/api/interpreter
```

When set, this overrides automatic Overspan selection and the public defaults.
Redeploy after changing it. Without an override or Overspan key, GeoProx tries
Private.coffee and overpass-api.de. Availability of
those public services is outside GeoProx's control; retries cannot fix an outage
or an access restriction. A failed or incomplete query produces no assessment.

## What3words API key

Set `WHAT3WORDS_API_KEY` in your environment or place the key in `config/what3words_key.txt` (one line, no quotes).

## Search workspace and deferred reports

The browser uses one interactive map for point/polygon selection and assessment
features. Recent searches and Street View are available in tabs. Results include
an explanation, exact feature distances and geometries linked to the map.
Existing category thresholds and synchronous API behavior are preserved.

The workspace sends `defer_reports: true` to `POST /api/search`. This returns the
completed assessment before rendering PDF/static-map files. Its `result.report`
contains `status: pending` and a URL. The browser then posts to that URL to build
the reports from the saved assessment, without another Overpass query or search
quota charge. The response is `done` with ready artifacts, `processing` while
another request holds the generation lease, or `error` with the valid assessment
and a retry URL. Report jobs use the existing application database; their table
is created automatically. Files use a unique prefix per report attempt.

Downloads and permit saving become available when report files are ready. A
report failure leaves the assessment visible and offers a report-only retry.
Requests that omit `defer_reports` keep the original synchronous behavior.

Backend checks: `python -m unittest discover -s tests -q`.

## Mobile API Authentication

The API now issues JWTs for mobile clients alongside the existing browser session cookies.

- Set `JWT_SECRET` in the environment (falls back to `SESSION_SECRET` for development).
- Optional overrides: `JWT_ACCESS_TTL` (seconds, default 3600) and `JWT_REFRESH_TTL` (default 30 days).
- Endpoints: `POST /api/mobile/auth/login`, `POST /api/mobile/auth/refresh`, `POST /api/mobile/auth/logout`.
