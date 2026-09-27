// deckOS offline map. Everything comes from deck-mapd on this machine.
"use strict";

const $ = (id) => document.getElementById(id);
const api = (path, opts) => fetch("/api/" + path, opts).then((r) => r.json());
const status = (t) => { $("status").textContent = t; };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

let maps = [];
let current = null;          // map region in use
let theme = "night";
let me = null;               // last GPS fix
let selected = null;         // {lat, lon, name} chosen from search/click
let pinMode = false;
const overlays = {};         // name -> GeoJSON FeatureCollection

// ---- style ----------------------------------------------------------------------------
function styleFor(region) {
  const flavor = theme === "day" ? "light" : "dark";
  return {
    version: 8,
    glyphs: location.origin + "/vendor/fonts/{fontstack}/{range}.pbf",
    sprite: location.origin + "/vendor/sprites/v4/" + flavor,
    sources: {
      protomaps: {
        type: "vector",
        url: "pmtiles://" + location.origin + region.url,
        attribution: "© OpenStreetMap contributors · Protomaps",
      },
    },
    layers: basemaps.layers("protomaps", basemaps.namedFlavor(flavor), { lang: "en" }),
  };
}

function regionFor(lng, lat) {
  const inside = maps.find((m) => m.bbox && lng >= m.bbox[0] && lat >= m.bbox[1] && lng <= m.bbox[2] && lat <= m.bbox[3]);
  return inside || maps[maps.length - 1] || null;
}

const OVERLAY_LAYERS = [
  ["route", { type: "line", paint: { "line-color": "#ffd060", "line-width": 5, "line-opacity": 0.85 } }],
  ["wiki", { type: "circle", paint: { "circle-radius": 6, "circle-color": "#7fb3ff", "circle-stroke-color": "#000", "circle-stroke-width": 1 } }],
  ["ft8", { type: "circle", paint: { "circle-radius": 4, "circle-color": "#c080ff", "circle-opacity": 0.8 } }],
  ["waypoints", { type: "circle", paint: { "circle-radius": 7, "circle-color": "#6fdc6f", "circle-stroke-color": "#000", "circle-stroke-width": 1 } }],
  ["mesh", { type: "circle", paint: { "circle-radius": 7, "circle-color": "#ffb000", "circle-stroke-color": "#000", "circle-stroke-width": 1 } }],
  ["me", { type: "circle", paint: { "circle-radius": 8, "circle-color": "#ff4a3d", "circle-stroke-color": "#fff", "circle-stroke-width": 2 } }],
];

function addOverlays() {
  for (const [name, spec] of OVERLAY_LAYERS) {
    if (!map.getSource(name)) map.addSource(name, { type: "geojson", data: overlays[name] || emptyFC() });
    if (!map.getLayer(name)) map.addLayer({ id: name, source: name, ...spec });
    if (spec.type === "circle" && !map.getLayer(name + "-label")) {
      map.addLayer({
        id: name + "-label", source: name, type: "symbol",
        layout: { "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"], "text-size": 12, "text-offset": [0, 1.2], "text-anchor": "top" },
        paint: { "text-color": theme === "day" ? "#000" : "#ffb000", "text-halo-color": theme === "day" ? "#fff" : "#000", "text-halo-width": 1.5 },
      });
    }
  }
  applyLayerToggles();
}

function emptyFC() { return { type: "FeatureCollection", features: [] }; }
function pointFC(items) {
  return { type: "FeatureCollection", features: items.map((i) => ({ type: "Feature", geometry: { type: "Point", coordinates: [i.lon, i.lat] }, properties: i })) };
}
function setOverlay(name, fc) {
  overlays[name] = fc;
  const src = map.getSource(name);
  if (src) src.setData(fc);
}

function applyLayerToggles() {
  const vis = { mesh: $("l-mesh").checked, waypoints: $("l-mesh").checked, wiki: $("l-wiki").checked, ft8: $("l-ft8").checked };
  for (const [name, on] of Object.entries(vis)) {
    for (const id of [name, name + "-label"]) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  }
}

// ---- start ----------------------------------------------------------------------------
const hash = location.hash.slice(1).split(",").map(Number);
const start = hash.length >= 2 && hash.every((n) => !isNaN(n)) ? { lat: hash[0], lon: hash[1], z: hash[2] || 14 } : null;

