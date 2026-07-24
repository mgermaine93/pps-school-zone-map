// --------------------
// SERVICE WORKER
// --------------------
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js')
    .catch(err => console.warn('Service worker registration failed:', err));
}

// --------------------
// MAP INIT
// --------------------
const PITTSBURGH_BOUNDS = L.latLngBounds([[40.36, -80.10], [40.50, -79.87]]);
const map = L.map('map').fitBounds(PITTSBURGH_BOUNDS);
const DEFAULT_ZOOM   = map.getZoom();
const DEFAULT_CENTER = map.getCenter();

const basemaps = {
  osm: L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }),
  light: L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>'
  }),
  dark: L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>'
  }),
  satellite: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 17,
    attribution: 'Tiles &copy; <a href="https://www.esri.com/">Esri</a>'
  })
};

let currentBasemap = basemaps.osm;
currentBasemap.addTo(map);

document.getElementById('basemapSelect').addEventListener('change', e => {
  map.removeLayer(currentBasemap);
  currentBasemapKey = e.target.value;
  currentBasemap = basemaps[currentBasemapKey];
  currentBasemap.addTo(map);
  document.body.classList.toggle('dark-basemap', currentBasemapKey === 'dark');
  syncHash();
});

const renderer = L.canvas({ padding: 0.5 });
const schoolColorMap = {};

function markerRadius() {
  const z = map.getZoom();
  if (z >= 16) return 7;
  if (z >= 14) return 6;
  if (z >= 12) return 5;
  return 4;
}

function updateMarkerRadius() {
  const r = markerRadius();
  allMarkers.forEach(({ marker }) => marker.setStyle({ radius: r }));
}

map.on('zoomend', updateMarkerRadius);

function updateResetViewBtn() {
  const c = map.getCenter();
  const EPS = 0.0001;
  const atDefault = map.getZoom() === DEFAULT_ZOOM &&
    Math.abs(c.lat - DEFAULT_CENTER.lat) < EPS &&
    Math.abs(c.lng - DEFAULT_CENTER.lng) < EPS;
  document.getElementById('resetViewBtn').style.display = atDefault ? 'none' : '';
}

map.on('moveend', updateResetViewBtn);

// On mobile a tap triggers both tooltip and popup simultaneously; dismiss
// the tooltip as soon as its marker's popup opens.
map.on('popupopen', e => {
  const marker = e.popup._source;
  if (marker?.getTooltip()) marker.closeTooltip();
});

// Linearly interpolates between Color Brewer hex anchor colors to produce a
// palette of targetSize evenly-spaced entries. Used to expand the ELEM palette
// so all elementary schools get a unique shade without cycling.
function expandPalette(anchors, targetSize) {
  const parse = h => [parseInt(h.slice(1,3),16), parseInt(h.slice(3,5),16), parseInt(h.slice(5,7),16)];
  const fmt   = ([r,g,b]) => '#' + [r,g,b].map(v => Math.round(v).toString(16).padStart(2,'0')).join('');
  const rgb = anchors.map(parse);
  return Array.from({ length: targetSize }, (_, i) => {
    const t  = i / (targetSize - 1) * (rgb.length - 1);
    const lo = Math.floor(t), hi = Math.min(lo + 1, rgb.length - 1), f = t - lo;
    return fmt(rgb[lo].map((c, j) => c + f * (rgb[hi][j] - c)));
  });
}

// Color Brewer sequential palettes, all marked colorblind-safe on colorbrewer2.org.
// Each type gets its own hue family so type groups stay visually distinct across
// "Color by" modes. Greens and oranges are intentionally avoided — they are the
// most common problem pair under deuteranopia/protanopia.
//   ELEM   → Blues   (expanded to 40 via interpolation — avoids cycling across ~30 schools)
//   K8     → Purples (8 anchors, ~5 schools — no expansion needed)
//   MIDD   → Reds    (shown in isolation from ELEM/K8)
//   HIGH   → RdPu    (pink-magenta, shown in isolation)
//   ONLINE → Greys   (neutral; typically only 1–2 schools)
const CB_PALETTES = {
  ELEM:   expandPalette(['#08306b','#08519c','#2171b5','#4292c6','#6baed6','#9ecae1','#c6dbef','#deebf7'], 40),
  K8:     ['#3f007d','#54278f','#6a51a3','#807dba','#9e9ac8','#bcbddc','#dadaeb','#efedf5'],
  MIDD:   ['#67000d','#a50f15','#cb181d','#ef3b2c','#fb6a4a','#fc9272','#fcbba1'],
  HIGH:   ['#49006a','#7a0177','#ae017e','#dd3497','#f768a1','#fa9fb5','#fcc5c0'],
  ONLINE: ['#252525','#525252','#737373','#969696','#bdbdbd','#d9d9d9'],
};

const DATA_CONFIGS = {
  current: { bin: 'data/addresses.bin',      schools: 'data/schools.json' },
  '2027':  { bin: 'data/addresses-2027.bin', schools: 'data/schools-2027.json' },
};

/**
 * Retrieves or assigns a Color Brewer color for a school.
 *
 * Colors are assigned once per school name and cached in schoolColorMap.
 * Each school type draws from its own Color Brewer sequential palette,
 * cycling through it if the number of schools in that type exceeds the
 * palette length.
 *
 * @param {string} schoolName - The school's display name, used as the cache key.
 * @param {string} type - School type code: 'ELEM', 'K8', 'MIDD', 'HIGH', or 'ONLINE'.
 * @returns {{ color: string, _type: string }} Cached entry with the hex color
 *   string and the type it was registered under.
 */
