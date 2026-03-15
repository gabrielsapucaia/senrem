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
let layersData = [];
let pollInterval = null;
let selectedLayerId = null;
let layerProps = {};
let layerStats = {};

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
    setupPropertiesPanel();
    await refreshLayersList();
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

async function refreshLayersList() {
    const list = document.getElementById("layers-list");
    const resp = await fetch("/api/layers").then(r => r.json());
    const layers = resp.layers;
    const isLoading = resp.loading;

    // Atualizar status de carregamento
    if (isLoading) {
        updateStatus(`Carregando layers GEE... ${resp.loaded}/${resp.total}`);
        startPolling();
    } else if (pollInterval) {
        stopPolling();
        updateStatus("Pronto");
    }

    // Se lista ja existe, apenas atualizar estados
    if (list.children.length > 0) {
        layers.forEach(layer => {
            const checkbox = document.getElementById(`layer-${layer.id}`);
            if (checkbox && !checkbox.checked) {
                checkbox.disabled = !layer.can_generate && !layer.available;
            }
        });
        layersData = layers;
        return;
    }

    // Primeira renderizacao: criar elementos
    layersData = layers;
    let currentGroup = null;

    // Botao refresh no topo
    const refreshBtn = document.createElement("button");
    refreshBtn.className = "refresh-btn";
    refreshBtn.textContent = "Atualizar Layers";
    refreshBtn.onclick = async () => {
        refreshBtn.disabled = true;
        refreshBtn.textContent = "Atualizando...";
        await fetch("/api/layers/refresh", { method: "POST" });
        startPolling();
    };
    list.appendChild(refreshBtn);

    layers.forEach(layer => {
        if (layer.group && layer.group !== currentGroup) {
            currentGroup = layer.group;
            const header = document.createElement("div");
            header.className = "layer-group-header";
            header.textContent = currentGroup;
            list.appendChild(header);
        }

        const item = document.createElement("div");
        item.className = "layer-item";

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.id = `layer-${layer.id}`;
        checkbox.disabled = !layer.can_generate && !layer.available;

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

        label.addEventListener("click", (e) => {
            if (checkbox.checked) {
                e.preventDefault();
                openPropertiesPanel(layer.id);
            }
        });

        if (layer.available) {
            label.classList.add("layer-ready");
        }

        item.appendChild(checkbox);
        item.appendChild(label);
        list.appendChild(item);
    });
}

function startPolling() {
    if (pollInterval) return;
    pollInterval = setInterval(async () => {
        await refreshLayersList();
    }, 3000);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
    // Re-habilitar botao refresh
    const btn = document.querySelector(".refresh-btn");
    if (btn) {
        btn.disabled = false;
        btn.textContent = "Atualizar Layers";
    }
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
                "raster-opacity": 0.7
            }
        }, "study-area-fill");

        activeLayers[layerId] = sourceId;
        if (!layerProps[layerId]) {
            layerProps[layerId] = getDefaultProps();
        }
        applyMapLibreProps(layerId);
        updateStatus(`${data.name} carregada`);
    } catch (err) {
        checkbox.checked = false;
        updateStatus(`Erro: ${err.message}`);
    }
}