const map = new maplibregl.Map({
  container: "map",
  style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#0b0906" } }] },
  center: start ? [start.lon, start.lat] : [-1.5, 53.0],
  zoom: start ? start.z : 5,
  attributionControl: { compact: true },
  hash: false,
});
map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "top-right");
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

api("maps").then((d) => {
  maps = d.maps || [];
  theme = d.theme || "night";
  document.body.classList.toggle("day", theme === "day");
  if (!maps.length) {
    status("No maps installed — open Library and download a map region.");
    return;
  }
  const c = map.getCenter();
  switchRegion(regionFor(c.lng, c.lat));
  if (start) { selected = { lat: start.lat, lon: start.lon, name: "Search result" }; showSelected(); }
});

function switchRegion(region) {
  if (!region || region === current) return;
  current = region;
  map.setStyle(styleFor(region));
  map.setMaxZoom(Math.max(16, (region.maxzoom || 14) + 3));
  status(region.title);
}
map.on("style.load", addOverlays);
map.on("moveend", () => {
  const c = map.getCenter();
  switchRegion(regionFor(c.lng, c.lat));
  if ($("l-wiki").checked) loadWiki();
});

// ---- position, mesh, spots ------------------------------------------------------------
function loadPosition() {
  api("position").then((d) => {
    me = d.fix;
    setOverlay("me", me ? pointFC([{ lat: me.lat, lon: me.lon, name: "Me" }]) : emptyFC());
  }).catch(() => {});
}
function loadMesh() {
  api("mesh").then((d) => {
    setOverlay("mesh", pointFC(d.nodes.map((n) => ({ lat: n.lat, lon: n.lon, name: n.long_name || n.id, kind: "mesh" }))));
    setOverlay("waypoints", pointFC(d.waypoints.map((w) => ({ ...w, kind: "waypoint" }))));
  }).catch(() => {});
}
function loadSpots() {
  if (!$("l-ft8").checked) return;
  api("spots").then((d) => setOverlay("ft8", pointFC(d.spots.map((s) => ({ lat: s.lat, lon: s.lon, name: s.call, snr: s.snr, kind: "ft8" }))))).catch(() => {});
}
function loadWiki() {
  const c = map.getCenter();
  const radius = Math.min(50000, 40000000 / Math.pow(2, map.getZoom()));
  api(`nearby?lat=${c.lat}&lon=${c.lng}&radius=${radius}`).then((d) => {
    setOverlay("wiki", pointFC(d.results.map((r) => ({ lat: r.lat, lon: r.lon, name: r.name, url: r.url, kind: "wiki" }))));
  }).catch(() => {});
}
loadPosition(); loadMesh();
setInterval(loadPosition, 5000);
setInterval(loadMesh, 15000);
setInterval(loadSpots, 60000);
for (const id of ["l-mesh", "l-wiki", "l-ft8"]) $(id).addEventListener("change", () => {
  applyLayerToggles();
  if (id === "l-wiki" && $(id).checked) loadWiki();
  if (id === "l-ft8" && $(id).checked) loadSpots();
});

// ---- clicking features ----------------------------------------------------------------
for (const layer of ["wiki", "mesh", "waypoints", "ft8"]) {
  map.on("click", layer, (e) => {
    const p = e.features[0].properties;
    let html = `<b>${esc(p.name)}</b>`;
    if (p.kind === "wiki" && p.url && p.url !== "null") html += `<br><a href="${esc(p.url)}" target="_blank">Read article</a>`;
    if (p.kind === "waypoint") html += `<br>${esc(p.description || "")}<br><button onclick="deleteWaypoint(${Number(p.id)})">Delete</button>`;
    if (p.kind === "ft8") html += `<br>FT8 · ${esc(p.snr)} dB`;
    new maplibregl.Popup().setLngLat(e.lngLat).setHTML(html).addTo(map);
    e.preventDefault();
  });
  map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
}

map.on("click", (e) => {
  if (e.defaultPrevented) return;
  if (pinMode) {
    pinMode = false;
    $("pin").classList.remove("on");
    const name = prompt("Waypoint name (e.g. Water, Shelter, Cache):");
    if (!name) return;
    const share = confirm("Share this waypoint over the mesh?\n(Only works while mesh transmit is on.)");
    api("waypoint", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, lat: e.lngLat.lat, lon: e.lngLat.lng, share }) })
      .then((d) => { if (d.error) alert(d.error); loadMesh(); });
    return;
  }
  selected = { lat: e.lngLat.lat, lon: e.lngLat.lng, name: `${e.lngLat.lat.toFixed(5)}, ${e.lngLat.lng.toFixed(5)}` };
  showSelected();
});