function getSchoolColor(schoolName, type) {
  if (schoolColorMap[schoolName]) return schoolColorMap[schoolName];

  const palette = CB_PALETTES[type] || CB_PALETTES.ELEM;
  const typeCount = Object.entries(schoolColorMap)
    .filter(([, v]) => v._type === type).length;
  const color = palette[typeCount % palette.length];

  schoolColorMap[schoolName] = { color, _type: type };
  return schoolColorMap[schoolName];
}

// --------------------
// SCHOOL ICONS
// --------------------
const SCHOOL_ICONS = {
  ELEM:   'img/favicon-elementary.svg',
  K8:     'img/favicon-k8.svg',
  MIDD:   'img/favicon-middle.svg',
  HIGH:   'img/favicon-highschool.svg',
  ONLINE: 'img/favicon-online.svg',
};

/**
 * Creates a Leaflet icon for a school map marker based on school type.
 *
 * Maps each type code to its corresponding SVG in the img/ directory.
 * The icon is 48×48px with the anchor at the bottom-center so the pin
 * tip aligns with the school's coordinates rather than its center.
 *
 * @param {string} type - School type code: 'ELEM', 'K8', 'MIDD', 'HIGH', or 'ONLINE'.
 *   Falls back to the ELEM icon for any unrecognized type.
 * @returns {L.Icon} A configured Leaflet icon instance ready to attach to a marker.
 */
function schoolIcon(type) {
  return L.icon({
    iconUrl:     SCHOOL_ICONS[type] || SCHOOL_ICONS.ELEM,
    iconSize:    [48, 48],
    iconAnchor:  [24, 48],
    popupAnchor: [0, -48],
  });
}

// --------------------
// SCHOOL POPUP HTML
// --------------------
const TYPE_LABELS = { ELEM: 'Elementary', K8: 'PreK–8', MIDD: 'Middle School', HIGH: 'High School', ONLINE: 'Online' };

function splitAddress(address) {
  const i = address.indexOf(',');
  return i !== -1
    ? { street: address.slice(0, i), city: address.slice(i + 2) }
    : { street: address, city: '' };
}

function schoolPopupHTML(school) {
  const typeLabel = TYPE_LABELS[school.type] || school.type;
  const { street: streetLine, city: cityLine } = splitAddress(school.address);

  let details = '';
  if (school.main_phone) {
    const digits = school.main_phone.replace(/\D/g, '');
    details += `<a href="tel:${digits}" style="color:#3a7bd5;text-decoration:none">${school.main_phone}</a>`;
  }
  if (school.start_time && school.end_time) {
    if (details) details += '<br>';
    details += `Hours: ${school.start_time} &ndash; ${school.end_time}`;
  }

  return `
    <b>${school.name}</b><br>
    <span class="popup-school-type">${typeLabel}</span><br>
    <span class="popup-addr">${streetLine}${cityLine ? `<br>${cityLine}` : ''}</span>
    ${details ? `<div class="popup-details">${details}</div>` : ''}
  `.trim();
}

// --------------------
// PRIMARY SCHOOL LOGIC
// --------------------
const TYPE_PRIORITY = ['ELEM', 'K8', 'MIDD', 'HIGH', 'ONLINE'];

/**
 * Selects the primary school for an address used to determine its dot color.
 *
 * Iterates TYPE_PRIORITY order ('ELEM' → 'K8' → 'MIDD' → 'HIGH' → 'ONLINE')
 * and returns the first school that matches the current type AND carries an
 * 'attendance' zone. Falls back to the first school in the list if none qualify.
 *
 * @param {Array<{name: string, type: string, zones: string[]}>} schools - The
 *   schools assigned to a single address, as stored in addresses_slim.json.
 * @returns {{ name: string, type: string, zones: string[] }} The school chosen
 *   to represent this address for color assignment purposes.
 */
function getPrimarySchool(schools) {
  for (const type of TYPE_PRIORITY) {
    const match = schools.find(s =>
      s.type === type && s.zones.includes('attendance')
    );
    if (match) return match;
  }
  return schools[0] ?? null;
}

// --------------------
// STATE
// --------------------
let allMarkers = [];
let allAddresses = [];   // raw data kept for search
let currentTypeFilter = '';
let currentSchoolFilter = '';
let searchMarker = null;
let schoolMarkers = [];
let allSchoolMarkers = [];
let filterSchoolMarker = null;
let schoolsByName = {};
let currentColorBy = "ELEM";
let currentBasemapKey = 'osm';
let currentPins = '';
let currentYear = 'current';
let searchZoneSchoolNames = null;

// --------------------
// LOAD DATA
// --------------------

/**
 * Loads the address and school datasets for the given year, tears down any
 * previously rendered markers, and re-renders the map from scratch.
 *
 * All existing address markers, school pins, and caches are cleared before
 * fetching. State variables (currentColorBy, currentSchoolFilter, etc.) are
 * read as-is so the caller can set them before invoking loadData — on first
 * page load they are restored from the URL hash; on year-change they are reset
 * by the yearSelect handler.
 *
 * @param {string} year - Key into DATA_CONFIGS ('current' or '2027').
 */
