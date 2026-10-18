const map = L.map("map", { preferCanvas: true }).setView([40.73, -73.95], 11);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: 19,
}).addTo(map);

const icons = {};
function icon(grade) {
  const g = ["A", "B", "C"].includes(grade) ? grade : null;
  const key = g || "none";
  return (icons[key] ||= L.divIcon({
    className: "",
    html: `<div class="pin pin-${key.toLowerCase()}">${g || ""}</div>`,
    iconSize: [22, 22],
  }));
}

const escape = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const cluster = L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: 50 });
map.addLayer(cluster);

const form = document.getElementById("filters");
async function loadPoints() {
  const params = new URLSearchParams();
  for (const name of ["borough", "cuisine", "grade"]) {
    const v = form.elements[name].value;
    if (v) params.set(name, v);
  }
  const res = await fetch(`/api/points?${params}`);
  const points = await res.json();
  cluster.clearLayers();
  cluster.addLayers(points.map(([id, lat, lon, grade, name]) =>
    L.marker([lat, lon], { icon: icon(grade) })
      .bindPopup(`<a href="/r/${id}" class="font-semibold">${escape(name)}</a>`)
  ));
}

form.querySelectorAll("select").forEach((s) => s.addEventListener("change", loadPoints));
loadPoints();

document.getElementById("near").addEventListener("click", () => {
  if (!navigator.geolocation) return alert("Location is not available in this browser.");
  navigator.geolocation.getCurrentPosition(
    ({ coords }) => {
      form.elements.lat.value = coords.latitude;
      form.elements.lon.value = coords.longitude;
      map.setView([coords.latitude, coords.longitude], 16);
      L.circleMarker([coords.latitude, coords.longitude], { radius: 7, color: "#0f172a" }).addTo(map);
      htmx.trigger(form, "near");
    },
    () => alert("Couldn't get your location."),
  );
});
