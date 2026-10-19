const { chromium } = require('playwright-core');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');

const repo = path.resolve(process.argv[2] || path.join(__dirname, '..', '..'));
const output = path.join(__dirname, 'artifacts');
const checks = [];
const check = (name, condition, detail) => {
  assert.ok(condition, `${name}${detail ? `: ${detail}` : ''}`);
  checks.push({ name, passed: true });
  process.stdout.write(`PASS ${name}\n`);
};
const tile = `<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e9eadc"/><path d="M0 0h74v92H0zM158 173h98v83h-98z" fill="#c6ddaf"/><g stroke="#d2cebf" stroke-width="16"><path d="M-20 22L276 197M57 -20L185 276M-20 214L276 64"/></g><g fill="none" stroke="#fff" stroke-width="10"><path d="M-20 22L276 197M57 -20L185 276M-20 214L276 64"/></g><path d="M-20 120L276 155" stroke="#edc974" stroke-width="8"/><g fill="#d6d0c3"><path d="M88 29h25v17H88zM22 148h29v18H22zM182 57h30v20h-30zM146 219h23v17h-23z"/></g></svg>`;
const makeResult = (level = 'HIGH') => {
  const details = level === 'EMPTY' ? [] : level === 'MEDIUM' ? [{ distance_m: 15.6, feature_index: 1, name: 'Test electrical substation', category: 'Sub-Stations', lat: 52.5211, lon: -1.5073, address: 'Test Road' }] : level === 'LOW' ? [{ distance_m: 42.7, feature_index: 1, name: 'Test electrical substation', category: 'Sub-Stations', lat: 52.5212, lon: -1.5075, address: 'Test Road' }] : [
    { distance_m: 8.4, feature_index: 1, name: 'Test petrol station', category: 'Petrol stations / Garages', lat: 52.52096, lon: -1.50706, address: 'Test Road' },
    { distance_m: 48.2, feature_index: 2, name: 'Test electrical substation', category: 'Sub-Stations', lat: 52.5213, lon: -1.5075, address: 'Test Lane' },
    { distance_m: 88.8, feature_index: 3, name: 'Test industrial estate', category: 'Industrial / Manufacturing', lat: 52.5205, lon: -1.5065, address: 'Test Street' }
  ];
  const labels = ['Industrial / Manufacturing', 'Gas holder stations', 'Mining (coal, metalliferous)', 'Petrol stations / Garages', 'Sub-Stations', 'Waste Site - Landfill / Disposal', 'Waste Site - Scrapyard / Metal', 'Waste Site - Other'];
  return {
    center: { lat: 52.520986, lon: -1.507158, display: '52.520986,-1.507158' }, radius_m: 100, permit: 'QA-001',
    summary: { outcome: level === 'EMPTY' ? 'LOW' : level, center: '52.520986,-1.507158', center_coords: { lat: 52.520986, lon: -1.507158 }, radius: 100, permit: 'QA-001', selection_mode: 'point', categories: labels.map(label => { const rows = details.filter(d => d.category === label); return { label, no: rows.length === 0, lt10: rows.some(d => d.distance_m < 10), r10_25: rows.some(d => d.distance_m >= 10 && d.distance_m < 25), r25_100: rows.some(d => d.distance_m >= 25 && d.distance_m <= 100) }; }) },
    details_100m: details,
    map_features: { type: 'FeatureCollection', features: details.map(d => ({ type: 'Feature', properties: { ...d }, geometry: d.feature_index === 2 ? { type: 'Polygon', coordinates: [[[-1.50755,52.52125],[-1.50745,52.52125],[-1.50745,52.52135],[-1.50755,52.52135],[-1.50755,52.52125]]] } : { type: 'Point', coordinates: [d.lon, d.lat] } })) },
    selection: { mode: 'point', center: { lat: 52.520986, lon: -1.507158 } }, artifacts: {}, report: { status: 'pending', url: '/api/search/reports/qa-test' }
  };
};

