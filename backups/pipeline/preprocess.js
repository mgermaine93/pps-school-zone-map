// preprocess.js — run with: node preprocess.js
const fs = require('fs');

const data = JSON.parse(fs.readFileSync('data/cleaned_new_pps_schools.json', 'utf8'));

const slim = data
  .filter(p => p.lat != null && p.lng != null && p.schools && p.schools.length > 0)
  .map(p => ({
    id: p.id,
    address: p.address,
    // lat: p.lat,
    // lng: p.lng,
    lat: Math.round(p.lat * 1e5) / 1e5,
    lng: Math.round(p.lng * 1e5) / 1e5,
    schools: p.schools.map(s => ({
      name: s.name,
      type: s.type,
      zones: s.zones
    }))
    // drops p.raw, p.error, p.school_count — not needed by the map
  }));

fs.writeFileSync('data/addresses_slim_2.json', JSON.stringify(slim));

// Build address → coords lookup so school pins use the same coordinates
// as the dot already plotted for that address, not a separate Nominatim result
const addressCoords = new Map();
data.forEach(p => {
  if (p.lat != null && p.lng != null && p.address) {
    addressCoords.set(p.address, {
      lat: Math.round(p.lat * 1e5) / 1e5,
      lng: Math.round(p.lng * 1e5) / 1e5
    });
  }
});

// Extract unique schools (id → object) for geocoding
const schoolsMap = new Map();
data.forEach(p => {
  (p.schools || []).forEach(s => {
    if (s.id != null && !schoolsMap.has(s.id)) {
      const school = { id: s.id, name: s.name, address: s.address, type: s.type };
      const coords = s.address && addressCoords.get(s.address);
      if (coords) { school.lat = coords.lat; school.lng = coords.lng; }
      schoolsMap.set(s.id, school);
    }
  });
});
const schools = [...schoolsMap.values()].sort((a, b) => a.name.localeCompare(b.name));
fs.writeFileSync('data/schools.json', JSON.stringify(schools, null, 2));

console.log(`Done. ${slim.length} addresses and ${schools.length} schools written.`);