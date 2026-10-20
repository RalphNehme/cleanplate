const el = document.getElementById("map");
const city = el.dataset.city;
const form = document.getElementById("filters");
const dark = window.matchMedia("(prefers-color-scheme: dark)");
const STYLES = {
  light: "https://tiles.openfreemap.org/styles/positron",
  dark: "https://tiles.openfreemap.org/styles/dark",
};

function palette() {
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(`--${name}`).trim();
  return {
    excellent: v("excellent"), good: v("good"), fair: v("fair"), poor: v("poor"), none: v("none"),
    surface: `rgb(${v("surface").split(" ").join(",")})`,
  };
}

function scale(input, p) {
  return ["step", input, p.poor, 70, p.fair, 85, p.good, 90, p.excellent];
}

const map = new maplibregl.Map({
  container: el,
  style: dark.matches ? STYLES.dark : STYLES.light,
  center: [Number(el.dataset.lon), Number(el.dataset.lat)],
  zoom: Number(el.dataset.zoom),
  attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
const geolocate = new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true } });
map.addControl(geolocate, "top-right");

function filterParams() {
  const params = new URLSearchParams();
  for (const name of ["area", "cuisine", "hygiene", "food", "oil"]) {
    const v = form.elements[name]?.value;
    if (v) params.set(name, v);
  }
  return params;
}

let data = { type: "FeatureCollection", features: [] };
async function geojson() {
  const res = await fetch(`/api/${city}/points?${filterParams()}`);
  const rows = await res.json();
  data = {
    type: "FeatureCollection",
    features: rows.map(([id, lat, lon, s, f, n]) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [lon, lat] },
      properties: { id, s, f, n },
    })),
  };
  return data;
}

function addLayers() {
  const p = palette();
  map.addSource("places", {
    type: "geojson",
    data,
    cluster: true,
    clusterMaxZoom: 14,
    clusterRadius: 45,
    clusterProperties: {
      sum: ["+", ["coalesce", ["get", "s"], 0]],
      scored: ["+", ["case", ["==", ["get", "s"], null], 0, 1]],
    },
  });
  map.addLayer({
    id: "clusters",
    type: "circle",
    source: "places",
    filter: ["has", "point_count"],
    paint: {
      "circle-color": scale(["/", ["get", "sum"], ["max", ["get", "scored"], 1]], p),
      "circle-opacity": 0.9,
      "circle-radius": ["step", ["get", "point_count"], 16, 50, 20, 250, 26, 1000, 32],
      "circle-stroke-width": 4,
      "circle-stroke-color": p.surface,
      "circle-stroke-opacity": 0.7,
    },
  });
  map.addLayer({
    id: "cluster-count",
    type: "symbol",
    source: "places",
    filter: ["has", "point_count"],
    layout: {
      "text-field": ["number-format", ["get", "point_count"], { locale: "en-US" }],
      "text-font": ["Noto Sans Bold"],
      "text-size": 12,
    },
    paint: { "text-color": "#fff" },
  });
  map.addLayer({
    id: "points",
    type: "circle",
    source: "places",
    filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-color": ["case", ["==", ["get", "s"], null], p.none, scale(["get", "s"], p)],
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 5, 15, 9, 17, 14],
      "circle-stroke-width": 2,
      "circle-stroke-color": p.surface,
    },
  });
  map.addLayer({
    id: "point-score",
    type: "symbol",
    source: "places",
    filter: ["all", ["!", ["has", "point_count"]], ["!=", ["get", "s"], null]],
    minzoom: 16,
    layout: { "text-field": ["to-string", ["get", "s"]], "text-font": ["Noto Sans Bold"], "text-size": 11 },
    paint: { "text-color": "#fff" },
  });
}

map.on("style.load", addLayers);
map.once("load", async () => {
  map.getSource("places").setData(await geojson());
});
dark.addEventListener("change", (e) => map.setStyle(e.matches ? STYLES.dark : STYLES.light));

map.on("click", "clusters", async (e) => {
  const feature = map.queryRenderedFeatures(e.point, { layers: ["clusters"] })[0];
  const zoom = await map.getSource("places").getClusterExpansionZoom(feature.properties.cluster_id);
  map.easeTo({ center: feature.geometry.coordinates, zoom });
});

const popup = new maplibregl.Popup({ closeButton: false, offset: 12, maxWidth: "260px" });
map.on("click", "points", (e) => {
  const { id, s, f, n } = e.features[0].properties;
  const node = document.createElement("a");
  node.href = `/r/${id}`;
  node.className = "popup";
  const name = document.createElement("strong");
  name.textContent = n;
  const scores = document.createElement("span");
  scores.textContent = `Food ${s ?? "–"} · Hygiene ${f ?? "–"}`;
  node.append(name, scores);
  popup.setLngLat(e.features[0].geometry.coordinates).setDOMContent(node).addTo(map);
});
for (const layer of ["clusters", "points"]) {
  map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
}

async function reload() {
  const source = map.getSource("places");
  if (source) source.setData(await geojson());
}
form.querySelectorAll("select").forEach((s) => s.addEventListener("change", reload));

function searchNear(lat, lon) {
  form.elements.lat.value = lat;
  form.elements.lon.value = lon;
  htmx.trigger(form, "near");
}
geolocate.on("geolocate", ({ coords }) => searchNear(coords.latitude, coords.longitude));
document.getElementById("near").addEventListener("click", () => geolocate.trigger());
