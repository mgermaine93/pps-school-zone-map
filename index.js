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

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

const renderer = L.canvas({ padding: 0.5 });
const schoolColorMap = {};

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
// PRIMARY SCHOOL LOGIC
// --------------------
const TYPE_PRIORITY = ['ELEM', 'K8', 'MIDD', 'HIGH', 'ONLINE'];

function getPrimarySchool(schools) {
  // console.log(schools)
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
let currentColorBy = "ELEM";

// --------------------
// LOAD DATA
// --------------------
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

function selectAddress(point) {
  // Update input and hide dropdown
  searchInput.value = point.address;
  searchResults.style.display = 'none';

  // Zoom to address
  map.setView([point.lat, point.lng], 16);

  // Place a highlight marker
  clearSearchMarker();
  searchMarker = L.circleMarker([point.lat, point.lng], {
    radius: 10,
    color: '#ffffff',
    weight: 3,
    fillColor: '#ff4444',
    fillOpacity: 1
  }).addTo(map);

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

function clearSearchMarker() {
  if (searchMarker) {
    map.removeLayer(searchMarker);
    searchMarker = null;
  }
}

// Clear search marker if user clears the input
searchInput.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    searchInput.value = '';
    searchResults.style.display = 'none';
    searchInfo.style.display = 'none';
    clearSearchMarker();
  }
});

// --------------------
// LEGEND
// --------------------
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

  updateStatus();
}

function toggleSchoolFromLegend(name, item) {
  currentSchoolFilter = currentSchoolFilter === name ? '' : name;
  currentTypeFilter = '';
  document.getElementById('typeFilter').value = '';
  document.getElementById('schoolFilter').value = currentSchoolFilter;
  withLoader('Filtering…', applyFilters);
}

function updateStatus() {
  const visible = allMarkers.filter(({ marker }) => map.hasLayer(marker)).length;
  document.getElementById('status').textContent = `Showing ${visible.toLocaleString()} of ${allMarkers.length.toLocaleString()} addresses`;
}

function recolor() {
  Object.keys(schoolColorMap).forEach(k => delete schoolColorMap[k]);

  // First pass: register a color for every school that appears anywhere
  allMarkers.forEach(({ point }) => {
    point.schools.forEach(s => getSchoolColor(s.name, s.type));
  });

  allMarkers.forEach(({ marker, point }) => {
    const primary = getPrimarySchool(point.schools, currentColorBy);
    const color = getSchoolColor(primary.name, primary.type).color;  // ← .color

    marker.setStyle({ color, fillColor: color });
    marker._primary = primary;
    marker._primaryColor = color;

    marker._colorByType = {};
    ['ELEM', 'MIDD', 'HIGH', 'K8', 'ONLINE'].forEach(type => {
      const match = point.schools.find(s =>
        s.type === type && s.zones.includes('attendance')
      );
      marker._colorByType[type] = match
        ? getSchoolColor(match.name, match.type).color  // ← .color
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