function loadData(year) {
  const config = DATA_CONFIGS[year] || DATA_CONFIGS.current;

  // Remove all existing address markers
  allMarkers.forEach(({ marker }) => map.removeLayer(marker));
  allMarkers = [];
  allAddresses = [];

  // Clear caches so recolor() starts fresh
  Object.keys(schoolColorMap).forEach(k => delete schoolColorMap[k]);
  Object.keys(schoolsByName).forEach(k => delete schoolsByName[k]);
  searchZoneSchoolNames = null;

  // Clear all school-related map markers
  clearSearchMarker();
  clearSchoolMarkers();
  clearFilterSchoolMarker();
  allSchoolMarkers.forEach(m => map.removeLayer(m));
  allSchoolMarkers = [];

  // Reset school dropdown to just the "All schools" placeholder
  const schoolSel = document.getElementById('schoolFilter');
  while (schoolSel.options.length > 1) schoolSel.remove(1);

  // Reset legend and status
  document.getElementById('legend').innerHTML = '';
  document.getElementById('status').textContent = '';

  // Show loader
  const loaderEl    = document.getElementById('loader');
  const loaderText  = document.getElementById('loaderText');
  const progressBar = document.getElementById('loadProgressBar');
  loaderEl.style.display = 'flex';
  loaderText.textContent = 'Loading…';
  progressBar.style.width = '0%';

  // Fetch school metadata (non-critical — address search still works without it)
  fetch(config.schools)
    .then(res => res.json())
    .then(schools => {
      schools.forEach(s => { if (s.lat != null) schoolsByName[s.name] = s; });
    })
    .catch(() => {});

  // Fetch and render the address binary
  fetch(config.bin)
    .then(res => res.arrayBuffer())
    .then(buf => {
      const view = new DataView(buf);
      const dec  = new TextDecoder();
      let pos = 0;

      // Header
      pos += 4; // skip magic 'PPSb'
      const schoolNameCount = view.getUint16(pos, true); pos += 2;
      const typeCount       = view.getUint8(pos);        pos += 1;
      const zoneCount       = view.getUint8(pos);        pos += 1;
      const addressCount    = view.getUint32(pos, true); pos += 4;

      function readLStr() {
        const len = view.getUint8(pos); pos += 1;
        const str = dec.decode(new Uint8Array(buf, pos, len));
        pos += len;
        return str;
      }

      const schoolNames = Array.from({ length: schoolNameCount }, readLStr);
      const types       = Array.from({ length: typeCount },       readLStr);
      const zones       = Array.from({ length: zoneCount },       readLStr);

      const addresses = [];
      for (let i = 0; i < addressCount; i++) {
        const lat         = view.getInt32(pos, true) / 100000; pos += 4;
        const lng         = view.getInt32(pos, true) / 100000; pos += 4;
        const schoolCount = view.getUint8(pos);                pos += 1;

        const schools = [];
        for (let j = 0; j < schoolCount; j++) {
          const nameIdx = view.getUint8(pos); pos += 1;
          const typeIdx = view.getUint8(pos); pos += 1;
          const zoneIdx = view.getUint8(pos); pos += 1;
          schools.push({
            name:  schoolNames[nameIdx],
            type:  types[typeIdx],
            zones: zones[zoneIdx].split(','),
          });
        }

        const idLen   = view.getUint16(pos, true); pos += 2;
        const id      = dec.decode(new Uint8Array(buf, pos, idLen)); pos += idLen;

        const addrLen = view.getUint16(pos, true); pos += 2;
        const address = dec.decode(new Uint8Array(buf, pos, addrLen)); pos += addrLen;

        addresses.push({ id, address, lat, lng, schools });
      }
      allAddresses = addresses;

      // Collect unique school name→type pairs in one pass (no worker needed —
      // the structured-clone round trip cost exceeded any off-thread benefit)
      const allSchoolsMap = new Map();
      addresses.forEach(point => {
        point.schools.forEach(s => {
          if (!allSchoolsMap.has(s.name)) allSchoolsMap.set(s.name, s.type);
        });
      });

      allSchoolsMap.forEach((type, name) => getSchoolColor(name, type));
      buildSchoolDropdown([...allSchoolsMap.keys()].sort());
      syncTypeOptions(new Set(allSchoolsMap.values()));

      // Sync school dropdown if a filter was already set before data arrived
      if (currentSchoolFilter) {
        document.getElementById('schoolFilter').value = currentSchoolFilter;
      }

      // Add markers in chunks to keep the UI responsive during load
      const CHUNK_SIZE = 5000;
      let i = 0;

      /**
       * Renders one batch of address markers onto the map, then yields to the
       * browser via requestAnimationFrame before processing the next batch.
       *
       * Splitting rendering into chunks prevents the UI from locking up during
       * the initial load of ~116,000 markers. Popup HTML is generated lazily
       * (bound as a factory function) so it is only built when a user clicks a
       * point, not for all markers at load time.
       */
      function processChunk() {
        const end = Math.min(i + CHUNK_SIZE, addresses.length);
        for (; i < end; i++) {
          const point = addresses[i];

          const marker = L.circleMarker([point.lat, point.lng], {
            renderer,
            radius: markerRadius(),
            color: '#aaa',
            weight: 1,
            fillColor: '#aaa',
            fillOpacity: 0.5
          });

          const { street, city } = splitAddress(point.address);
          const tooltipHTML = city ? `${street}<br>${city}` : street;
          marker.bindTooltip(tooltipHTML, { sticky: true, className: 'addr-tooltip' });

          // Generate popup HTML only on click, not for all 116k markers at load time
          marker.bindPopup(() => {
            const schoolList = [...point.schools]
              .sort((a, b) => TYPE_PRIORITY.indexOf(a.type) - TYPE_PRIORITY.indexOf(b.type))
              .map(s => `<li><b>${s.name}</b> <span class="popup-school-type">(${TYPE_LABELS[s.type] || s.type})</span></li>`)
              .join('');
            return `
              <b>${street}</b>${city ? `<br><span class="popup-addr">${city}</span>` : ''}
              <ul style="margin:6px 0 0;padding-left:16px;font-size:12px">${schoolList}</ul>
            `;
          });

          marker.addTo(map);
          allMarkers.push({ marker, point });
        }

        if (i < addresses.length) {
          const pct = (i / addresses.length * 100).toFixed(1);
          loaderText.textContent = `Loading ${i.toLocaleString()} / ${addresses.length.toLocaleString()} addresses…`;
          progressBar.style.width = `${pct}%`;
          requestAnimationFrame(processChunk);
        } else {
          progressBar.style.width = '100%';
          if (currentPins) updateSchoolPins(currentPins);
          recolor();
          updateStatus();
          loaderEl.style.display = 'none';
        }
      }

      requestAnimationFrame(processChunk);
    })
    .catch(err => {
      console.error('Error loading data:', err);
      loaderEl.style.display = 'none';
    });
}

