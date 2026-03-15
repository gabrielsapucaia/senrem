const BASEMAPS = {
    satellite: {
        name: "Satelite",
        style: {
            version: 8,
            sources: {
                esri: {
                    type: "raster",
                    tiles: [
                        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                    ],
                    tileSize: 256,
                    attribution: "Esri"
                }
            },
            layers: [{ id: "esri-satellite", type: "raster", source: "esri" }]
        }
    },
    topo: {
        name: "Topo",
        style: "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json"
    },
    dark: {
        name: "Escuro",
        style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
    }
};

let map;
let studyArea = null;
let currentBasemap = "satellite";
let activeLayers = {};

async function init() {
    const config = await fetch("/api/config").then(r => r.json());
    studyArea = config;

    map = new maplibregl.Map({
        container: "map",
        style: BASEMAPS[currentBasemap].style,
        center: [config.center.lon, config.center.lat],
        zoom: 11
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

    map.on("load", () => {
        addStudyAreaCircle(config);
        updateStatus("Pronto");
    });

    map.on("mousemove", (e) => {
        const coords = e.lngLat;
        document.getElementById("cursor-coords").textContent =
            `${coords.lat.toFixed(5)}, ${coords.lng.toFixed(5)}`;
    });

    setupBasemapSwitcher();
    setupOpacitySlider();
    await setupLayersList();
}

function addStudyAreaCircle(config) {
    const center = [config.center.lon, config.center.lat];
    const radiusKm = config.radius_km;
    const points = 64;
    const coords = [];

    for (let i = 0; i <= points; i++) {
        const angle = (i / points) * 2 * Math.PI;
        const dx = radiusKm * Math.cos(angle);
        const dy = radiusKm * Math.sin(angle);
        const lat = center[1] + (dy / 111.32);
        const lon = center[0] + (dx / (111.32 * Math.cos(center[1] * Math.PI / 180)));
        coords.push([lon, lat]);
    }

    map.addSource("study-area", {
        type: "geojson",
        data: {
            type: "Feature",
            geometry: { type: "Polygon", coordinates: [coords] }
        }
    });

    map.addLayer({
        id: "study-area-fill",
        type: "fill",
        source: "study-area",
        paint: {
            "fill-color": "#e94560",
            "fill-opacity": 0.05
        }
    });

    map.addLayer({
        id: "study-area-outline",
        type: "line",
        source: "study-area",
        paint: {
            "line-color": "#e94560",
            "line-width": 2,
            "line-dasharray": [3, 2]
        }
    });

    new maplibregl.Marker({ color: "#e94560" })
        .setLngLat(center)
        .setPopup(new maplibregl.Popup().setHTML(
            `<strong>${config.name}</strong><br>` +
            `${config.center.lat}, ${config.center.lon}<br>` +
            `Raio: ${config.radius_km} km`
        ))
        .addTo(map);
}

function setupBasemapSwitcher() {
    const container = document.createElement("div");
    container.className = "basemap-switcher";

    Object.entries(BASEMAPS).forEach(([key, val]) => {
        const btn = document.createElement("button");
        btn.className = "basemap-btn" + (key === currentBasemap ? " active" : "");
        btn.textContent = val.name;
        btn.onclick = () => {
            currentBasemap = key;
            map.setStyle(val.style);
            map.once("style.load", () => {
                if (studyArea) addStudyAreaCircle(studyArea);
                Object.keys(activeLayers).forEach(layerId => {
                    const checkbox = document.getElementById(`layer-${layerId}`);
                    if (checkbox && checkbox.checked) {
                        enableLayer(layerId, checkbox);
                    }
                });
            });
            container.querySelectorAll(".basemap-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
        };
        container.appendChild(btn);
    });

    const layersPanel = document.getElementById("layers-panel");
    layersPanel.insertBefore(container, layersPanel.querySelector("#layers-list"));
}

async function setupLayersList() {
    const list = document.getElementById("layers-list");
    const layers = await fetch("/api/layers").then(r => r.json());

    layers.forEach(layer => {
        const item = document.createElement("div");
        item.className = "layer-item";

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.id = `layer-${layer.id}`;
        checkbox.disabled = !layer.can_generate;

        checkbox.addEventListener("change", async () => {
            if (checkbox.checked) {
                await enableLayer(layer.id, checkbox);
            } else {
                disableLayer(layer.id);
            }
        });

        const label = document.createElement("label");
        label.htmlFor = `layer-${layer.id}`;
        label.textContent = layer.name;

        item.appendChild(checkbox);
        item.appendChild(label);
        list.appendChild(item);
    });
}

async function enableLayer(layerId, checkbox) {
    updateStatus(`Gerando ${layerId}...`);
    try {
        const data = await fetch(`/api/layers/${layerId}/generate`, { method: "POST" })
            .then(r => {
                if (!r.ok) throw new Error(`Erro ${r.status}`);
                return r.json();
            });

        const sourceId = `layer-${layerId}`;

        if (map.getSource(sourceId)) {
            map.removeLayer(sourceId);
            map.removeSource(sourceId);
        }

        map.addSource(sourceId, {
            type: "raster",
            tiles: [data.tile_url],
            tileSize: 256
        });

        map.addLayer({
            id: sourceId,
            type: "raster",
            source: sourceId,
            paint: {
                "raster-opacity": parseInt(document.getElementById("opacity-slider").value) / 100
            }
        }, "study-area-fill");

        activeLayers[layerId] = sourceId;
        updateStatus(`${data.name} carregada`);
    } catch (err) {
        checkbox.checked = false;
        updateStatus(`Erro: ${err.message}`);
    }
}

function disableLayer(layerId) {
    const sourceId = `layer-${layerId}`;
    if (map.getLayer(sourceId)) {
        map.removeLayer(sourceId);
    }
    if (map.getSource(sourceId)) {
        map.removeSource(sourceId);
    }
    delete activeLayers[layerId];
    updateStatus("Pronto");
}

function setupOpacitySlider() {
    const slider = document.getElementById("opacity-slider");
    const value = document.getElementById("opacity-value");
    slider.addEventListener("input", () => {
        const opacity = parseInt(slider.value) / 100;
        value.textContent = slider.value + "%";
        Object.values(activeLayers).forEach(sourceId => {
            if (map.getLayer(sourceId)) {
                map.setPaintProperty(sourceId, "raster-opacity", opacity);
            }
        });
    });
}

function updateStatus(text) {
    document.getElementById("status-text").textContent = "Status: " + text;
}

init();
