/**
 * THE VANISHED BLUE GRID — Earth Engine extraction, v2
 *
 * Paste into https://code.earthengine.google.com and press Run.
 * Then set CITY to the other entry and Run again.
 *
 * Exports per city:
 *   rgb2005      true colour Landsat 5, mid 2000s
 *   rgb2025      true colour Sentinel-2, today
 *   historic     water present 1984-1999
 *   present      water still present 2000-2021
 *   encroached   former water now under buildings
 *   flowpath     natural drainage lines from terrain
 *   floodprone   low ground that receives what the lakes no longer hold
 *   + a ranked GeoJSON of flagged buildings
 */

// ---------------------------------------------------------------------------
// 1. CITY
// ---------------------------------------------------------------------------
// Switch this one line and re-run to prove the method is not hand-tuned to
// a single place. Everything below is city-agnostic.
var CITIES = {
  bengaluru: {
    name: 'Bengaluru — Bellandur & Varthur catchment',
    aoi: ee.Geometry.Rectangle([77.63, 12.90, 77.75, 12.97])
  },
  chennai: {
    name: 'Chennai — Pallikaranai marsh',
    aoi: ee.Geometry.Rectangle([80.180, 12.900, 80.280, 12.985])
  }
};

var CITY = CITIES.bengaluru;   // <-- change to CITIES.chennai and Run again

var AOI = CITY.aoi;
Map.centerObject(AOI, 13);
print('=== ' + CITY.name + ' ===');

// Common resolution for every comparison. Both eras get measured at the
// coarser sensor's scale, because a 10m sensor finds more water than a 30m one
// whatever is on the ground, and that gap would otherwise read as water
// appearing out of nowhere.
var SCALE = 30;
var MIN_PATCH_PIXELS = 4;

// Post-monsoon, when tanks are fullest. Same window in both eras.
var SEASON_START = 10, SEASON_END = 1;

// ---------------------------------------------------------------------------
// 2. TRUE COLOUR, THEN AND NOW
// ---------------------------------------------------------------------------
function maskLandsat5(image) {
  var qa = image.select('QA_PIXEL');
  var clear = qa.bitwiseAnd(1 << 1).eq(0)
    .and(qa.bitwiseAnd(1 << 3).eq(0))
    .and(qa.bitwiseAnd(1 << 4).eq(0));
  return image.select('SR_B.').multiply(0.0000275).add(-0.2)
    .updateMask(clear).copyProperties(image, ['system:time_start']);
}

function maskS2(image) {
  var qa = image.select('QA60');
  var clear = qa.bitwiseAnd(1 << 10).eq(0).and(qa.bitwiseAnd(1 << 11).eq(0));
  return image.divide(10000).updateMask(clear)
    .copyProperties(image, ['system:time_start']);
}

var l5 = ee.ImageCollection('LANDSAT/LT05/C02/T1_L2')
  .filterBounds(AOI).filterDate('2003-01-01', '2008-01-01')
  .filter(ee.Filter.calendarRange(SEASON_START, SEASON_END, 'month'))
  .map(maskLandsat5).median();

var s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(AOI).filterDate('2023-01-01', '2026-01-01')
  .filter(ee.Filter.calendarRange(SEASON_START, SEASON_END, 'month'))
  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
  .map(maskS2).median();

// Identical stretch on both, so the eye compares ground cover rather than
// two different contrast curves. Landsat 5 is 30m and will look soft next to
// Sentinel-2 at 10m; that softness is honest and reads as "old photograph".
var VIS = {min: 0.02, max: 0.30, gamma: 1.25};
var rgb2005 = l5.select(['SR_B3', 'SR_B2', 'SR_B1']);
var rgb2025 = s2.select(['B4', 'B3', 'B2']);

// ---------------------------------------------------------------------------
// 3. THE TWO ERAS OF WATER, FROM ONE SOURCE
// ---------------------------------------------------------------------------
// JRC Global Surface Water already compared eras across the whole Landsat
// archive with one method. Its transition band encodes each pixel's history as
// a single class, 1984-1999 against 2000-2021:
//   1 permanent   2 new permanent   3 LOST permanent
//   4 seasonal    5 new seasonal    6 LOST seasonal
//   7 seasonal>permanent   8 permanent>seasonal
//   9,10 ephemeral
// Deriving both eras from this one band is what keeps the comparison honest.
// Hand-differencing Landsat against Sentinel-2 cannot be made symmetric.
var gsw = ee.Image('JRC/GSW1_4/GlobalSurfaceWater');
var T = gsw.select('transition');