// Read all state from the URL hash, then kick off the initial load.
// Year is read first because it determines which dataset to fetch;
// other params are applied before loadData so they take effect at first render.
{
  const params = new URLSearchParams(window.location.hash.slice(1));
  const hashYear    = params.get('year');
  const hashColorBy = params.get('colorBy');
  const hashType    = params.get('type');
  const hashSchool  = params.get('school');
  const hashBasemap = params.get('basemap');
  const hashPins    = params.get('pins');

  if (hashYear && DATA_CONFIGS[hashYear]) {
    currentYear = hashYear;
    document.querySelectorAll('.year-tab').forEach(t => {
      t.classList.toggle('active', t.dataset.year === hashYear);
    });
  }
  if (hashColorBy && ['ELEM', 'MIDD', 'HIGH'].includes(hashColorBy)) {
    currentColorBy = hashColorBy;
    document.getElementById('colorBy').value = hashColorBy;
  }
  if (hashSchool) {
    currentSchoolFilter = hashSchool;
    // schoolFilter dropdown is synced after buildSchoolDropdown inside loadData
  } else if (hashType) {
    currentTypeFilter = hashType;
    document.getElementById('typeFilter').value = hashType;
  }
  if (hashBasemap && basemaps[hashBasemap]) {
    map.removeLayer(currentBasemap);
    currentBasemapKey = hashBasemap;
    currentBasemap = basemaps[currentBasemapKey];
    currentBasemap.addTo(map);
    document.getElementById('basemapSelect').value = currentBasemapKey;
    document.body.classList.toggle('dark-basemap', currentBasemapKey === 'dark');
  }
  if (hashPins) {
    currentPins = hashPins;
    document.getElementById('schoolPins').value = hashPins;
  }
}
loadData(currentYear);

// --------------------
// ADDRESS SEARCH
// --------------------
const searchInput = document.getElementById('searchInput');
const searchResults = document.getElementById('searchResults');
const searchInfo = document.getElementById('searchInfo');

let searchActiveIndex = -1;

function getSearchItems() {
  return searchResults.querySelectorAll('.search-result-item');
}

function setSearchActive(idx) {
  const items = getSearchItems();
  searchActiveIndex = Math.max(-1, Math.min(idx, items.length - 1));
  items.forEach((el, i) => el.classList.toggle('active', i === searchActiveIndex));
}

searchInput.addEventListener('input', () => {
  const query = searchInput.value.trim().toLowerCase();
  searchResults.innerHTML = '';
  searchActiveIndex = -1;
  searchInfo.style.display = 'none';

  if (query.length < 3) {
    searchResults.style.display = 'none';
    clearSearchMarker();
    return;
  }

  const matches = allAddresses
    .filter(p => p.address.toLowerCase().includes(query))
    .slice(0, 10);

  if (matches.length === 0) {
    searchResults.innerHTML = '<div class="search-no-results">No addresses found</div>';
    searchResults.style.display = 'block';
    return;
  }

  matches.forEach(point => {
    const item = document.createElement('div');
    item.className = 'search-result-item';
    item.textContent = point.address;
    item.addEventListener('click', () => selectAddress(point));
    searchResults.appendChild(item);
  });

  searchResults.style.display = 'block';
});

searchInput.addEventListener('keydown', e => {
  const items = getSearchItems();
  if (!items.length) return;
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    setSearchActive(searchActiveIndex + 1);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    setSearchActive(searchActiveIndex - 1);
  } else if (e.key === 'Enter') {
    const target = searchActiveIndex >= 0 ? items[searchActiveIndex] : items[0];
    if (target) target.click();
  }
});

// Close dropdown if clicking outside
document.addEventListener('click', e => {
  if (!document.getElementById('controls').contains(e.target)) {
    searchResults.style.display = 'none';
  }
});

