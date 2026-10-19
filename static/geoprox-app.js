(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const form = $('searchForm');
  const locationEl = $('location');
  const radiusEl = $('radius');
  const permitEl = $('permit');
  const modeButtons = [...document.querySelectorAll('.mode-btn')];
  const categoryLabels = {
    manufacturing: 'Industrial / Manufacturing', gas_holding: 'Gas holder stations', mines: 'Mining (coal, metalliferous)',
    petrol_stations: 'Petrol stations / Garages', substations: 'Sub-Stations', landfills: 'Waste Site - Landfill & Treatment / Disposal',
    scrapyards: 'Waste Site - Scrapyard / Metal Recycling', waste_disposal: 'Waste Site - Other', sewage_treatment: 'Sewage Treatment Works',
  };
  let map, originMarker, drawnItems, drawControl, resultLayers, radiusLayers;
  let polygonCoords = null;
  let selectionMode = 'point';
  let latestSearchResult = null;
  let searchRevision = 0;
  let searchBusy = false;
  let reportBusy = false;
  let saveBusy = false;
  let activeTab = 'map';
  let streetCoords = null;
  let expanded = false;
  let featureLayers = new Map();

  const text = (id, value) => { $(id).textContent = value ?? ''; };
  const node = (tag, value, className) => {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = value;
    if (className) element.className = className;
    return element;
  };
  const distance = (value) => {
    const number = Number(value);
    if (!Number.isFinite(number)) return 'Distance unavailable';
    // Keep small, non-zero distances visible instead of rounding them to zero.
    if (number > 0 && number < .1) return '<0.1 m';
    return `${number.toLocaleString('en-GB', { maximumFractionDigits: 1 })} m`;
  };
  const isPetrol = (feature) => /petrol|fuel/i.test(feature.category || '');
  const proximity = (feature) => {
    const metres = Number(feature.distance_m);
    return metres < (isPetrol(feature) ? 25 : 10) ? 'HIGH' : metres < (isPetrol(feature) ? 50 : 25) ? 'MEDIUM' : 'LOW';
  };
  const featureName = (feature) => feature.name && feature.name !== '(unnamed)' ? feature.name : feature.category || 'Unnamed mapped feature';
  const features = (result) => (Array.isArray(result.details_100m) ? result.details_100m : [])
    .filter((row) => Number.isFinite(Number(row.distance_m)))
    .map((row, index) => ({ ...row, feature_index: row.feature_index ?? index }))
    .sort((a, b) => Number(a.distance_m) - Number(b.distance_m));

  const normaliseDmsSymbols = (input) => (
      input
        ? input
            .replace(/[º˚]/g, '°')
            .replace(/[’′]/g, "'")
            .replace(/[“”″]/g, '"')
        : input
    );
    const splitDmsTokens = (input) => {
      if (!input) return null;
      const tokens = [];
      let buffer = '';
      for (const ch of input) {
        buffer += ch;
        if ('NSEW'.includes(ch.toUpperCase())) {
          const trimmed = buffer.trim();
          if (trimmed) tokens.push(trimmed);
          buffer = '';
        }
      }
      if (tokens.length === 2) {
        const remainder = buffer.trim();
        if (remainder) tokens[1] += ` ${remainder}`;
        return tokens;
      }
      return null;
    };
    const parseDmsCoordinate = (token, isLat) => {
      if (!token) return null;
      let cleaned = normaliseDmsSymbols(token);
      if (!cleaned) return null;
      cleaned = cleaned.trim().toUpperCase();
      if (!cleaned) return null;
      let sign = 1;
      if (cleaned.startsWith('-')) {
        sign = -1;
        cleaned = cleaned.slice(1).trim();
      } else if (cleaned.startsWith('+')) {
        cleaned = cleaned.slice(1).trim();
      }
      let direction = null;
      if (cleaned && /[NSEW]$/.test(cleaned)) {
        direction = cleaned.slice(-1);
        cleaned = cleaned.slice(0, -1).trim();
      }
      let numeric = cleaned.replace(/°/g, ' ').replace(/[’′']/g, ' ').replace(/[“”″"]/g, ' ');
      numeric = numeric.replace(/\s+/g, ' ').trim();
      if (!numeric) return null;
      const parts = numeric.split(' ');
      if (parts.length > 3) return null;
      const deg = parseFloat(parts[0]);
      if (!Number.isFinite(deg)) return null;
      const minutes = parts.length >= 2 ? parseFloat(parts[1]) : 0;
      const seconds = parts.length >= 3 ? parseFloat(parts[2]) : 0;
      if ((parts.length >= 2 && !Number.isFinite(minutes)) || (parts.length >= 3 && !Number.isFinite(seconds))) return null;
      if (minutes >= 60 || seconds >= 60) return null;
      let value = Math.abs(deg) + minutes / 60 + seconds / 3600;
      if (direction) {
        if (direction === 'S' || direction === 'W') value = -value;
      } else if (sign < 0 || deg < 0) {
        value = -value;
      }
      const limit = isLat ? 90 : 180;
      if (value < -limit || value > limit) return null;
      return value;
    };
    const parseDecimalLocation = (value) => {
      const cleaned = value.replace(/\s+/g, '');
      const parts = cleaned.split(',');
      if (parts.length !== 2) return null;
      const lat = parseFloat(parts[0]);
      const lon = parseFloat(parts[1]);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
      if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
      return [lat, lon];
    };
    const parseLocation = (value) => {
      if (!value) return null;
      if (value.startsWith('///')) return null;
      const trimmed = value.trim();
      if (!trimmed) return null;
      const decimal = parseDecimalLocation(trimmed);
      if (decimal) return decimal;
      const normalised = normaliseDmsSymbols(trimmed);
      let tokens = normalised.split(',').map((part) => part.trim()).filter(Boolean);
      if (tokens.length !== 2) {
        tokens = splitDmsTokens(normalised) || [];
      }
      if (tokens.length !== 2) return null;
      const lat = parseDmsCoordinate(tokens[0], true);
      const lon = parseDmsCoordinate(tokens[1], false);
      if (lat === null || lon === null) return null;
      return [lat, lon];
    };

  const highwayAuthorities = ["Barking and Dagenham","Barnet","Barnsley","Bath & North East Somerset","Bedford","Bexley","Birmingham","Blackburn with Darwen","Blackpool","Bolton","Bournemouth, Christchurch and Poole","Bracknell Forest","Bradford","Brent","Brighton and Hove","Bristol","Bromley","Buckinghamshire","Bury","Calderdale","Cambridgeshire","Camden","Central Bedfordshire","Cheshire East","Cheshire West and Chester","City of London","City of York","Cornwall","Coventry","Croydon","Cumberland","Darlington","Derby","Derbyshire","Devon","Doncaster","Dorset","Dudley","Durham","Ealing","East Riding of Yorkshire","East Sussex","Enfield","Essex","Gateshead","Gloucestershire","Greenwich","Hackney","Halton","Hammersmith and Fulham","Hampshire","Haringey","Harrow","Hartlepool","Havering","Herefordshire","Hertfordshire","Hillingdon","Hounslow","Isle of Wight","Isles of Scilly","Islington","Kensington and Chelsea","Kent","Kingston upon Hull","Kingston upon Thames","Kirklees","Knowsley","Lambeth","Lancashire","Leeds","Leicester","Leicestershire","Lewisham","Lincolnshire","Liverpool","Luton","Manchester","Medway","Merton","Middlesbrough","Milton Keynes","Newcastle upon Tyne","Norfolk","North East Lincolnshire","North Lincolnshire","North Northamptonshire","North Somerset","North Tyneside","North Yorkshire","Northumberland","Nottingham","Nottinghamshire","Oldham","Oxfordshire","Peterborough","Plymouth","Portsmouth","Reading","Redbridge","Redcar & Cleveland","Richmond upon Thames","Rochdale","Rotherham","Rutland","Salford","Sandwell","Sefton","Sheffield","Shropshire","Slough","Solihull","Somerset","South Gloucestershire","South Tyneside","Southampton","Southend-on-Sea","Southwark","St Helens","Staffordshire","Stockport","Stockton-on-Tees","Stoke-on-Trent","Suffolk","Sunderland","Surrey","Sutton","Swindon","Tameside","Telford and Wrekin","Thurrock","Torbay","Tower Hamlets","Trafford","Wakefield","Walsall","Waltham Forest","Wandsworth","Warrington","Warwickshire","West Berkshire","West Northamptonshire","West Sussex","Westminster","Westmorland and Furness","Wigan","Wiltshire","Windsor and Maidenhead","Wirral","Wokingham","Wolverhampton","Worcestershire","York (City of York)","Transport for London"];
  for (const name of highwayAuthorities) {
    const option = document.createElement('option');
    option.value = name;
    document.getElementById('highwayOptionsList').append(option);
  }

  const showError = (message = '') => {
    text('errorTxt', message);
    $('errorTxt').hidden = !message;
  };
  const setStatus = (message, state = 'ready') => {
    text('searchStatusText', message);
    $('searchStatus').dataset.state = state;
  };
  const setSaveStatus = (message = '', error = false) => {
    text('savePermitStatus', message);
    $('savePermitStatus').style.color = error ? 'var(--high)' : '';
  };
  const setDownload = (url) => {
    if (url) { $('downloadBtn').href = url; $('downloadBtn').removeAttribute('tabindex'); }
    else { $('downloadBtn').removeAttribute('href'); $('downloadBtn').tabIndex = -1; }
    $('downloadBtn').setAttribute('aria-disabled', String(!url));
  };
  const reportReady = () => !!latestSearchResult && latestSearchResult.report?.status !== 'pending' && latestSearchResult.report?.status !== 'error'
    && !!(latestSearchResult.artifacts?.pdf_url || latestSearchResult.artifacts?.pdf_download_url);
  const updateSaveButton = () => {
    const ready = reportReady();
    $('savePermitBtn').disabled = !ready || !permitEl.value.trim() || saveBusy;
    if (!latestSearchResult) setSaveStatus();
    else if (!ready) setSaveStatus('Saving will be available when the report is ready.');
    else if (!saveBusy) setSaveStatus(permitEl.value.trim() ? 'Ready to save this assessment to the permit.' : 'Add a permit reference to save this assessment.');
  };
  const clearResults = (message) => {
    searchRevision += 1;
    latestSearchResult = null;
    reportBusy = false;
    saveBusy = false;
    streetCoords = null;
    $('resultCard').hidden = true;
    $('outcomeBadge').hidden = true;
    text('outcomeBadge', '');
    $('assessmentEmpty').hidden = false;
    $('assessmentEmpty').querySelector('h2').textContent = message || 'Your assessment will appear here';
    $('mapLegend').hidden = true;
    $('featureList').replaceChildren();
    $('detailsBody').replaceChildren();
    setDownload(null);
    $('openMapBtn').disabled = true;
    $('openMapBtn').onclick = null;
    $('savePermitBtn').disabled = true;
    $('retryReportBtn').hidden = true;
    setSaveStatus();
    if (resultLayers) resultLayers.clearLayers();
    if (radiusLayers) radiusLayers.clearLayers();
    featureLayers = new Map();
    $('streetViewFrame').hidden = true;
    $('streetViewFrame').removeAttribute('src');
    $('streetViewEmpty').hidden = false;
    $('openStreetViewBtn').disabled = true;
    text('streetViewHint', 'Run a search to explore the assessed location.');
  };
  const changedSearch = () => {
    if (searchBusy) return;
    if (latestSearchResult) clearResults('Search settings changed');
    showError();
    setStatus('Ready to search');
  };
  const setBusy = (busy) => {
    searchBusy = busy;
    form.setAttribute('aria-busy', String(busy));
    for (const control of form.querySelectorAll('input, button')) control.disabled = busy;
    for (const button of modeButtons) button.disabled = busy;
    const drawToolbar = document.querySelector('.leaflet-draw');
    if (drawToolbar) drawToolbar.inert = busy;
    $('runBtn').classList.toggle('busy', busy);
    text('runBtnLabel', busy ? 'Searching mapped features…' : 'Run proximity check');
  };

  const setExpanded = (value) => {
    expanded = value;
    $('mapPanel').classList.toggle('expanded', expanded);
    document.body.classList.toggle('map-expanded', expanded);
    $('toggleMapSize').setAttribute('aria-label', expanded ? 'Close enlarged map' : 'Enlarge map');
    $('toggleMapSize').title = expanded ? 'Close enlarged map' : 'Enlarge map';
    if (expanded) selectTab('map');
    requestAnimationFrame(() => map?.invalidateSize());
  };
  const updateStreetView = () => {
    if (!streetCoords) return;
    $('streetViewEmpty').hidden = true;
    $('streetViewFrame').hidden = false;
    const { lat, lon } = streetCoords;
    const url = `https://www.google.com/maps?q=&layer=c&cbll=${lat},${lon}&cbp=11,0,0,0,0&z=18&output=svembed`;
    if ($('streetViewFrame').getAttribute('src') !== url) $('streetViewFrame').src = url;
  };
  function selectTab(name, focus = false) {
    if (expanded && name !== 'map') setExpanded(false);
    activeTab = name;
    for (const tab of document.querySelectorAll('.view-tab')) {
      const selected = tab.id === `tab-${name}`;
      tab.classList.toggle('active', selected);
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      $(tab.getAttribute('aria-controls')).hidden = !selected;
    }
    if (focus) $(`tab-${name}`).focus();
    if (name === 'map') requestAnimationFrame(() => map?.invalidateSize());
    if (name === 'history') void fetchHistory();
    if (name === 'streetview') updateStreetView();
  }
  const updateOrigin = (coords, recenter = true) => {
    if (!map || !coords?.every(Number.isFinite)) return;
    if (!originMarker) originMarker = L.marker(coords, {
      icon: L.divIcon({ className: 'origin-icon', iconSize: [19, 19], iconAnchor: [9.5, 9.5] }),
      keyboard: false, interactive: false,
    });
    originMarker.setLatLng(coords);
    if (selectionMode === 'point' && !map.hasLayer(originMarker)) originMarker.addTo(map);
    if (recenter) map.setView(coords, Math.max(map.getZoom(), 15));
    text('mapLocationLabel', `${coords[0].toFixed(6)}, ${coords[1].toFixed(6)}`);
  };
  const polygonCenter = (coords) => {
    let twiceArea = 0, cx = 0, cy = 0;
    coords.forEach(([lat, lon], i) => {
      const [nextLat, nextLon] = coords[(i + 1) % coords.length];
      const cross = lon * nextLat - nextLon * lat;
      twiceArea += cross; cx += (lon + nextLon) * cross; cy += (lat + nextLat) * cross;
    });
    if (Math.abs(twiceArea) < 1e-12) return coords.reduce((sum, p) => [sum[0] + p[0] / coords.length, sum[1] + p[1] / coords.length], [0, 0]);
    return [cy / (3 * twiceArea), cx / (3 * twiceArea)];
  };
  const acceptPolygon = (layer) => {
    const rings = layer.getLatLngs();
    polygonCoords = (Array.isArray(rings[0]) ? rings[0] : rings).map((p) => [Number(p.lat), Number(p.lng)]);
    const center = polygonCenter(polygonCoords);
    locationEl.value = `${center[0].toFixed(6)},${center[1].toFixed(6)}`;
    text('mapLocationLabel', `Polygon · ${polygonCoords.length} vertices`);
  };
  const setMode = (mode) => {
    if (searchBusy || selectionMode === mode) return;
    changedSearch();
    selectionMode = mode === 'polygon' ? 'polygon' : 'point';
    modeButtons.forEach((button) => {
      button.classList.toggle('active', button.dataset.mode === selectionMode);
      button.setAttribute('aria-pressed', String(button.dataset.mode === selectionMode));
    });
    text('mapInstruction', selectionMode === 'polygon' ? 'Use the polygon tool to draw the works boundary' : 'Click the map to set your search location');
    if (!map) return;
    if (selectionMode === 'polygon') {
      if (originMarker) map.removeLayer(originMarker);
      if (drawControl) map.addControl(drawControl);
    } else {
      if (drawControl) map.removeControl(drawControl);
      drawnItems.clearLayers(); polygonCoords = null;
      const coords = parseLocation(locationEl.value);
      if (coords) updateOrigin(coords, false);
    }
  };
  const popupFor = (row) => {
    const box = node('div', undefined, 'feature-popup');
    box.append(node('strong', featureName(row)), node('p', row.category || 'Mapped feature'), node('p', `${distance(row.distance_m)} from the works · ${proximity(row)} proximity`));
    return box;
  };
  const selectFeature = (index, moveMap = true) => {
    selectTab('map');
    for (const button of document.querySelectorAll('.feature-button')) button.setAttribute('aria-pressed', String(button.dataset.featureIndex === String(index)));
    const layer = featureLayers.get(String(index));
    if (!layer) return;
    if (moveMap) {
      if (layer.getBounds) map.fitBounds(layer.getBounds(), { padding: [65, 65], maxZoom: 18 });
      else if (layer.getLatLng) map.setView(layer.getLatLng(), Math.max(map.getZoom(), 17));
      $('pickerMap').scrollIntoView({ block: 'center', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
    }
    layer.openPopup();
  };
  const renderMap = (result, rows) => {
    if (!map) return;
    resultLayers.clearLayers(); radiusLayers.clearLayers(); featureLayers = new Map();
    const center = result.summary?.center_coords || result.center;
    if (center && Number.isFinite(center.lat) && Number.isFinite(center.lon)) {
      updateOrigin([center.lat, center.lon], false);
      if (selectionMode === 'point') {
        const radius = Number(result.radius_m || result.summary.radius || radiusEl.value);
        for (const metres of [radius, 25, 10].filter((v, i, arr) => v <= radius && arr.indexOf(v) === i)) {
          const ring = L.circle([center.lat, center.lon], { radius: metres, color: metres === radius ? '#246c78' : '#537f86', weight: 1.5, fillOpacity: metres === radius ? .045 : .025, dashArray: metres === radius ? undefined : '4 5', interactive: false }).addTo(radiusLayers);
          if (metres === radius) map.fitBounds(ring.getBounds(), { padding: [35, 35], maxZoom: 18 });
        }
      } else if (drawnItems.getLayers().length) map.fitBounds(drawnItems.getBounds(), { padding: [35, 35], maxZoom: 18 });
    }
    const geoFeatures = result.map_features?.features || [];
    rows.forEach((row) => {
      const geometry = geoFeatures.find((f) => String(f.properties?.feature_index) === String(row.feature_index));
      const band = proximity(row);
      const color = band === 'HIGH' ? '#b23b3b' : band === 'MEDIUM' ? '#9a680c' : '#156e69';
      let layer;
      if (geometry?.geometry) {
        layer = L.geoJSON(geometry, {
          style: { color, fillColor: color, weight: 3, fillOpacity: .22 },
          pointToLayer: (_, latlng) => L.circleMarker(latlng, { radius: 7, color: '#fff', weight: 2, fillColor: color, fillOpacity: 1 }),
        });
      } else if (Number.isFinite(Number(row.lat)) && Number.isFinite(Number(row.lon))) {
        layer = L.circleMarker([Number(row.lat), Number(row.lon)], { radius: 7, color: '#fff', weight: 2, fillColor: color, fillOpacity: 1 });
      }
      if (!layer) return;
      layer.bindPopup(popupFor(row));
      layer.on('click', (event) => { if (event.originalEvent) L.DomEvent.stopPropagation(event.originalEvent); selectFeature(row.feature_index, false); });
      layer.addTo(resultLayers);
      featureLayers.set(String(row.feature_index), layer);
    });
    $('mapLegend').hidden = false;
  };

  const renderAssessment = (result) => {
    const outcome = String(result.summary?.outcome || '').toUpperCase();
    if (!['HIGH', 'MEDIUM', 'LOW'].includes(outcome)) throw new Error('The search returned no valid proximity assessment. Please try again.');
    latestSearchResult = result;
    const rows = features(result);
    const nearest = rows[0];
    const contributor = rows.find((row) => proximity(row) === outcome);
    $('outcomeBadge').className = `outcome-badge ${outcome.toLowerCase()}`;
    text('outcomeBadge', outcome); $('outcomeBadge').hidden = false;
    let reason;
    if (outcome === 'LOW') reason = rows.length ? 'No mapped features fall within the higher proximity bands for their categories.' : 'No matching mapped features were found within the assessment bands for this search.';
    else if (contributor) {
      const band = outcome === 'HIGH' ? (isPetrol(contributor) ? 'below 25 m' : 'below 10 m') : (isPetrol(contributor) ? '25–50 m' : '10–25 m');
      reason = `${contributor.category || 'Mapped feature'}: ${distance(contributor.distance_m)} from the works, in the ${outcome.toLowerCase()} proximity band (${band}).`;
    } else reason = 'The mapped features meet the proximity criteria shown in the category breakdown.';
    text('resultReason', reason);
    text('nearestFeature', nearest ? featureName(nearest) : 'No matching features found');
    text('nearestDistance', nearest ? `${distance(nearest.distance_m)} from the works` : 'Assessment bands extend up to 100 m');
    text('centerLabel', result.summary?.center || result.center?.display || '');
    text('radiusLabel', `${result.summary?.radius || result.radius_m || radiusEl.value} m radius`);
    text('permitLabel', result.summary?.permit ? `Permit ${result.summary.permit}` : '');
    text('featureCount', `${rows.length} ${rows.length === 1 ? 'feature' : 'features'} · within 100 m`);
    $('featureList').replaceChildren();
    rows.forEach((row, index) => {
      const item = node('li'); const button = node('button', undefined, 'feature-button');
      button.type = 'button'; button.dataset.featureIndex = row.feature_index; button.setAttribute('aria-pressed', 'false');
      const label = node('span', undefined, 'feature-name'); label.append(node('span', featureName(row)), node('small', row.category || 'Mapped feature'));
      button.append(node('span', String(index + 1).padStart(2, '0'), 'feature-number'), label, node('span', distance(row.distance_m), `feature-distance ${proximity(row).toLowerCase()}`));
      button.addEventListener('click', () => selectFeature(row.feature_index)); item.append(button); $('featureList').append(item);
    });
    if (!rows.length) $('featureList').append(node('li', 'No matching mapped features were found. The completed category breakdown is available below.', 'feature-empty'));
    $('detailsBody').replaceChildren();
    const selected = new Set([...form.querySelectorAll('[name="cat"]:checked')].map((input) => categoryLabels[input.value]));
    for (const category of result.summary?.categories || []) {
      if (!selected.has(category.label)) continue;
      const tr = node('tr'); tr.append(node('td', category.label));
      for (const value of [category.no, category.lt10, category.r10_25, category.r25_100]) { const td = node('td', value ? '✓' : '—'); td.setAttribute('aria-label', value ? 'Yes' : 'No'); tr.append(td); }
      $('detailsBody').append(tr);
    }
    const center = result.summary?.center_coords || result.center;
    streetCoords = center && Number.isFinite(center.lat) && Number.isFinite(center.lon) ? { lat: center.lat, lon: center.lon } : null;
    $('openStreetViewBtn').disabled = !streetCoords;
    text('streetViewHint', streetCoords ? 'Explore the surroundings of the assessed location.' : 'Street View is unavailable for this location.');
    if (activeTab === 'streetview') updateStreetView();
    $('assessmentEmpty').hidden = true; $('resultCard').hidden = false;
    renderMap(result, rows);
    $('resultCard').focus({ preventScroll: true });
    $('resultCard').scrollIntoView({ block: 'nearest', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
    void fetchHistory();
  };
  const applyArtifacts = (result) => {
    latestSearchResult = result;
    const artifacts = result.artifacts || {};
    const pdf = artifacts.pdf_url || artifacts.pdf_download_url;
    const mapUrl = artifacts.map_url || artifacts.map_embed_url;
    setDownload(pdf);
    $('openMapBtn').disabled = !mapUrl;
    $('openMapBtn').onclick = mapUrl ? () => window.open(mapUrl, '_blank', 'noopener') : null;
    $('reportIndicator').className = 'report-indicator';
    $('retryReportBtn').hidden = true;
    text('reportStatus', pdf ? 'Report ready to download' : 'No report files are available.');
    setStatus('Assessment complete'); updateSaveButton();
  };
  const reportError = (message) => {
    if (latestSearchResult?.report) latestSearchResult.report.status = 'error';
    $('reportIndicator').className = 'report-indicator error';
    text('reportStatus', message || 'The assessment is ready, but its report could not be prepared.');
    $('retryReportBtn').hidden = !latestSearchResult?.report?.url;
    $('retryReportBtn').disabled = false;
    setStatus('Assessment ready · report unavailable'); updateSaveButton();
  };
  async function generateReport(revision, attempts = 0) {
    if (revision !== searchRevision || !latestSearchResult?.report?.url || reportBusy) return;
    reportBusy = true;
    $('retryReportBtn').hidden = true;
    $('reportIndicator').className = 'report-indicator busy';
    text('reportStatus', 'Assessment ready. Preparing your PDF and report map…');
    setStatus('Assessment ready · preparing report', 'busy');
    try {
      const response = await fetch(latestSearchResult.report.url, { method: 'POST', credentials: 'include', headers: { Accept: 'application/json' } });
      const json = await response.json().catch(() => ({}));
      if (revision !== searchRevision) return;
      if (response.status === 401) { window.location.href = '/'; return; }
      if (response.ok && json.status === 'processing' && attempts < 30) {
        reportBusy = false;
        setTimeout(() => { void generateReport(revision, attempts + 1); }, Math.max(1, Math.min(Number(json.result?.report?.retry_after_seconds) || 2, 10)) * 1000);
        return;
      }
      if (!response.ok || json.status !== 'done' || !json.result || json.result.report?.status === 'error') throw new Error('The assessment is ready, but its report could not be prepared. Retry the report without running another search.');
      applyArtifacts(json.result);
      void fetchHistory();
    } catch (error) {
      if (revision === searchRevision) reportError(error.message || 'Unable to prepare the report. Please retry.');
    } finally { if (revision === searchRevision) reportBusy = false; }
  }

  async function runSearch(event) {
    event?.preventDefault();
    if (searchBusy) return;
    showError(); locationEl.removeAttribute('aria-invalid'); radiusEl.removeAttribute('aria-invalid');
    const radius = Number(radiusEl.value);
    if (!locationEl.value.trim() && selectionMode === 'point') { showError('Enter coordinates or what3words, or select a point on the map.'); locationEl.setAttribute('aria-invalid', 'true'); locationEl.focus(); return; }
    if (!Number.isInteger(radius) || radius < 10 || radius > 20000) { showError('Enter a radius between 10 and 20,000 metres.'); radiusEl.setAttribute('aria-invalid', 'true'); radiusEl.focus(); return; }
    if (selectionMode === 'polygon' && (!polygonCoords || polygonCoords.length < 3)) { showError('Draw a polygon on the map before running the search.'); selectTab('map'); return; }
    const categories = [...form.querySelectorAll('[name="cat"]:checked')].map((input) => input.value);
    if (!categories.length) { showError('Select at least one category to check.'); return; }
    clearResults('Searching mapped features…');
    const revision = searchRevision;
    setBusy(true); setStatus('Searching mapped features…', 'busy');
    try {
      const response = await fetch('/api/search', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ location: locationEl.value.trim(), radius_m: radius, categories, permit: permitEl.value.trim() || null, address: $('address').value.trim() || null, highway_authority: $('highwayAuthority').value.trim() || null, max_results: null, selection_mode: selectionMode, polygon: selectionMode === 'polygon' ? polygonCoords : null, defer_reports: true }),
      });
      const json = await response.json().catch(() => ({}));
      if (revision !== searchRevision) return;
      if (response.status === 401) { window.location.href = '/'; return; }
      if (!response.ok || json.status !== 'done' || !json.result) throw new Error(typeof json.error === 'string' ? json.error : `The search could not be completed${response.ok ? '' : ` (${response.status})`}. Please try again.`);
      renderAssessment(json.result);
      updateSaveButton();
      if (json.result.report?.status === 'pending' && json.result.report.url) void generateReport(revision);
      else applyArtifacts(json.result);
    } catch (error) {
      if (revision !== searchRevision) return;
      clearResults('No proximity assessment was completed');
      showError(error.message || 'Unable to complete the search. Please try again.');
      setStatus('Search could not be completed', 'error');
    } finally { setBusy(false); }
  }
  async function savePermit() {
    if (saveBusy || !reportReady() || !permitEl.value.trim()) return;
    const revision = searchRevision;
    saveBusy = true; $('savePermitBtn').disabled = true; setSaveStatus('Saving permit record…');
    try {
      const response = await fetch('/api/permits', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ permit_ref: permitEl.value.trim(), result: latestSearchResult }) });
      const json = await response.json().catch(() => ({}));
      if (revision !== searchRevision) return;
      if (response.status === 401) { window.location.href = '/'; return; }
      if (!response.ok) throw new Error(typeof json.detail === 'string' ? json.detail : 'Unable to save the permit record.');
      if (json.search_result) latestSearchResult = json.search_result;
      setSaveStatus('Permit record saved.');
    } catch (error) { if (revision === searchRevision) setSaveStatus(error.message || 'Unable to save the permit record.', true); }
    finally { if (revision === searchRevision) { saveBusy = false; $('savePermitBtn').disabled = !reportReady() || !permitEl.value.trim(); } }
  }
  async function fetchHistory() {
    try {
      const response = await fetch('/api/history', { credentials: 'include' });
      if (response.status === 401) { window.location.href = '/'; return; }
      if (!response.ok) throw new Error();
      const json = await response.json();
      $('historyBody').replaceChildren();
      for (const item of Array.isArray(json.history) ? json.history : []) {
        const tr = node('tr'); const date = new Date(item.timestamp);
        tr.append(node('td', Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString('en-GB', { timeZone: 'Europe/London', dateStyle: 'short', timeStyle: 'short' })));
        tr.append(node('td', item.permit ? `${item.permit} · ${item.location || ''}` : item.location || ''));
        const outcome = ['HIGH', 'MEDIUM', 'LOW'].includes(item.outcome) ? item.outcome : '';
        const td = node('td'); td.append(node('span', outcome || 'Not assessed', `history-outcome ${outcome.toLowerCase()}`)); tr.append(td); $('historyBody').append(tr);
      }
      if (!$('historyBody').children.length) { const tr = node('tr'); const td = node('td', 'No searches yet.', 'muted'); td.colSpan = 3; tr.append(td); $('historyBody').append(tr); }
    } catch (_) { const tr = node('tr'); const td = node('td', 'Recent searches could not be loaded. Use View full history to try again.', 'muted'); td.colSpan = 3; tr.append(td); $('historyBody').replaceChildren(tr); }
  }

  function initializeMap() {
    if (!window.L) { showError('The map could not be loaded. You can still search using coordinates or what3words.'); return; }
    map = L.map('pickerMap').setView([52.5, -1.5], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
    drawnItems = new L.FeatureGroup().addTo(map); resultLayers = new L.FeatureGroup().addTo(map); radiusLayers = new L.FeatureGroup().addTo(map);
    if (L.Control.Draw) drawControl = new L.Control.Draw({ draw: { marker: false, circle: false, circlemarker: false, polyline: false, rectangle: false, polygon: { allowIntersection: false, showArea: true, shapeOptions: { color: '#146b68', fillOpacity: .13 } } }, edit: { featureGroup: drawnItems } });
    map.on('click', (event) => {
      if (selectionMode !== 'point' || searchBusy || event.originalEvent?.target?.closest('.leaflet-interactive, .leaflet-popup')) return;
      changedSearch(); const { lat, lng } = event.latlng; locationEl.value = `${lat.toFixed(6)},${lng.toFixed(6)}`; updateOrigin([lat, lng], false);
    });
    map.on('draw:created', (event) => { if (searchBusy || selectionMode !== 'polygon') return; changedSearch(); drawnItems.clearLayers(); drawnItems.addLayer(event.layer); acceptPolygon(event.layer); });
    map.on('draw:edited', (event) => { if (searchBusy) return; changedSearch(); event.layers.eachLayer(acceptPolygon); });
    map.on('draw:deleted', () => { if (searchBusy) return; changedSearch(); polygonCoords = null; locationEl.value = ''; text('mapLocationLabel', 'Draw a polygon to define the search area'); });
  }
  initializeMap();
  form.addEventListener('submit', runSearch);
  for (const button of modeButtons) button.addEventListener('click', () => setMode(button.dataset.mode));
  for (const tab of document.querySelectorAll('.view-tab')) {
    tab.addEventListener('click', () => selectTab(tab.id.replace('tab-', '')));
    tab.addEventListener('keydown', (event) => {
      const tabs = [...document.querySelectorAll('.view-tab')]; const index = tabs.indexOf(tab);
      const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
      if (next !== null) { event.preventDefault(); selectTab(tabs[next].id.replace('tab-', ''), true); }
    });
  }
  locationEl.addEventListener('input', changedSearch);
  locationEl.addEventListener('change', () => { const coords = parseLocation(locationEl.value); if (coords && selectionMode === 'point') updateOrigin(coords); });
  for (const input of [radiusEl, $('address'), $('highwayAuthority'), ...form.querySelectorAll('[name="cat"]')]) input.addEventListener('input', changedSearch);
  permitEl.addEventListener('input', updateSaveButton);
  $('toggleMapSize').addEventListener('click', () => setExpanded(!expanded));
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && expanded) setExpanded(false); });
  $('openStreetViewBtn').addEventListener('click', () => { if (streetCoords) window.open(`https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${streetCoords.lat},${streetCoords.lon}`, '_blank', 'noopener'); });
  $('downloadBtn').addEventListener('click', (event) => { if ($('downloadBtn').getAttribute('aria-disabled') === 'true') event.preventDefault(); });
  $('savePermitBtn').addEventListener('click', savePermit);
  $('retryReportBtn').addEventListener('click', () => { void generateReport(searchRevision); });
  fetch('/auth-status', { credentials: 'include' }).then((response) => { if (response.status === 401) window.location.href = '/'; }).catch(() => {});
})();
