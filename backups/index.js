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
const map = L.map('map').setView([40.44, -79.99], 12);

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
  currentBasemap = basemaps[e.target.value];
  currentBasemap.addTo(map);
  document.body.classList.toggle('dark-basemap', e.target.value === 'dark');
});

const renderer = L.canvas({ padding: 0.5 });
const schoolColorMap = {};

/**
 * Retrieves or generates a deterministic HSL color for a school.
 *
 * Colors are assigned once per school name and cached in schoolColorMap.
 * Each school type owns a fixed hue range so type groups remain visually
 * distinct even when the "Color by" mode changes. Lightness alternates
 * across three values to maximize contrast between schools in the same type.
 *
 * @param {string} schoolName - The school's display name, used as the cache key.
 * @param {string} type - School type code: 'ELEM', 'K8', 'MIDD', 'HIGH', or 'ONLINE'.
 * @returns {{ color: string, _type: string }} Cached entry with the HSL color
 *   string and the type it was registered under.
 */
function getSchoolColor(schoolName, type) {
  if (schoolColorMap[schoolName]) return schoolColorMap[schoolName];

  // Each type gets its own hue range so types are visually distinct
  // even if a user switches Color By modes
  const hueRanges = {
    ELEM:   [90,  170],  // greens
    K8:     [170, 220],  // teals/cyans
    MIDD:   [220, 280],  // blues/purples
    HIGH:   [280, 360],  // pinks/reds
    ONLINE: [30,  90],   // yellows/oranges
  };

  const [hueMin, hueMax] = hueRanges[type] || [0, 360];

  // Count how many schools of this type already have colors
  const typeCount = Object.entries(schoolColorMap)
    .filter(([, v]) => v._type === type).length;

  // Spread evenly within the hue range, alternating lightness
  const steps = 12; // max schools per type before wrapping
  const hue = hueMin + ((typeCount * (hueMax - hueMin)) / steps) % (hueMax - hueMin);
  const lightness = 38 + (typeCount % 3) * 12; // 38%, 50%, 62%
  const color = `hsl(${hue.toFixed(1)}, 75%, ${lightness}%)`;

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
  return schools[0];
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

// --------------------
// LOAD DATA
// --------------------
fetch('data/schools.json')
  .then(res => res.json())
  .then(schools => {
    schools.forEach(s => {
      if (s.lat != null) schoolsByName[s.name] = s;
    });
  })
  .catch(() => {});  // non-critical — address search still works without it

fetch('data/addresses_slim.json')
  .then(res => res.json())
  .then(addresses => {
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

    // Add markers in chunks to keep the UI responsive during load
    const CHUNK_SIZE = 2000;
    const loaderText = document.querySelector('#loader p');
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
          radius: 4,
          color: '#aaa',
          weight: 1,
          fillColor: '#aaa',
          fillOpacity: 0.8
        });

        // Generate popup HTML only on click, not for all 116k markers at load time
        marker.bindPopup(() => {
          const schoolList = point.schools
            .map(s => `<li><b>${s.name}</b> <span style="color:#888">(${s.type})</span></li>`)
            .join('');
          return `
            <b>${point.address}</b><br>
            <small>ID: ${point.id}</small>
            <ul style="margin:6px 0 0;padding-left:16px;font-size:12px">${schoolList}</ul>
          `;
        });

        marker.addTo(map);
        allMarkers.push({ marker, point });
      }

      if (i < addresses.length) {
        loaderText.textContent = `Loading ${i.toLocaleString()} / ${addresses.length.toLocaleString()} addresses…`;
        requestAnimationFrame(processChunk);
      } else {
        recolor();
        updateStatus();
        document.getElementById('loader').style.display = 'none';
      }
    }

    requestAnimationFrame(processChunk);
  })
  .catch(err => {
    console.error('Error loading data:', err);
    document.getElementById('loader').style.display = 'none';
  });

// --------------------
// ADDRESS SEARCH
// --------------------
const searchInput = document.getElementById('searchInput');
const searchResults = document.getElementById('searchResults');
const searchInfo = document.getElementById('searchInfo');

searchInput.addEventListener('input', () => {
  const query = searchInput.value.trim().toLowerCase();
  searchResults.innerHTML = '';
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
    searchResults.style.display = 'none';
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
  withLoader('Applying colors…', recolor);
});