document.getElementById('colorBy').addEventListener('change', e => {
  currentColorBy = e.target.value;
  currentSchoolFilter = '';
  currentTypeFilter = '';
  document.getElementById('schoolFilter').value = '';
  document.getElementById('typeFilter').value = '';
  updateClearBtn();
  withLoader('Applying colors…', recolor);
});

/**
 * Handles selection of an address from the search results dropdown.
 *
 * Clears any existing search and school markers, places a house icon marker
 * at the address location, adds icon pins at each assigned school's
 * physical location (sourced from schools.json), fits the map viewport to
 * show the address and all school markers together, and populates the
 * search info panel with the full school assignment list.
 *
 * @param {{ id: number, address: string, lat: number, lng: number,
 *   schools: Array<{name: string, type: string, zones: string[]}>}} point -
 *   A single address record from addresses_slim.json.
 */
function selectAddress(point) {
  searchInput.value = point.address;
  searchResults.style.display = 'none';

  // Place address highlight marker
  clearSearchMarker();
  clearSchoolMarkers();
  searchMarker = L.marker([point.lat, point.lng], {
    icon: L.icon({
      iconUrl:     'img/favicon-house.svg',
      iconSize:    [48, 48],
      iconAnchor:  [24, 24],
      popupAnchor: [0, -24],
    })
  }).addTo(map);

  // Sort schools by grade level so the sidebar always reads ELEM → MIDD → HIGH
  const sortedSchools = [...point.schools].sort(
    (a, b) => TYPE_PRIORITY.indexOf(a.type) - TYPE_PRIORITY.indexOf(b.type)
  );

  // Place a marker at each assigned school's physical location
  const boundsPoints = [[point.lat, point.lng]];
  sortedSchools.forEach(s => {
    const school = schoolsByName[s.name];
    if (!school) return;
    const marker = L.marker([school.lat, school.lng], {
      icon: schoolIcon(s.type)
    }).addTo(map);
    marker.bindPopup(schoolPopupHTML(school));
    schoolMarkers.push(marker);
    boundsPoints.push([school.lat, school.lng]);
  });

  // Fit map to show the searched address and all school markers
  if (boundsPoints.length > 1) {
    map.fitBounds(L.latLngBounds(boundsPoints).pad(0.2));
  } else {
    map.setView([point.lat, point.lng], 16);
  }

  // Show school info panel
  const schoolItems = sortedSchools
    .map(s => `<li><b>${s.name}</b> <span class="school-type">(${s.type})</span></li>`)
    .join('');

  const { street: addrStreet, city: addrCity } = splitAddress(point.address);

  searchInfo.innerHTML = `
    <div class="info-address">${addrStreet}${addrCity ? `<br><span class="info-city">${addrCity}</span>` : ''}</div>
    <ul>${schoolItems}</ul>
  `;
  // Filter map markers to show only addresses sharing a zone with this address
  searchZoneSchoolNames = new Set(sortedSchools.map(s => s.name));
  searchInfo.style.display = 'block';
  updateClearBtn();
  withLoader('Highlighting zones…', applyFilters);

  // On mobile, collapse the sidebar so the map result is immediately visible
  if (window.innerWidth < 768 && controls.classList.contains('open')) {
    controls.classList.remove('open');
    toggleBtn.textContent = '☰ Schools & Filters';
  }
}

/**
 * Removes the house icon marker placed by the most recent search.
 * No-op if no search marker is currently on the map.
 */
function clearSearchMarker() {
  if (searchMarker) {
    map.removeLayer(searchMarker);
    searchMarker = null;
  }
}

/**
 * Removes all school icon markers placed by the most recent address search
 * and resets the schoolMarkers array. No-op if no markers are present.
 */
function clearSchoolMarkers() {
  schoolMarkers.forEach(m => map.removeLayer(m));
  schoolMarkers = [];
}

/**
 * Removes the school icon marker placed when a school is selected via the
 * "Map by school" dropdown or a legend click, and clears the reference.
 * No-op if no filter marker is currently on the map.
 */
function clearFilterSchoolMarker() {
  if (filterSchoolMarker) {
    map.removeLayer(filterSchoolMarker);
    filterSchoolMarker = null;
  }
}

/**
 * Replaces the "School location pins" layer with markers for the selected type.
 *
 * Clears all existing school-location markers, then adds an icon pin for every
 * school in schoolsByName that matches the given type. An empty string removes
 * all pins without adding new ones.
 *
 * @param {string} typeFilter - Type code to display ('ELEM', 'K8', 'MIDD', 'HIGH',
 *   'ONLINE'), 'ALL' to show every school, or '' to show none.
 */
function updateSchoolPins(typeFilter) {
  allSchoolMarkers.forEach(m => map.removeLayer(m));
  allSchoolMarkers = [];
  if (!typeFilter) return;
  Object.values(schoolsByName).forEach(school => {
    if (typeFilter !== 'ALL' && school.type !== typeFilter) return;
    const marker = L.marker([school.lat, school.lng], {
      icon: schoolIcon(school.type)
    }).addTo(map);
    marker.bindPopup(schoolPopupHTML(school));
    allSchoolMarkers.push(marker);
  });
}

document.getElementById('schoolPins').addEventListener('change', e => {
  currentPins = e.target.value;
  updateSchoolPins(currentPins);
  syncHash();
});