(async () => {
  await fs.mkdir(output, { recursive: true });
  const server = http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url, 'http://localhost');
      const requested = url.pathname === '/' || url.pathname === '/app' ? '/static/index.html' : url.pathname;
      const filename = path.resolve(repo, '.' + decodeURIComponent(requested));
      if (!filename.startsWith(path.resolve(repo) + path.sep)) { res.writeHead(403).end(); return; }
      const body = await fs.readFile(filename);
      const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml' }[path.extname(filename)] || 'application/octet-stream';
      res.writeHead(200, { 'Content-Type': mime, 'Cache-Control': 'no-store' }); res.end(body);
    } catch { res.writeHead(404).end('Not found'); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  let browser;
  let page;
  try {
    const launchOptions = process.env.GEOPROX_QA_BROWSER
      ? [{ executablePath: process.env.GEOPROX_QA_BROWSER }]
      : [{ channel: 'chrome' }, { channel: 'msedge' }];
    let browserError;
    for (const options of launchOptions) {
      try { browser = await chromium.launch({ ...options, headless: true }); break; }
      catch (error) { browserError = error; }
    }
    if (!browser) throw new Error(`Install Google Chrome or Microsoft Edge, or set GEOPROX_QA_BROWSER to a Chromium executable. ${browserError?.message || ''}`);
    const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1, reducedMotion: 'reduce' });
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
    page = await context.newPage();
    const errors = [];
    page.on('pageerror', err => errors.push(err.message));
    let scenario = 'HIGH';
    let reportMode = 'hold';
    let reportRelease;
    let reportRequests = 0;
    let processingResponses = 0;
    let searchPayload;
    const heldReports = [];
    await page.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      const json = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
      if (url.pathname === '/auth-status') return json({ authenticated: true, user: 'Browser QA' });
      if (url.pathname === '/api/history') return json({ history: [{ timestamp: '2026-10-19T12:00:00Z', location: '52.520986,-1.507158', outcome: 'HIGH' }] });
      if (url.pathname === '/api/search') {
        searchPayload = request.postDataJSON();
        if (scenario === 'FAIL') return json({ error: 'Map data service unavailable. No proximity assessment completed.' }, 503);
        return json({ status: 'done', result: makeResult(scenario) });
      }
      if (url.pathname.startsWith('/api/search/reports/')) {
        reportRequests++;
        const reportLevel = scenario === 'FAIL' ? 'HIGH' : scenario;
        if (reportMode === 'hold') await new Promise(resolve => { reportRelease = resolve; heldReports.push(resolve); });
        const result = makeResult(reportLevel);
        if (reportMode === 'fail') { result.report.status = 'error'; result.report.error = 'Test report rendering failed'; return json({ status: 'error', error: 'Test report rendering failed', result }, 500); }
        if (reportMode === 'processing' && processingResponses-- > 0) { result.report.status = 'pending'; result.report.retry_after_seconds = 1; return json({ status: 'processing', result }); }
        result.report.status = 'ready'; result.artifacts = { pdf_url: '/qa-report.pdf', map_url: '/qa-report-map.html' };
        return json({ status: 'done', result });
      }
      if (url.pathname === '/api/permits') return json({ status: 'saved', search_result: makeResult(scenario) });
      if (url.pathname === '/qa-report.pdf') return route.fulfill({ status: 200, contentType: 'application/pdf', body: '%PDF-1.4 QA' });
      if (url.pathname === '/qa-report-map.html') return route.fulfill({ status: 200, contentType: 'text/html', body: '<p>QA report map</p>' });
      if (url.host.includes('tile.openstreetmap.org')) return route.fulfill({ status: 200, contentType: 'image/svg+xml', body: tile });
      if (url.origin !== base && !url.protocol.startsWith('data') && url.protocol !== 'about:') return route.fulfill({ status: 200, contentType: 'text/html', body: '<html><body style="font:20px system-ui;color:#567;background:#eff3f7">External Street View content mocked for browser QA.</body></html>' });
      return route.continue();
    });
    const waitText = (selector, text) => page.waitForFunction(({selector, text}) => document.querySelector(selector)?.textContent.includes(text), {selector, text}, {timeout: 10000});
    const screenshot = async name => { await page.waitForTimeout(350); return page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true }); };
    const run = async () => { await page.locator('#location').fill('52.520986,-1.507158'); await page.locator('#permit').fill('QA-001'); await page.waitForTimeout(350); await page.locator('#runBtn').click(); };
    const noOverflow = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);

    await page.goto(base + '/app', { waitUntil: 'networkidle' });
    await page.waitForSelector('#pickerMap.leaflet-container');
    check('Initial assessment has no LOW badge', !(await page.locator('#outcomeBadge').isVisible()));
    check('Initial PDF download disabled', (await page.locator('#downloadBtn').getAttribute('aria-disabled')) === 'true');
    check('Desktop page has no horizontal overflow', await noOverflow());
    await screenshot('01-desktop-initial');

    await run();
    await waitText('#outcomeBadge', 'HIGH');
    check('Search opts into deferred reports', searchPayload.defer_reports === true);
    check('HIGH assessment appears while report request pending', await page.locator('#outcomeBadge').isVisible() && reportRequests > 0);
    check('Risk reason explains high assessment', /10|8\.4|petrol/i.test(await page.locator('#resultReason').innerText()));
    check('Nearest feature shows precise distance', /8\.4/.test(await page.locator('.nearest-detail').innerText()));
    check('PDF unavailable while report pending', (await page.locator('#downloadBtn').getAttribute('aria-disabled')) === 'true');
    check('Report map and permit save unavailable while report pending', await page.locator('#openMapBtn').isDisabled() && await page.locator('#savePermitBtn').isDisabled());
    check('Features appear in results list', (await page.locator('#featureList').innerText()).includes('Test petrol station'));
    check('Completed assessment automatically comes into desktop viewport', await page.locator('#outcomeBadge').evaluate(el => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= window.innerHeight; }));
    await screenshot('02-desktop-high-pending');
    await page.screenshot({ path: path.join(output, '02a-desktop-assessment-viewport.png'), fullPage: false });

    const featureButton = page.locator('#featureList button').filter({ hasText: 'Test electrical substation' }).first();
    await featureButton.click();
    await page.waitForSelector('.leaflet-popup-content');
    check('Clicking feature list highlights corresponding map feature', (await page.locator('.leaflet-popup-content').innerText()).includes('Test electrical substation'));
    await screenshot('03-desktop-feature-selected');
    await page.locator('.leaflet-popup-close-button').click();
    const featureMarker = page.locator('#pickerMap .leaflet-overlay-pane .leaflet-interactive').first();
    if (await featureMarker.count()) {
      await featureMarker.click({force: true});
      await page.waitForSelector('.leaflet-popup-content');
    check('Clicking map feature opens details', (await page.locator('.leaflet-popup-content').last().innerText()).length > 0);
    }
    reportMode = 'ready';
    reportRelease();
    await page.waitForFunction(() => document.querySelector('#downloadBtn')?.getAttribute('href')?.includes('qa-report.pdf'));
    check('Deferred report enables PDF without rerunning search', reportRequests === 1 && (await page.locator('#outcomeBadge').innerText()).trim() === 'HIGH');
    check('Ready report enables map and permit save', !(await page.locator('#openMapBtn').isDisabled()) && !(await page.locator('#savePermitBtn').isDisabled()));
    await screenshot('04-desktop-high-report-ready');

    await page.locator('#tab-history').click();
    check('History tab displays saved assessments', await page.locator('#historyBody').isVisible() && (await page.locator('#historyBody').innerText()).includes('HIGH'));
    await screenshot('05-desktop-history');
    await page.locator('#tab-streetview').click();
    check('Street View tab displays preview', await page.locator('#streetViewFrame').isVisible());
    await screenshot('06-desktop-streetview');
    await page.locator('#tab-map').click();

    scenario = 'LOW'; reportMode = 'fail';
    await run(); await waitText('#outcomeBadge', 'LOW');
    await page.waitForFunction(() => !document.querySelector('#retryReportBtn')?.hidden);
    check('LOW assessment remains valid after report-only error', await page.locator('#outcomeBadge').isVisible() && (await page.locator('#outcomeBadge').innerText()).trim() === 'LOW');
    check('Report-only error offers retry', await page.locator('#retryReportBtn').isVisible());
    await screenshot('07-desktop-report-failed');
    reportMode = 'ready'; await page.locator('#retryReportBtn').click();
    await page.waitForFunction(() => document.querySelector('#downloadBtn')?.getAttribute('href')?.includes('qa-report.pdf'));
    check('Report retry enables PDF', (await page.locator('#downloadBtn').getAttribute('aria-disabled')) === 'false');

    scenario = 'MEDIUM'; reportMode = 'ready';
    await run(); await waitText('#outcomeBadge', 'MEDIUM');
    check('MEDIUM assessment explains the category distance band', /15\.6/.test(await page.locator('#resultReason').innerText()) && /25/.test(await page.locator('#resultReason').innerText()));
    await screenshot('07b-desktop-medium');
    scenario = 'EMPTY'; await run(); await waitText('#outcomeBadge', 'LOW');
    check('Zero-feature assessment shows truthful no-match explanation', /No matching mapped features/i.test(await page.locator('#resultReason').innerText()) && /assessment bands/i.test(await page.locator('#resultReason').innerText()));
    check('Zero-feature assessment clears old nearest feature', /No matching features found/.test(await page.locator('#nearestFeature').innerText()) && (await page.locator('#featureList button').count()) === 0);
    await screenshot('07c-desktop-no-features');

    scenario = 'HIGH'; reportMode = 'processing'; processingResponses = 1;
    const reportsBeforeProcessing = reportRequests;
    await run(); await waitText('#outcomeBadge', 'HIGH');
    check('Processing report keeps assessment visible and download disabled', (await page.locator('#downloadBtn').getAttribute('aria-disabled')) === 'true' && await page.locator('#outcomeBadge').isVisible());
    await page.waitForFunction(() => document.querySelector('#downloadBtn')?.getAttribute('href')?.includes('qa-report.pdf'));
    check('Processing report automatically retries until ready', reportRequests === reportsBeforeProcessing + 2);

    scenario = 'FAIL'; await run();
    await waitText('#errorTxt', 'Map data service');
    check('Failed search clears previous risk badge', !(await page.locator('#outcomeBadge').isVisible()));
    check('Failed search clears previous PDF', !(await page.locator('#downloadBtn').getAttribute('href')));
    await screenshot('08-desktop-search-failed');

    scenario = 'HIGH'; reportMode = 'hold';
    reportRelease = null;
    await run(); await waitText('#outcomeBadge', 'HIGH');
    for (let count = 0; count < 50 && !reportRelease; count++) await page.waitForTimeout(20);
    const releaseOldReport = reportRelease;
    check('A second search can run during deferred report generation', !!releaseOldReport && !(await page.locator('#runBtn').isDisabled()));
    scenario = 'LOW'; reportMode = 'ready';
    await run(); await waitText('#outcomeBadge', 'LOW');
    await page.waitForFunction(() => document.querySelector('#downloadBtn')?.getAttribute('href')?.includes('qa-report.pdf'));
    releaseOldReport(); await page.waitForTimeout(150);
    check('Late report response cannot overwrite a newer assessment', (await page.locator('#outcomeBadge').innerText()).trim() === 'LOW' && /42\.7/.test(await page.locator('.nearest-detail').innerText()));

    const locationBeforeClick = await page.locator('#location').inputValue();
    const mapBox = await page.locator('#pickerMap').boundingBox();
    await page.mouse.click(mapBox.x + mapBox.width * 0.75, mapBox.y + mapBox.height * 0.65);
    check('Point mode map click updates location', await page.locator('#location').inputValue() !== locationBeforeClick);
    await page.locator('.mode-btn[data-mode="polygon"]').click();
    await page.locator('.leaflet-draw-draw-polygon').click();
    const polyBox = await page.locator('#pickerMap').boundingBox();
    await page.mouse.click(polyBox.x + polyBox.width * 0.35, polyBox.y + polyBox.height * 0.35);
    await page.waitForTimeout(150);
    await page.mouse.click(polyBox.x + polyBox.width * 0.65, polyBox.y + polyBox.height * 0.35);
    await page.waitForTimeout(150);
    await page.mouse.click(polyBox.x + polyBox.width * 0.5, polyBox.y + polyBox.height * 0.65);
    await page.waitForTimeout(150);
    await page.getByText('Finish', { exact: true }).click();
    scenario = 'HIGH'; reportMode = 'ready';
    await page.locator('#runBtn').click(); await waitText('#outcomeBadge', 'HIGH');
    check('Polygon mode sends drawn polygon', searchPayload.selection_mode === 'polygon' && searchPayload.polygon.length >= 3);
    await screenshot('09-desktop-polygon');
    await page.locator('.mode-btn[data-mode="point"]').click();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    scenario = 'HIGH'; reportMode = 'ready'; await run(); await waitText('#outcomeBadge', 'HIGH');
    check('Mobile page has no horizontal overflow', await noOverflow());
    check('Mobile search button remains usable', await page.locator('#runBtn').isVisible());
    check('Completed assessment automatically comes into mobile viewport', await page.locator('#outcomeBadge').evaluate(el => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= window.innerHeight; }));
    await screenshot('10-mobile-high');
    await page.screenshot({ path: path.join(output, '10a-mobile-assessment-viewport.png'), fullPage: false });
    await page.locator('#featureList button').filter({ hasText: 'Test electrical substation' }).first().click();
    await page.waitForTimeout(350);
    check('Mobile feature selection brings map popup into view', await page.locator('.leaflet-popup-content').last().evaluate(el => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= window.innerHeight; }));
    await page.screenshot({ path: path.join(output, '10b-mobile-map-feature-viewport.png'), fullPage: false });
    await page.locator('#tab-history').click();
    check('Mobile history tab is reachable', await page.locator('#historyBody').isVisible());
    check('Mobile history has no horizontal overflow', await noOverflow());
    await screenshot('11-mobile-history');
    check('Browser reports no unhandled JavaScript errors', errors.length === 0, errors.join('; '));
    await context.tracing.stop({ path: path.join(output, 'trace.zip') });
    await fs.writeFile(path.join(output, 'results.json'), JSON.stringify({ passed: true, checks, errors, screenshots: output }, null, 2));
    process.stdout.write(`\n${checks.length} checks passed. Artifacts: ${output}\n`);
  } catch (error) {
    if (page) { await page.screenshot({ path: path.join(output, 'FAILURE.png'), fullPage: true }).catch(() => {}); await fs.writeFile(path.join(output, 'failure-dom.html'), await page.content().catch(() => '')); }
    await fs.writeFile(path.join(output, 'results.json'), JSON.stringify({ passed: false, checks, error: String(error), stack: error.stack }, null, 2));
    process.stderr.write(error.stack + '\n'); process.exitCode = 1;
  } finally { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
})();