window.deleteWaypoint = (id) => {
  fetch("/api/waypoint?id=" + id, { method: "DELETE" }).then(loadMesh);
};

function showSelected() {
  if (!selected) return;
  let html = `<b>${esc(selected.name)}</b><br>${selected.lat.toFixed(5)}, ${selected.lon.toFixed(5)}`;
  if (me) {
    const km = haversineKm(me.lat, me.lon, selected.lat, selected.lon);
    html += `<br>${km.toFixed(1)} km from you`;
  }
  $("info").innerHTML = html;
}

function haversineKm(a, b, c, d) {
  const r = (x) => (x * Math.PI) / 180;
  const h = Math.sin(r(c - a) / 2) ** 2 + Math.cos(r(a)) * Math.cos(r(c)) * Math.sin(r(d - b) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
}

// ---- search --------------------------------------------------------------------------------
let searchTimer = null;
let results = [];
let sel = -1;
$("q").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, 300);
});
$("q").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { sel = Math.min(results.length - 1, sel + 1); drawResults(); e.preventDefault(); }
  else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); drawResults(); e.preventDefault(); }
  else if (e.key === "Enter" && results.length) { choose(results[Math.max(0, sel)]); }
  else if (e.key === "Escape") { $("q").value = ""; results = []; drawResults(); $("q").blur(); }
});
function runSearch() {
  const q = $("q").value.trim();
  if (q.length < 2) { results = []; drawResults(); return; }
  const c = me || { lat: map.getCenter().lat, lon: map.getCenter().lng };
  api(`search?q=${encodeURIComponent(q)}&lat=${c.lat}&lon=${c.lon}`).then((d) => {
    if (d.error) status(d.error);
    results = d.results || []; sel = results.length ? 0 : -1; drawResults();
  });
}
function drawResults() {
  $("results").innerHTML = results.map((r, i) =>
    `<div class="${i === sel ? "sel" : ""}" data-i="${i}">${esc(r.name)} <small>${esc(r.kind)} ${esc(r.extra)}</small></div>`).join("");
  for (const el of $("results").children) el.onclick = () => choose(results[Number(el.dataset.i)]);
}
function choose(r) {
  selected = { lat: r.lat, lon: r.lon, name: r.name };
  results = []; drawResults();
  map.flyTo({ center: [r.lon, r.lat], zoom: r.kind === "city" ? 11 : r.kind === "town" ? 13 : 15 });
  showSelected();
}

// ---- routing --------------------------------------------------------------------------------
function route() {
  if (!me) { status("No GPS fix: can't route from your position yet."); return; }
  if (!selected) { status("Pick a destination first (search or click the map)."); return; }
  status("Routing…");
  api(`route?from=${me.lat},${me.lon}&to=${selected.lat},${selected.lon}&mode=${$("mode").value}`).then((d) => {
    if (d.error) { status(d.error); return; }
    setOverlay("route", { type: "FeatureCollection", features: [{ type: "Feature", geometry: d.geometry, properties: {} }] });
    const steps = d.steps.map((s) => `<li>${esc(s.text)} <small>${s.km.toFixed(2)} km</small></li>`).join("");
    $("info").innerHTML = `<b>${d.km.toFixed(1)} km · ${d.minutes} min</b><ol>${steps}</ol>`;
    status("Route ready");
  });
}

$("me").onclick = () => { if (me) map.flyTo({ center: [me.lon, me.lat], zoom: 15 }); else status("No GPS fix yet."); };
$("route").onclick = route;
$("pin").onclick = () => { pinMode = !pinMode; $("pin").classList.toggle("on", pinMode); status(pinMode ? "Click the map to place a waypoint" : ""); };

document.addEventListener("keydown", (e) => {
  if (document.activeElement === $("q")) return;
  if (e.key === "/") { $("q").focus(); e.preventDefault(); }
  else if (e.key === "c") $("me").click();
  else if (e.key === "r") route();
  else if (e.key === "w") $("pin").click();
});