document.querySelectorAll('.year-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    if (tab.dataset.year === currentYear) return;
    document.querySelectorAll('.year-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    currentYear         = tab.dataset.year;
    currentSchoolFilter = '';
    currentTypeFilter   = '';
    currentColorBy      = 'ELEM';
    currentPins         = '';
    searchZoneSchoolNames = null;
    document.getElementById('colorBy').value      = 'ELEM';
    document.getElementById('typeFilter').value   = '';
    document.getElementById('schoolFilter').value = '';
    document.getElementById('schoolPins').value   = '';
    document.getElementById('searchInput').value  = '';
    document.getElementById('searchResults').style.display = 'none';
    document.getElementById('searchInfo').innerHTML        = '';
    document.getElementById('searchInfo').style.display    = 'none';
    document.getElementById('schoolInfoStrip').style.display = 'none';
    document.getElementById('schoolInfoStrip').innerHTML   = '';
    clearSearchMarker();
    clearSchoolMarkers();
    clearFilterSchoolMarker();
    updateClearBtn();
    syncHash();
    loadData(currentYear);
  });
});

function updateClearBtn() {
  const active = searchMarker || currentSchoolFilter || currentTypeFilter || currentColorBy !== 'ELEM';
  document.getElementById('clearAllBtn').style.display = active ? '' : 'none';
}

function syncHash() {
  const parts = [];
  if (currentYear !== 'current')    parts.push('year='    + currentYear);
  if (currentSchoolFilter)          parts.push('school='  + encodeURIComponent(currentSchoolFilter));
  if (currentTypeFilter)            parts.push('type='    + encodeURIComponent(currentTypeFilter));
  if (currentColorBy !== 'ELEM')    parts.push('colorBy=' + currentColorBy);
  if (currentBasemapKey !== 'osm')  parts.push('basemap=' + currentBasemapKey);
  if (currentPins)                  parts.push('pins='    + encodeURIComponent(currentPins));
  if (parts.length) {
    history.replaceState(null, '', '#' + parts.join('&'));
  } else {
    history.replaceState(null, '', window.location.pathname + window.location.search);
  }
}

function resetAll() {
  history.replaceState(null, '', window.location.pathname + window.location.search);
  searchZoneSchoolNames = null;
  searchInput.value = '';
  searchResults.style.display = 'none';
  searchInfo.innerHTML = '';
  searchInfo.style.display = 'none';
  clearSearchMarker();
  clearSchoolMarkers();
  currentSchoolFilter = '';
  currentTypeFilter = '';
  currentColorBy = 'ELEM';
  document.getElementById('colorBy').value = 'ELEM';
  document.getElementById('schoolFilter').value = '';
  document.getElementById('typeFilter').value = '';
  currentPins = '';
  document.getElementById('schoolPins').value = '';
  updateSchoolPins('');
  map.flyToBounds(PITTSBURGH_BOUNDS);
  withLoader('Resetting…', recolor);
}


document.getElementById('clearAllBtn').addEventListener('click', resetAll);

document.getElementById('resetViewBtn').addEventListener('click', () => {
  map.flyToBounds(PITTSBURGH_BOUNDS);
});

// --------------------
// LEGEND
// --------------------
/**
 * Rebuilds the legend panel to show schools relevant to the current "Color by" mode.
 *
 * Collects school names whose type falls within the active colorBy group
 * (e.g., ELEM mode shows both ELEM and K8 schools), sorts them alphabetically,
 * and renders a colored dot and label for each. Clicking a legend item calls
 * toggleSchoolFromLegend to filter the map to that school's addresses.
 */
function buildLegend() {
  const legend = document.getElementById('legend');
  legend.innerHTML = '';

  // Determine which types are relevant to the current colorBy mode
  const relevantTypes = {
    ELEM: ['ELEM', 'K8'],
    MIDD: ['MIDD'],
    HIGH: ['HIGH'],
  }[currentColorBy] || [];

  // Single pass: collect type and address count per school
  const schoolInfo = new Map(); // name → { type, count }
  allMarkers.forEach(({ point }) => {
    point.schools.forEach(s => {
      if (!relevantTypes.includes(s.type)) return;
      if (!schoolInfo.has(s.name)) schoolInfo.set(s.name, { type: s.type, count: 0 });
      schoolInfo.get(s.name).count++;
    });
  });

  [...schoolInfo.keys()].sort().forEach(name => {
    const { type, count } = schoolInfo.get(name);
    const color = getSchoolColor(name, type).color;
    const item = document.createElement('div');
    item.className = 'legend-item';
    item.dataset.school = name;
    item.innerHTML = `
      <div class="legend-dot" style="background:${color}"></div>
      <span>${name}</span>
      <span class="legend-count">(${count.toLocaleString()})</span>
    `;
    item.addEventListener('click', () => toggleSchoolFromLegend(name, item));
    legend.appendChild(item);
  });
}

/**
 * Populates the "Map by school" dropdown with a sorted list of school names.
 *
 * Appends one <option> per name to the #schoolFilter <select> element.
 * Called once after address data finishes loading; names are pre-sorted
 * by the caller.
 *
 * @param {string[]} names - Alphabetically sorted list of unique school names
 *   derived from the loaded address dataset.
 */
/**
 * Shows or hides type-specific options in the "Map by type" and "Map school
 * locations" dropdowns based on which types actually exist in the loaded data.
 * Prevents dead-end selections (e.g. K8 or Online) when those types are absent
 * from the active dataset.
 *
 * @param {Set<string>} availableTypes - School type codes present in the dataset.
 */
