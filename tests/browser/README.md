# Browser checks

Requires Node.js 20 or later and an installed Google Chrome or Microsoft Edge. From the repository root:

```sh
npm --prefix tests/browser install
npm --prefix tests/browser test
```

The script starts and stops its own loopback server. It uses the repository's actual HTML, CSS, JavaScript, Leaflet and drawing controls. Authenticated search, history, report APIs, map tiles and external Street View are deterministic test fixtures; no account, paid API key or running backend is needed.

Checks cover HIGH/MEDIUM/LOW and empty assessments, distance explanations, feature selection, tabs, point and polygon searches, reports being prepared, report retry and polling, stale background responses, failed searches, and mobile layout. Screenshots, results and a successful Playwright trace are written to the ignored `artifacts/` directory.

For a custom Chromium installation, set `GEOPROX_QA_BROWSER` to its executable path. An optional first script argument selects a different GeoProx checkout. The browser dependency is isolated here and is not needed for deployment.

These checks exercise browser behavior with mocked data. Backend tests and live checks separately verify data services, PDF generation and deployment.