function isClass(img, classes) {
  return ee.Image(classes).eq(img).reduce(ee.Reducer.max());
}

var historicWater = isClass(T, [1, 3, 4, 6, 7, 8]).rename('historic');
var presentWaterJRC = isClass(T, [1, 2, 4, 5, 7, 8]).rename('present');
var jrcLost = isClass(T, [3, 6]);

// ---------------------------------------------------------------------------
// 4. WHAT IS THERE NOW
// ---------------------------------------------------------------------------
var dw = ee.ImageCollection('GOOGLE/DYNAMICWORLD/V1')
  .filterBounds(AOI).filterDate('2023-01-01', '2026-01-01')
  .select('label').mode();

var builtNow = dw.eq(6).rename('built');

// Flooded vegetation must not count as open water in the area figures: it
// fires readily on paddy and wet cropland. But it does have to block a "lost"
// verdict, because Bellandur and Varthur sit under dense hyacinth mats and
// read as plants in every water index. Two jobs, two masks.
var stillWetGuard = dw.eq(0).or(dw.eq(3));

var lostRaw = historicWater.and(presentWaterJRC.not()).and(stillWetGuard.not())
  .or(jrcLost.and(stillWetGuard.not()));

// selfMask() before counting, or connectedPixelCount measures the size of the
// huge contiguous zero region too and the whole script crawls.
var lostWater = lostRaw.selfMask()
  .connectedPixelCount(32, true).gte(MIN_PATCH_PIXELS)
  .unmask(0).clip(AOI).rename('lost');

var encroached = lostWater.and(builtNow).clip(AOI).rename('encroached');

// ---------------------------------------------------------------------------
// 5. TERRAIN — WHERE THE WATER STILL WANTS TO GO
// ---------------------------------------------------------------------------
// MERIT Hydro ships precomputed hydrology at 90m, so there is no flow
// accumulation to calculate.
//   upa = upstream drainage area in km2, how much rain funnels through here
//   hnd = height above nearest drainage in metres, how deep in a water path
var merit = ee.Image('MERIT/Hydro/v1_0_1');
var upstreamArea = merit.select('upa');
var hand = merit.select('hnd');

var flowPath = upstreamArea.gt(2).and(hand.lt(2)).clip(AOI).rename('flowpath');

// Low ground: where water ends up once the tanks that used to hold it are
// gone. This is the downstream half of the argument, and the reason the people
// who flood are rarely the people who built.
var floodProne = hand.lt(2).clip(AOI).rename('floodprone');

// ---------------------------------------------------------------------------
// 6. BUILDINGS
// ---------------------------------------------------------------------------
var buildings = ee.FeatureCollection('GOOGLE/Research/open-buildings/v3/polygons')
  .filterBounds(AOI)
  .filter(ee.Filter.gte('confidence', 0.70))
  .filter(ee.Filter.gte('area_in_meters', 40));

var signals = lostWater.rename('lost_frac')
  .addBands(flowPath.unmask(0).rename('flow_frac'))
  .addBands(upstreamArea.rename('upstream_km2'))
  .addBands(hand.rename('hand_m'));

// No reduceToVectors. Vectorising the mask and spatially joining against it
// produced tens of thousands of polygons and hung the script. A tight AOI plus
// tileScale is both faster and simpler.
var scored = signals.reduceRegions({
  collection: buildings, reducer: ee.Reducer.mean(), scale: SCALE, tileScale: 8
});

var flagged = scored.map(function (f) {
  var lost = ee.Number(ee.Algorithms.If(f.get('lost_frac'), f.get('lost_frac'), 0));
  var flow = ee.Number(ee.Algorithms.If(f.get('flow_frac'), f.get('flow_frac'), 0));
  var upa = ee.Number(ee.Algorithms.If(f.get('upstream_km2'), f.get('upstream_km2'), 0));
  var h = ee.Number(ee.Algorithms.If(f.get('hand_m'), f.get('hand_m'), 50));

  var onWater = lost.max(flow);
  var score = onWater
    .multiply(upa.add(1).log10())
    .multiply(ee.Number(1).divide(h.max(0).add(1)))
    .multiply(100);

  var verdict = ee.Algorithms.If(
    lost.gt(0.5), 'RED_FORMER_WATER_BODY',
    ee.Algorithms.If(flow.gt(0.5), 'RED_BLOCKS_DRAINAGE',
      ee.Algorithms.If(onWater.gt(0.15), 'AMBER_PARTIAL', 'GREEN_CLEAR')));

  return f.set({
    risk_score: score, verdict: verdict, lost_frac: lost, flow_frac: flow,
    upstream_km2: upa, hand_m: h
  });
}).filter(ee.Filter.gt('risk_score', 1));