function syncTypeOptions(availableTypes) {
  ['typeFilter', 'schoolPins'].forEach(id => {
    document.getElementById(id).querySelectorAll('option').forEach(opt => {
      if (!opt.value || opt.value === 'ALL') return;
      opt.hidden = !availableTypes.has(opt.value);
    });
  });
}

function buildSchoolDropdown(names) {
  const sel = document.getElementById('schoolFilter');
  names.forEach(name => {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  });
}

// --------------------
// FILTERING
// --------------------
const loader = document.getElementById('loader');
const loaderLabel = document.querySelector('#loader p');

// Shows the spinner, lets the browser paint, runs fn(), then hides it.
// Double-RAF is required: the first frame queues the repaint, the second
// runs after the browser has actually rendered the spinner.
/**
 * Shows the loading spinner, lets the browser paint it, runs a synchronous
 * function, then hides the spinner.
 *
 * A double requestAnimationFrame is required: the first frame queues the
 * repaint, and the second fires only after the browser has actually rendered
 * the spinner to the screen. Without the double RAF the spinner never appears
 * before the blocking work begins.
 *
 * @param {string} label - Text to display below the spinner.
 * @param {Function} fn - Synchronous function to execute while the spinner is visible.
 */
function withLoader(label, fn) {
  loaderLabel.textContent = label;
  loader.style.display = 'flex';
  requestAnimationFrame(() => requestAnimationFrame(() => {
    fn();
    loader.style.display = 'none';
  }));
}

document.getElementById('typeFilter').addEventListener('change', e => {
  currentTypeFilter = e.target.value;
  currentSchoolFilter = '';
  document.getElementById('schoolFilter').value = '';
  withLoader('Filtering…', applyFilters);
});

document.getElementById('schoolFilter').addEventListener('change', e => {
  currentSchoolFilter = e.target.value;
  currentTypeFilter = '';
  document.getElementById('typeFilter').value = '';
  withLoader('Filtering…', applyFilters);
});

/**
 * Applies the current type and school filters to all address markers.
 *
 * Shows or hides each marker based on currentTypeFilter and currentSchoolFilter,
 * then assigns the appropriate fill color: a uniform filter color when a single
 * school is selected, a per-type color when a type filter is active, or the
 * marker's stored primary color otherwise. Also dims non-matching legend items,
 * and places or removes the filter school marker pin depending on whether a
 * school filter is active and that school has known coordinates.
 */
function applyFilters() {
  const filterColor = currentSchoolFilter
  ? (() => {
      for (const { point } of allMarkers) {
        const match = point.schools.find(s => s.name === currentSchoolFilter);
        if (match) return getSchoolColor(currentSchoolFilter, match.type).color;
      }
      return null;
    })()
  : null;

  allMarkers.forEach(({ marker, point }) => {
    let visible = true;

    if (currentTypeFilter) {
      visible = point.schools.some(s => s.type === currentTypeFilter);
    }

    if (currentSchoolFilter) {
      visible = point.schools.some(s => s.name === currentSchoolFilter);
    }

    if (searchZoneSchoolNames) {
      visible = visible && point.schools.some(s => searchZoneSchoolNames.has(s.name));
    }

    if (visible) {
      if (!map.hasLayer(marker)) marker.addTo(map);

      let color;
      if (filterColor) {
        color = filterColor;
      } else if (currentTypeFilter) {
        color = marker._colorByType?.[currentTypeFilter] ?? '#aaa';
      } else {
        color = marker._primaryColor ?? '#aaa';
      }

      marker.setStyle({ color, fillColor: color });
    } else {
      if (map.hasLayer(marker)) map.removeLayer(marker);
    }
  });

  document.querySelectorAll('.legend-item').forEach(item => {
    const name = item.dataset.school;
    const active = !currentSchoolFilter || name === currentSchoolFilter;
    item.classList.toggle('dimmed', !active);
  });

  clearFilterSchoolMarker();
  const strip = document.getElementById('schoolInfoStrip');
  if (currentSchoolFilter && schoolsByName[currentSchoolFilter]) {
    const school = schoolsByName[currentSchoolFilter];
    filterSchoolMarker = L.marker([school.lat, school.lng], {
      icon: schoolIcon(school.type)
    }).addTo(map);
    filterSchoolMarker.bindPopup(schoolPopupHTML(school));
    map.flyTo([school.lat, school.lng], 15);

    const phoneHTML = school.main_phone
      ? `<a class="strip-link" href="tel:${school.main_phone.replace(/\D/g,'')}">${school.main_phone}</a>`
      : '';
    const hoursHTML = (school.start_time && school.end_time)
      ? `Hours: ${school.start_time} &ndash; ${school.end_time}`
      : '';
    const { street: streetLine, city: cityLine } = splitAddress(school.address);
    const zoneCount  = allMarkers.filter(({ point }) =>
      point.schools.some(s => s.name === currentSchoolFilter)).length;
    strip.innerHTML = `
      <strong>${school.name}</strong><br>
      <span class="strip-type">${TYPE_LABELS[school.type] || school.type}</span><br>
      <span class="strip-addr">${streetLine}</span><br>
      ${cityLine ? `<span class="strip-addr">${cityLine}</span><br>` : ''}
      ${phoneHTML || hoursHTML ? `${[phoneHTML, hoursHTML].filter(Boolean).join('<br>')}<br>` : ''}
      <span class="strip-count">${zoneCount.toLocaleString()} addresses in zone</span>
      <div style="display:flex;gap:6px;margin-top:8px">
        <button id="fitZoneBtn"  class="text-btn" style="flex:1;margin-top:0">Fit zone</button>
        <button id="copyLinkBtn" class="text-btn" style="flex:1;margin-top:0">Copy link</button>
      </div>`;
    strip.style.display = 'block';
    document.getElementById('fitZoneBtn').addEventListener('click', () => {
      const pts = allMarkers
        .filter(({ point }) => point.schools.some(s => s.name === currentSchoolFilter))
        .map(({ point }) => [point.lat, point.lng]);
      if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.1));
    });
    document.getElementById('copyLinkBtn').addEventListener('click', () => {
      navigator.clipboard.writeText(location.href).then(() => {
        const btn = document.getElementById('copyLinkBtn');
        if (!btn) return;
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = 'Copy link'; }, 1500);
      });
    });
  } else {
    strip.style.display = 'none';
    strip.innerHTML = '';
  }

  updateStatus();
  updateClearBtn();
  syncHash();
}

