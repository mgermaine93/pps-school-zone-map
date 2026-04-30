// --------------------
// MAP INIT
// --------------------
const map = L.map('map').setView([40.44, -79.99], 12);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

const renderer = L.canvas({ padding: 0.5 });

// --------------------
// COLOR ASSIGNMENT
// --------------------
const PALETTE = [
  '#e6194b','#3cb44b','#4363d8','#f58231','#911eb4',
  '#42d4f4','#f032e6','#bfef45','#fabed4','#469990',
  '#dcbeff','#9A6324','#fffac8','#800000','#aaffc3',
  '#808000','#ffd8b1','#000075','#a9a9a9','#e6beff',
  '#ff6b6b','#51cf66','#339af0','#fcc419','#cc5de8',
  '#20c997','#f06595','#74c0fc','#a9e34b','#ff922b'
];

const schoolColorMap = {};
let colorIndex = 0;

function getSchoolColor(schoolName) {
  if (!schoolColorMap[schoolName]) {
    schoolColorMap[schoolName] = PALETTE[colorIndex % PALETTE.length];
    colorIndex++;
  }
  return schoolColorMap[schoolName];
}

// --------------------
// PRIMARY SCHOOL LOGIC
// --------------------
const TYPE_PRIORITY = ['ELEM', 'K8', 'MIDD', 'HIGH', 'ONLINE'];

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

// --------------------
// LOAD DATA
// --------------------
fetch('cleaned_new_pps_schools.json')
  .then(res => res.json())
  .then(addresses => {
    allAddresses = addresses;
    const schoolNames = new Set();

    addresses.forEach(point => {
      if (point.lat == null || point.lng == null) return;
      if (!point.schools || point.schools.length === 0) return;

      const primary = getPrimarySchool(point.schools);
      const color = getSchoolColor(primary.name);
      schoolNames.add(primary.name);

      const marker = L.circleMarker([point.lat, point.lng], {
        renderer,
        radius: 4,
        color: color,
        weight: 1,
        fillColor: color,
        fillOpacity: 0.8
      });

      const schoolList = point.schools
        .map(s => `<li><b>${s.name}</b> <span style="color:#888">(${s.type})</span></li>`)
        .join('');

      marker.bindPopup(`
        <b>${point.address}</b><br>
        <small>ID: ${point.id}</small>
        <ul style="margin:6px 0 0;padding-left:16px;font-size:12px">${schoolList}</ul>
      `);

      marker.addTo(map);
      allMarkers.push({ marker, point, primary });
    });

    buildLegend();
    buildSchoolDropdown([...schoolNames].sort());
    updateStatus();
  })
  .catch(err => console.error('Error loading data:', err));

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

  const sorted = Object.entries(schoolColorMap).sort((a, b) => a[0].localeCompare(b[0]));

  sorted.forEach(([name, color]) => {
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
document.getElementById('typeFilter').addEventListener('change', e => {
  currentTypeFilter = e.target.value;
  currentSchoolFilter = '';
  document.getElementById('schoolFilter').value = '';
  applyFilters();
});

document.getElementById('schoolFilter').addEventListener('change', e => {
  currentSchoolFilter = e.target.value;
  currentTypeFilter = '';
  document.getElementById('typeFilter').value = '';
  applyFilters();
});

function applyFilters() {
  allMarkers.forEach(({ marker, point, primary }) => {
    let visible = true;

    if (currentTypeFilter) {
      visible = point.schools.some(s => s.type === currentTypeFilter);
    }

    if (currentSchoolFilter) {
      visible = primary.name === currentSchoolFilter;
    }

    if (visible) {
      if (!map.hasLayer(marker)) marker.addTo(map);
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
  applyFilters();
}

function updateStatus() {
  const visible = allMarkers.filter(({ marker }) => map.hasLayer(marker)).length;
  document.getElementById('status').textContent = `Showing ${visible.toLocaleString()} of ${allMarkers.length.toLocaleString()} addresses`;
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