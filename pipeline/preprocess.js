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

fs.writeFileSync('data/addresses_slim.json', JSON.stringify(slim));
console.log(`Done. ${slim.length} addresses written.`);