/**
 * Toggles a school filter on or off when the user clicks a legend item.
 *
 * If the clicked school is already the active filter it is cleared; otherwise
 * it becomes the new filter. Resets the type filter, syncs the school dropdown
 * to reflect the new state, and re-applies filters via withLoader.
 *
 * @param {string} name - The school name corresponding to the clicked legend item.
 */
function toggleSchoolFromLegend(name) {
  currentSchoolFilter = currentSchoolFilter === name ? '' : name;
  currentTypeFilter = '';
  document.getElementById('typeFilter').value = '';
  document.getElementById('schoolFilter').value = currentSchoolFilter;
  withLoader('Filtering…', applyFilters);
}

/**
 * Updates the status bar with the count of currently visible address markers.
 *
 * Counts markers present on the map and writes "Showing X of Y addresses"
 * to the #status element.
 */
function updateStatus() {
  const visible = allMarkers.filter(({ marker }) => map.hasLayer(marker)).length;
  document.getElementById('status').textContent = `Showing ${visible.toLocaleString()} of ${allMarkers.length.toLocaleString()} addresses`;
}

/**
 * Resets and recomputes all marker colors from scratch, then reapplies filters.
 *
 * Clears the schoolColorMap cache and re-registers a color for every school
 * that appears in the loaded data. For each address marker, stores the primary
 * color (highest-priority attendance school by TYPE_PRIORITY) in _primaryColor
 * and a per-type color lookup in _colorByType for use when a type filter is
 * active. Rebuilds the legend and re-runs applyFilters after recoloring.
 */
function recolor() {
  Object.keys(schoolColorMap).forEach(k => delete schoolColorMap[k]);

  // First pass: register a color for every school that appears anywhere
  allMarkers.forEach(({ point }) => {
    point.schools.forEach(s => getSchoolColor(s.name, s.type));
  });

  allMarkers.forEach(({ marker, point }) => {
    const primary = getPrimarySchool(point.schools);
    if (!primary) return;
    const color = getSchoolColor(primary.name, primary.type).color;

    marker.setStyle({ color, fillColor: color });
    marker._primaryColor = color;

    marker._colorByType = {};
    ['ELEM', 'MIDD', 'HIGH', 'K8', 'ONLINE'].forEach(type => {
      const match = point.schools.find(s =>
        s.type === type && s.zones.includes('attendance')
      );
      marker._colorByType[type] = match
        ? getSchoolColor(match.name, match.type).color
        : null;
    });
  });

  buildLegend();
  applyFilters();
}

// --------------------
// MOBILE TOGGLE
// --------------------
const toggleBtn = document.getElementById('toggleBtn');
const controls = document.getElementById('controls');

toggleBtn.addEventListener('click', () => {
  const isOpen = controls.classList.toggle('open');
  toggleBtn.textContent = isOpen ? '✕ Close' : '☰ Schools & Filters';
});

// Close panel when user picks an address on mobile
const origSelect = selectAddress;
selectAddress = function(point) {
  origSelect(point);
  if (window.innerWidth <= 600) {
    controls.classList.remove('open');
    toggleBtn.textContent = '☰ Schools & Filters';
  }
};

// --------------------
// ABOUT MODAL
// --------------------
const aboutBtn = document.getElementById('aboutBtn');
const aboutModal = document.getElementById('aboutModal');
const modalClose = document.getElementById('modalClose');

aboutBtn.addEventListener('click', () => {
  aboutModal.classList.add('open');
});

modalClose.addEventListener('click', () => {
  aboutModal.classList.remove('open');
});

// Close on clicking/tapping outside the modal box.
// touchend is added alongside click because iOS Safari doesn't reliably fire
// click on non-interactive overlay elements. preventDefault suppresses the
// ghost click iOS synthesizes ~300ms after touchend.
aboutModal.addEventListener('click', () => aboutModal.classList.remove('open'));
aboutModal.addEventListener('touchend', e => {
  e.preventDefault();
  aboutModal.classList.remove('open');
});
document.querySelector('#aboutModal .modal-box').addEventListener('click', e => e.stopPropagation());
document.querySelector('#aboutModal .modal-box').addEventListener('touchend', e => e.stopPropagation());

// Escape: close modal if open, otherwise fully reset the app
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if (aboutModal.classList.contains('open')) {
    aboutModal.classList.remove('open');
  } else {
    resetAll();
  }
});