/**
 * Handles selection of an address from the search results dropdown.
 *
 * Clears any existing search and school markers, places a red highlight
 * circle at the address location, adds icon pins at each assigned school's
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
  searchMarker = L.circleMarker([point.lat, point.lng], {
    radius: 10,
    color: '#ffffff',
    weight: 3,
    fillColor: '#ff4444',
    fillOpacity: 1
  }).addTo(map);

  // Place a marker at each assigned school's physical location
  const boundsPoints = [[point.lat, point.lng]];
  point.schools.forEach(s => {
    const school = schoolsByName[s.name];
    if (!school) return;
    const marker = L.marker([school.lat, school.lng], {
      icon: schoolIcon(s.type)
    }).addTo(map);
    marker.bindPopup(`
      <b>${school.name}</b><br>
      <span style="color:#888;font-size:12px">${school.type}</span><br>
      <small style="color:#666">${school.address}</small>
    `);
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
  const schoolItems = point.schools
    .map(s => `<li><b>${s.name}</b> <span class="school-type">(${s.type} — ${s.zones.join(', ')})</span></li>`)
    .join('');

  searchInfo.innerHTML = `
    <div class="info-address">${point.address}</div>
    <ul>${schoolItems}</ul>
  `;
  searchInfo.style.display = 'block';
}

/**
 * Removes the address highlight circle placed by the most recent search.
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
 * "Filter by school" dropdown or a legend click, and clears the reference.
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
    marker.bindPopup(`
      <b>${school.name}</b><br>
      <span style="color:#888;font-size:12px">${school.type}</span><br>
      <small style="color:#666">${school.address}</small>
    `);
    allSchoolMarkers.push(marker);
  });
}

document.getElementById('schoolPins').addEventListener('change', e => {
  updateSchoolPins(e.target.value);
});

// Clear markers when user dismisses the search
searchInput.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    searchInput.value = '';
    searchResults.style.display = 'none';
    searchInfo.style.display = 'none';
    clearSearchMarker();
    clearSchoolMarkers();
  }
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

  // Collect school names that match the current color mode
  const relevantSchools = new Set();
  allMarkers.forEach(({ point }) => {
    point.schools.forEach(s => {
      if (relevantTypes.includes(s.type)) {
        relevantSchools.add(s.name);
      }
    });
  });

  const sorted = [...relevantSchools].sort();

  sorted.forEach(name => {
    // find the type for this school name
    const schoolType = (() => {
      for (const { point } of allMarkers) {
        const match = point.schools.find(s => s.name === name);
        if (match) return match.type;
      }
      return 'ELEM';
    })();
    const color = getSchoolColor(name, schoolType).color;
    const item = document.createElement('div');
    item.className = 'legend-item';
    item.dataset.school = name;
    item.innerHTML = `
      <div class="legend-dot" style="background:${color}"></div>
      <span>${name}</span>
    `;
    item.addEventListener('click', () => toggleSchoolFromLegend(name, item));
    legend.appendChild(item);
  });
}

/**
 * Populates the "Filter by school" dropdown with a sorted list of school names.
 *
 * Appends one <option> per name to the #schoolFilter <select> element.
 * Called once after address data finishes loading; names are pre-sorted
 * by the caller.
 *
 * @param {string[]} names - Alphabetically sorted list of unique school names
 *   derived from the loaded address dataset.
 */
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
  if (currentSchoolFilter && schoolsByName[currentSchoolFilter]) {
    const school = schoolsByName[currentSchoolFilter];
    filterSchoolMarker = L.marker([school.lat, school.lng], {
      icon: schoolIcon(school.type)
    }).addTo(map);
    filterSchoolMarker.bindPopup(`
      <b>${school.name}</b><br>
      <span style="color:#888;font-size:12px">${school.type}</span><br>
      <small style="color:#666">${school.address}</small>
    `);
  }

  updateStatus();
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

// Close on clicking outside the modal box
aboutModal.addEventListener('click', e => {
  if (e.target === aboutModal) aboutModal.classList.remove('open');
});

// Close on Escape
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') aboutModal.classList.remove('open');
});