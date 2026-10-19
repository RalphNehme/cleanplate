const el = document.getElementById("map");
const city = el.dataset.city;
const form = document.getElementById("filters");

const COLOR = [
  "case",
  ["==", ["get", "s"], null], "#a8a29e",
  ["step", ["get", "s"], "#dc2626", 70, "#d97706", 85, "#65a30d", 90, "#15803d"],
];
const CLUSTER_AVG = ["/", ["get", "sum"], ["max", ["get", "scored"], 1]];

const map = new maplibregl.Map({
  container: el,
  style: "https://tiles.openfreemap.org/styles/positron",
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

async function geojson() {
  const res = await fetch(`/api/${city}/points?${filterParams()}`);
  const rows = await res.json();
  return {
    type: "FeatureCollection",
    features: rows.map(([id, lat, lon, s, f, n]) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [lon, lat] },
      properties: { id, s, f, n },
    })),
  };
}

map.on("load", async () => {
  map.addSource("places", {
    type: "geojson",
    data: await geojson(),
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
      "circle-color": ["step", CLUSTER_AVG, "#dc2626", 70, "#d97706", 85, "#65a30d", 90, "#15803d"],
      "circle-opacity": 0.85,
      "circle-radius": ["step", ["get", "point_count"], 16, 50, 20, 250, 26, 1000, 32],
      "circle-stroke-width": 3,
      "circle-stroke-color": "rgba(255,255,255,0.8)",
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
      "circle-color": COLOR,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 5, 15, 9, 17, 14],
      "circle-stroke-width": 2,
      "circle-stroke-color": "#fff",
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
});

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
