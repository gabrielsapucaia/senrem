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
    setupLayersList();
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
            });
            container.querySelectorAll(".basemap-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
        };
        container.appendChild(btn);
    });

    const layersPanel = document.getElementById("layers-panel");
    layersPanel.insertBefore(container, layersPanel.querySelector("#layers-list"));
}

function setupLayersList() {
    const list = document.getElementById("layers-list");
    const layers = [
        { id: "rgb-true", name: "RGB Verdadeira", available: false },
        { id: "rgb-false", name: "RGB Falsa-cor", available: false },
        { id: "iron-oxide", name: "Oxidos de Ferro", available: false },
        { id: "clay", name: "Argilas / Sericita", available: false },
        { id: "carbonate", name: "Carbonatos", available: false },
        { id: "silica", name: "Silica", available: false },
        { id: "dem", name: "DEM / Hillshade", available: false },
        { id: "lineaments", name: "Lineamentos", available: false },
        { id: "geology", name: "Geologia (CPRM)", available: false },
        { id: "magnetic", name: "Magnetico", available: false },
        { id: "gamma", name: "Gamaespectrometrico", available: false },
        { id: "targets", name: "Alvos", available: false },
    ];

    layers.forEach(layer => {
        const item = document.createElement("div");
        item.className = "layer-item";
        item.innerHTML = `
            <input type="checkbox" id="layer-${layer.id}" disabled>
            <label for="layer-${layer.id}">${layer.name}</label>
        `;
        list.appendChild(item);
    });
}

function setupOpacitySlider() {
    const slider = document.getElementById("opacity-slider");
    const value = document.getElementById("opacity-value");
    slider.addEventListener("input", () => {
        value.textContent = slider.value + "%";
    });
}

function updateStatus(text) {
    document.getElementById("status-text").textContent = "Status: " + text;
}

init();