// ---------------------------------------------------------------------------
// 7. FIGURES
// ---------------------------------------------------------------------------
var HA = ee.Image.pixelArea().divide(10000);
function hectares(mask) {
  return HA.updateMask(mask.clip(AOI)).reduceRegion({
    reducer: ee.Reducer.sum(), geometry: AOI, scale: SCALE, maxPixels: 1e10
  }).get('area');
}

print('Historic water (ha):', hectares(historicWater));
print('Present water (ha):', hectares(presentWaterJRC));
print('Lost water (ha):', hectares(lostWater));
print('Built on former water (ha):', hectares(encroached));
print('Flood-prone low ground (ha):', hectares(floodProne));

// The downstream half of the story, as one number: how many structures sit on
// the low ground that now receives what the lost tanks used to hold.
print('Buildings in flood-prone low ground:',
  buildings.filterBounds(floodProne.selfMask().reduceToVectors({
    geometry: AOI, scale: 90, geometryType: 'polygon',
    maxPixels: 1e9, bestEffort: true
  })).size());

// ---------------------------------------------------------------------------
// 8. MAP
// ---------------------------------------------------------------------------
Map.addLayer(rgb2005, VIS, '2005 true colour', false);
Map.addLayer(rgb2025, VIS, '2025 true colour', false);
Map.addLayer(historicWater.clip(AOI).selfMask(), {palette: ['1f6feb']}, 'Historic water');
Map.addLayer(presentWaterJRC.clip(AOI).selfMask(), {palette: ['58a6ff']}, 'Present water');
Map.addLayer(floodProne.selfMask(), {palette: ['bc8cff']}, 'Flood-prone', false);
Map.addLayer(flowPath.selfMask(), {palette: ['d29922']}, 'Flow paths', false);
Map.addLayer(encroached.selfMask(), {palette: ['f85149']}, 'BUILT ON WATER');
// Buildings are deliberately not drawn: rendering them forces the whole
// per-building scoring to run interactively and hit the interactive timeout.

// ---------------------------------------------------------------------------
// 9. EXPORTS
// ---------------------------------------------------------------------------
print('AOI bounds:', AOI.bounds());

var THUMB = {region: AOI, dimensions: 2048, format: 'png'};

print('PNG rgb2005:', rgb2005.clip(AOI).visualize(VIS).getThumbURL(THUMB));
print('PNG rgb2025:', rgb2025.clip(AOI).visualize(VIS).getThumbURL(THUMB));
print('PNG historic:', historicWater.clip(AOI).selfMask()
  .visualize({palette: ['1f6feb'], opacity: 1}).getThumbURL(THUMB));
print('PNG present:', presentWaterJRC.clip(AOI).selfMask()
  .visualize({palette: ['58a6ff'], opacity: 1}).getThumbURL(THUMB));
print('PNG encroached:', encroached.selfMask()
  .visualize({palette: ['f85149'], opacity: 1}).getThumbURL(THUMB));
print('PNG flowpath:', flowPath.selfMask()
  .visualize({palette: ['d29922'], opacity: 1}).getThumbURL(THUMB));
print('PNG floodprone:', floodProne.selfMask()
  .visualize({palette: ['bc8cff'], opacity: 1}).getThumbURL(THUMB));

// Run from the Tasks tab. Export tasks get far more time than anything
// computed interactively, which is why the building scoring lives here.
Export.table.toDrive({
  collection: flagged,
  description: 'blue_grid_flagged_buildings',
  fileFormat: 'GeoJSON',
  selectors: ['risk_score', 'verdict', 'lost_frac', 'flow_frac',
              'upstream_km2', 'hand_m', 'area_in_meters', 'confidence']
});