function disableLayer(layerId) {
    if (selectedLayerId === layerId) {
        closePropertiesPanel();
    }
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

function getDefaultProps() {
    return {
        opacity: 70,
        brightnessMin: 0,
        brightnessMax: 100,
        contrast: 0,
        saturation: 0,
        colormap: "viridis",
        vmin: null,
        vmax: null,
    };
}

async function openPropertiesPanel(layerId) {
    if (!activeLayers[layerId]) return;

    selectedLayerId = layerId;
    if (!layerProps[layerId]) {
        layerProps[layerId] = getDefaultProps();
    }

    const layer = layersData.find(l => l.id === layerId);
    const supportsColormap = layer && layer.supports_colormap;

    document.getElementById("props-layer-name").textContent = layer ? layer.name : layerId;

    if (supportsColormap && !layerStats[layerId]) {
        try {
            const resp = await fetch(`/api/tiles/${layerId}/stats`);
            if (resp.ok) {
                layerStats[layerId] = await resp.json();
            }
        } catch (e) { /* ignore */ }
    }

    const p = layerProps[layerId];
    document.getElementById("prop-opacity").value = p.opacity;
    document.getElementById("prop-opacity-val").textContent = p.opacity + "%";
    document.getElementById("prop-brightness-min").value = p.brightnessMin;
    document.getElementById("prop-brightness-min-val").textContent = (p.brightnessMin / 100).toFixed(2);
    document.getElementById("prop-brightness-max").value = p.brightnessMax;
    document.getElementById("prop-brightness-max-val").textContent = (p.brightnessMax / 100).toFixed(2);
    document.getElementById("prop-contrast").value = p.contrast;
    document.getElementById("prop-contrast-val").textContent = (p.contrast / 100).toFixed(2);
    document.getElementById("prop-saturation").value = p.saturation;
    document.getElementById("prop-saturation-val").textContent = (p.saturation / 100).toFixed(2);

    const localControls = document.getElementById("props-local-controls");
    if (supportsColormap) {
        localControls.style.display = "block";
        document.getElementById("prop-colormap").value = p.colormap;

        const stats = layerStats[layerId];
        if (stats) {
            const range = stats.p98 - stats.p2;
            const sliderMin = Math.floor((stats.p2 - range) * 100);
            const sliderMax = Math.ceil((stats.p98 + range) * 100);
            const vminSlider = document.getElementById("prop-vmin");
            const vmaxSlider = document.getElementById("prop-vmax");
            vminSlider.min = sliderMin;
            vminSlider.max = sliderMax;
            vmaxSlider.min = sliderMin;
            vmaxSlider.max = sliderMax;
            vminSlider.value = p.vmin !== null ? Math.round(p.vmin * 100) : Math.round(stats.p2 * 100);
            vmaxSlider.value = p.vmax !== null ? Math.round(p.vmax * 100) : Math.round(stats.p98 * 100);
            document.getElementById("prop-vmin-val").textContent = (parseInt(vminSlider.value) / 100).toFixed(2);
            document.getElementById("prop-vmax-val").textContent = (parseInt(vmaxSlider.value) / 100).toFixed(2);
        }
    } else {
        localControls.style.display = "none";
    }

    document.getElementById("properties-panel").classList.add("open");
}

function closePropertiesPanel() {
    selectedLayerId = null;
    document.getElementById("properties-panel").classList.remove("open");
}

function applyMapLibreProps(layerId) {
    const sourceId = `layer-${layerId}`;
    const p = layerProps[layerId];
    if (!p || !map.getLayer(sourceId)) return;

    map.setPaintProperty(sourceId, "raster-opacity", p.opacity / 100);
    map.setPaintProperty(sourceId, "raster-brightness-min", p.brightnessMin / 100);
    map.setPaintProperty(sourceId, "raster-brightness-max", p.brightnessMax / 100);
    map.setPaintProperty(sourceId, "raster-contrast", p.contrast / 100);
    map.setPaintProperty(sourceId, "raster-saturation", p.saturation / 100);
}

function rebuildTileUrl(layerId) {
    const p = layerProps[layerId];
    if (!p) return;
    const sourceId = `layer-${layerId}`;
    const source = map.getSource(sourceId);
    if (!source) return;

    const stats = layerStats[layerId];
    const vmin = p.vmin !== null ? p.vmin : (stats ? stats.p2 : null);
    const vmax = p.vmax !== null ? p.vmax : (stats ? stats.p98 : null);

    let url = `/api/tiles/${layerId}/{z}/{x}/{y}.png?colormap=${p.colormap}`;
    if (vmin !== null) url += `&vmin=${vmin}`;
    if (vmax !== null) url += `&vmax=${vmax}`;

    source.setTiles([url]);
}

function setupPropertiesPanel() {
    document.getElementById("props-close").addEventListener("click", closePropertiesPanel);

    const sliderConfigs = [
        { id: "prop-opacity", valId: "prop-opacity-val", prop: "opacity", format: v => v + "%" },
        { id: "prop-brightness-min", valId: "prop-brightness-min-val", prop: "brightnessMin", format: v => (v / 100).toFixed(2) },
        { id: "prop-brightness-max", valId: "prop-brightness-max-val", prop: "brightnessMax", format: v => (v / 100).toFixed(2) },
        { id: "prop-contrast", valId: "prop-contrast-val", prop: "contrast", format: v => (v / 100).toFixed(2) },
        { id: "prop-saturation", valId: "prop-saturation-val", prop: "saturation", format: v => (v / 100).toFixed(2) },
    ];

    sliderConfigs.forEach(({ id, valId, prop, format }) => {
        const slider = document.getElementById(id);
        slider.addEventListener("input", () => {
            const val = parseInt(slider.value);
            document.getElementById(valId).textContent = format(val);
            if (selectedLayerId && layerProps[selectedLayerId]) {
                layerProps[selectedLayerId][prop] = val;
                applyMapLibreProps(selectedLayerId);
            }
        });
    });

    // Colormap
    const cmSelect = document.getElementById("prop-colormap");
    cmSelect.addEventListener("change", () => {
        if (selectedLayerId && layerProps[selectedLayerId]) {
            layerProps[selectedLayerId].colormap = cmSelect.value;
            rebuildTileUrl(selectedLayerId);
        }
    });

    // Vmin/Vmax
    ["prop-vmin", "prop-vmax"].forEach(id => {
        const slider = document.getElementById(id);
        const valSpan = document.getElementById(id + "-val");
        const prop = id === "prop-vmin" ? "vmin" : "vmax";
        slider.addEventListener("input", () => {
            const val = parseInt(slider.value) / 100;
            valSpan.textContent = val.toFixed(2);
            if (selectedLayerId && layerProps[selectedLayerId]) {
                layerProps[selectedLayerId][prop] = val;
                rebuildTileUrl(selectedLayerId);
            }
        });
    });
}

function updateStatus(text) {
    document.getElementById("status-text").textContent = "Status: " + text;
}

init();
