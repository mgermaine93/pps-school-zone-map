/**
 * Unit tests for pure utility functions from index.js.
 *
 * index.js is a monolithic browser script and cannot be imported in Node
 * without heavily mocking Leaflet and the DOM. The functions under test are
 * declared inline here. If index.js is ever modularised, replace the
 * declarations below with imports.
 */

// ── getPrimarySchool ──────────────────────────────────────────────────────────

const TYPE_PRIORITY = ['ELEM', 'K8', 'MIDD', 'HIGH', 'ONLINE'];

function getPrimarySchool(schools) {
  for (const type of TYPE_PRIORITY) {
    const match = schools.find(s =>
      s.type === type && s.zones.includes('attendance')
    );
    if (match) return match;
  }
  return schools[0] ?? null;
}

describe('getPrimarySchool', () => {
  test('returns the highest-priority attendance school', () => {
    const schools = [
      { name: 'Allderdice', type: 'HIGH', zones: ['attendance'] },
      { name: 'Frick',      type: 'ELEM', zones: ['attendance'] },
    ];
    expect(getPrimarySchool(schools).name).toBe('Frick');
  });

  test('skips schools that lack an attendance zone', () => {
    const schools = [
      { name: 'Frick',      type: 'ELEM', zones: ['early'] },
      { name: 'Allderdice', type: 'HIGH', zones: ['attendance'] },
    ];
    expect(getPrimarySchool(schools).name).toBe('Allderdice');
  });

  test('falls back to first school when no attendance match exists', () => {
    const schools = [
      { name: 'CAPA',  type: 'HIGH', zones: ['magnet'] },
      { name: 'Obama', type: 'HIGH', zones: ['online'] },
    ];
    expect(getPrimarySchool(schools)).toBe(schools[0]);
  });

  test('returns null for an empty array', () => {
    // Previously crashed via schools[0].name on undefined — now returns null.
    expect(getPrimarySchool([])).toBeNull();
  });

  test('prefers ELEM over K8 when both have attendance zones', () => {
    const schools = [
      { name: 'Woolslair K8', type: 'K8',   zones: ['attendance'] },
      { name: 'Frick',        type: 'ELEM',  zones: ['attendance'] },
    ];
    expect(getPrimarySchool(schools).name).toBe('Frick');
  });

  test('returns K8 when no ELEM attendance school is present', () => {
    const schools = [
      { name: 'Woolslair K8', type: 'K8',  zones: ['attendance'] },
      { name: 'Allderdice',   type: 'HIGH', zones: ['attendance'] },
    ];
    expect(getPrimarySchool(schools).name).toBe('Woolslair K8');
  });

  test('returns ONLINE when it is the only type with attendance', () => {
    const schools = [
      { name: 'Online Academy', type: 'ONLINE', zones: ['attendance'] },
    ];
    expect(getPrimarySchool(schools).name).toBe('Online Academy');
  });
});

// ── getSchoolColor ────────────────────────────────────────────────────────────

let schoolColorMap = {};

function getSchoolColor(schoolName, type) {
  if (schoolColorMap[schoolName]) return schoolColorMap[schoolName];

  const hueRanges = {
    ELEM:   [140, 185],
    K8:     [35,  65],
    MIDD:   [210, 255],
    HIGH:   [300, 345],
    ONLINE: [18,  34],
  };

  const [hueMin, hueMax] = hueRanges[type] || [0, 360];

  const typeCount = Object.entries(schoolColorMap)
    .filter(([, v]) => v._type === type).length;

  const steps = 12;
  const hue = hueMin + ((typeCount * (hueMax - hueMin)) / steps) % (hueMax - hueMin);
  const lightness = 38 + (typeCount % 3) * 12;
  const color = `hsl(${hue.toFixed(1)}, 75%, ${lightness}%)`;

  schoolColorMap[schoolName] = { color, _type: type };
  return schoolColorMap[schoolName];
}

beforeEach(() => {
  schoolColorMap = {};
});

describe('getSchoolColor', () => {
  test('returns an object with color and _type fields', () => {
    const result = getSchoolColor('Frick Elementary', 'ELEM');
    expect(result).toHaveProperty('color');
    expect(result).toHaveProperty('_type', 'ELEM');
  });

  test('color string is a valid HSL value', () => {
    const { color } = getSchoolColor('Frick Elementary', 'ELEM');
    expect(color).toMatch(/^hsl\(\d+\.\d, 75%, \d+%\)$/);
  });

  test('same name returns the cached object reference', () => {
    const first  = getSchoolColor('Frick', 'ELEM');
    const second = getSchoolColor('Frick', 'ELEM');
    expect(first).toBe(second);
  });

  test('hue stays within the ELEM range [140, 185)', () => {
    const { color } = getSchoolColor('Frick Elementary', 'ELEM');
    const hue = parseFloat(color.match(/hsl\((\d+\.\d)/)[1]);
    expect(hue).toBeGreaterThanOrEqual(140);
    expect(hue).toBeLessThan(185);
  });

  test('hue stays within the HIGH range [300, 345)', () => {
    const { color } = getSchoolColor('Allderdice High', 'HIGH');
    const hue = parseFloat(color.match(/hsl\((\d+\.\d)/)[1]);
    expect(hue).toBeGreaterThanOrEqual(300);
    expect(hue).toBeLessThan(345);
  });

  test('unknown type falls back to [0, 360] range without producing NaN', () => {
    const { color } = getSchoolColor('Mystery School', 'UNKNOWN');
    const hue = parseFloat(color.match(/hsl\((\d+\.\d)/)[1]);
    expect(isNaN(hue)).toBe(false);
    expect(hue).toBeGreaterThanOrEqual(0);
    expect(hue).toBeLessThan(360);
  });

  test('two schools of the same type receive different hues', () => {
    const a = getSchoolColor('Frick Elementary', 'ELEM');
    const b = getSchoolColor('Woolslair Elementary', 'ELEM');
    expect(a.color).not.toBe(b.color);
  });

  test('schools of different types receive different _type tags', () => {
    const elem = getSchoolColor('Frick', 'ELEM');
    const high = getSchoolColor('Allderdice', 'HIGH');
    expect(elem._type).toBe('ELEM');
    expect(high._type).toBe('HIGH');
  });
});
