const BASEMAP_STYLE = {
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
};

let map;
let studyArea = null;
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
        style: BASEMAP_STYLE,
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

async function refreshLayersList() {
    const list = document.getElementById("layers-list");
    const resp = await fetch("/api/layers").then(r => r.json());
    const layers = resp.layers;
    const isLoading = resp.loading;

    if (isLoading) {
        updateStatus(`Carregando layers GEE... ${resp.loaded}/${resp.total}`);
        startPolling();
    } else if (pollInterval) {
        stopPolling();
        updateStatus("Pronto");
    }

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

    layersData = layers;
    let currentGroup = null;

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

    // Botoes selecionar/deselecionar todos
    const toggleDiv = document.createElement("div");
    toggleDiv.className = "toggle-all";
    const selectAllBtn = document.createElement("button");
    selectAllBtn.className = "toggle-btn";
    selectAllBtn.textContent = "Ativar todas";
    selectAllBtn.onclick = async () => {
        for (const layer of layersData) {
            const cb = document.getElementById(`layer-${layer.id}`);
            if (cb && !cb.checked && !cb.disabled) {
                cb.checked = true;
                await enableLayer(layer.id, cb);
            }
        }
    };
    const deselectAllBtn = document.createElement("button");
    deselectAllBtn.className = "toggle-btn";
    deselectAllBtn.textContent = "Desativar todas";
    deselectAllBtn.onclick = () => {
        for (const layerId of Object.keys(activeLayers)) {
            const cb = document.getElementById(`layer-${layerId}`);
            if (cb) cb.checked = false;
            disableLayer(layerId);
        }
    };
    toggleDiv.appendChild(selectAllBtn);
    toggleDiv.appendChild(deselectAllBtn);
    list.appendChild(toggleDiv);

    // Basemap como layer especial
    const basemapHeader = document.createElement("div");
    basemapHeader.className = "layer-group-header";
    basemapHeader.textContent = "Basemap";
    list.appendChild(basemapHeader);

    const basemapItem = document.createElement("div");
    basemapItem.className = "layer-item";
    basemapItem.id = "layer-item-basemap";
    const basemapLabel = document.createElement("label");
    basemapLabel.textContent = "Satelite";
    basemapLabel.style.cursor = "pointer";
    basemapLabel.addEventListener("click", () => {
        if (selectedLayerId === "basemap") {
            selectedLayerId = null;
            showEmptyProperties();
        } else {
            selectBasemap();
        }
    });
    basemapItem.appendChild(basemapLabel);
    list.appendChild(basemapItem);

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
        item.id = `layer-item-${layer.id}`;

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
                if (selectedLayerId === layer.id) {
                    selectedLayerId = null;
                    showEmptyProperties();
                } else {
                    selectLayer(layer.id);
                }
            }
        });

        if (layer.available) {
            label.classList.add("layer-ready");
        }

        item.appendChild(checkbox);
        item.appendChild(label);
        list.appendChild(item);

        if (layer.id === "mining-available") {
            const legend = document.createElement("div");
            legend.className = "vector-legend";
            legend.id = `legend-${layer.id}`;
            legend.style.display = "none";
            legend.innerHTML = `
                <span class="legend-item"><span class="legend-swatch" style="background:#FF4444;border-color:#FF4444"></span>Ouro</span>
                <span class="legend-item"><span class="legend-swatch" style="background:#8B8B8B;border-color:#8B8B8B"></span>Outros</span>
            `;
            list.appendChild(legend);

            checkbox.addEventListener("change", () => {
                legend.style.display = checkbox.checked ? "flex" : "none";
            });
        }

        if (layer.id === "mining-rights") {
            const legend = document.createElement("div");
            legend.className = "vector-legend";
            legend.id = `legend-${layer.id}`;
            legend.style.display = "none";
            legend.innerHTML = `
                <span class="legend-item"><span class="legend-swatch" style="background:#FFD700;border-color:#FFD700"></span>Aura Minerals</span>
                <span class="legend-item"><span class="legend-swatch" style="background:#888888;border-color:#888888"></span>Outros</span>
            `;
            list.appendChild(legend);

            checkbox.addEventListener("change", () => {
                legend.style.display = checkbox.checked ? "flex" : "none";
            });
        }
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

        if (data.type === "vector") {
            await enableVectorLayer(layerId, data);
        } else {
            enableRasterLayer(layerId, data);
        }

        if (!layerProps[layerId]) {
            layerProps[layerId] = getDefaultProps();
        }
        applyMapLibreProps(layerId);
        selectLayer(layerId);
        updateStatus(`${data.name} carregada`);
    } catch (err) {
        checkbox.checked = false;
        updateStatus(`Erro: ${err.message}`);
    }
}

function enableRasterLayer(layerId, data) {
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
}

async function enableVectorLayer(layerId, data) {
    const sourceId = `layer-${layerId}`;
    const geojson = await fetch(data.vector_url).then(r => r.json());

    if (map.getSource(sourceId)) {
        disableVectorLayers(layerId);
    }

    map.addSource(sourceId, { type: "geojson", data: geojson });

    if (layerId === "mining-rights") {
        enableMiningRightsLayers(sourceId);
    } else if (layerId === "mining-available") {
        enableMiningAvailableLayers(sourceId);
    } else if (layerId === "mineral-occurrences") {
        enableOccurrenceLayers(sourceId);
    } else {
        // Geology layers (litho, age) — polygons with per-feature color
        enableGeologyLayers(sourceId);
    }

    activeLayers[layerId] = sourceId;
}

function enableMiningRightsLayers(sourceId) {
    map.addLayer({
        id: `${sourceId}-other-fill`, type: "fill", source: sourceId,
        filter: ["==", ["get", "is_aura"], false],
        paint: { "fill-color": "#888888", "fill-opacity": 0.25 }
    }, "study-area-fill");
    map.addLayer({
        id: `${sourceId}-other-line`, type: "line", source: sourceId,
        filter: ["==", ["get", "is_aura"], false],
        paint: { "line-color": "#888888", "line-width": 1.5 }
    }, "study-area-fill");
    map.addLayer({
        id: `${sourceId}-aura-fill`, type: "fill", source: sourceId,
        filter: ["==", ["get", "is_aura"], true],
        paint: { "fill-color": "#FFD700", "fill-opacity": 0.35 }
    }, "study-area-fill");
    map.addLayer({
        id: `${sourceId}-aura-line`, type: "line", source: sourceId,
        filter: ["==", ["get", "is_aura"], true],
        paint: { "line-color": "#FFD700", "line-width": 2 }
    }, "study-area-fill");

    addPopup(sourceId, ["-aura-fill", "-other-fill"], (props) => `
        <div style="color:#1a1a2e;font-size:13px;max-width:260px">
            <strong>${props.PROCESSO || ""}</strong><br>
            <b>Titular:</b> ${props.NOME || ""}<br>
            <b>Fase:</b> ${props.FASE || ""}<br>
            <b>Substancia:</b> ${props.SUBS || ""}<br>
            <b>Area:</b> ${props.AREA_HA ? Number(props.AREA_HA).toFixed(1) + " ha" : ""}
        </div>
    `);
}

function enableMiningAvailableLayers(sourceId) {
    // Outros minerais — cinza claro
    map.addLayer({
        id: `${sourceId}-other-fill`, type: "fill", source: sourceId,
        filter: ["==", ["get", "is_ouro"], false],
        paint: { "fill-color": "#8B8B8B", "fill-opacity": 0.2 }
    }, "study-area-fill");
    map.addLayer({
        id: `${sourceId}-other-line`, type: "line", source: sourceId,
        filter: ["==", ["get", "is_ouro"], false],
        paint: { "line-color": "#8B8B8B", "line-width": 1, "line-dasharray": [2, 1] }
    }, "study-area-fill");
    // Ouro — vermelho/coral
    map.addLayer({
        id: `${sourceId}-aura-fill`, type: "fill", source: sourceId,
        filter: ["==", ["get", "is_ouro"], true],
        paint: { "fill-color": "#FF4444", "fill-opacity": 0.3 }
    }, "study-area-fill");
    map.addLayer({
        id: `${sourceId}-aura-line`, type: "line", source: sourceId,
        filter: ["==", ["get", "is_ouro"], true],
        paint: { "line-color": "#FF4444", "line-width": 2 }
    }, "study-area-fill");

    addPopup(sourceId, ["-aura-fill", "-other-fill"], (props) => `
        <div style="color:#1a1a2e;font-size:13px;max-width:280px">
            <strong>${props.PROCESSO || ""}</strong><br>
            <b>Titular:</b> ${props.NOME || ""}<br>
            <b>Fase:</b> ${props.FASE || ""}<br>
            <b>Substancia:</b> ${props.SUBS || ""}<br>
            <b>Area:</b> ${props.AREA_HA ? Number(props.AREA_HA).toFixed(1) + " ha" : ""}
        </div>
    `);
}

function enableGeologyLayers(sourceId) {
    map.addLayer({
        id: `${sourceId}-fill`, type: "fill", source: sourceId,
        paint: { "fill-color": ["get", "color"], "fill-opacity": 0.4 }
    }, "study-area-fill");
    map.addLayer({
        id: `${sourceId}-line`, type: "line", source: sourceId,
        paint: { "line-color": ["get", "color"], "line-width": 1, "line-opacity": 0.8 }
    }, "study-area-fill");

    addPopup(sourceId, ["-fill"], (props) => `
        <div style="color:#1a1a2e;font-size:13px;max-width:280px">
            <strong>${props.sigla || ""}</strong><br>
            <b>${props.nome || ""}</b><br>
            <em>${props.litotipos || ""}</em><br>
            ${props.era_max ? `<b>Idade:</b> ${props.era_max}` : ""}
        </div>
    `);
}

function enableOccurrenceLayers(sourceId) {
    map.addLayer({
        id: `${sourceId}-circle`, type: "circle", source: sourceId,
        paint: {
            "circle-radius": ["get", "radius"],
            "circle-color": ["get", "color"],
            "circle-stroke-color": "#fff",
            "circle-stroke-width": 1,
            "circle-opacity": 0.9,
        }
    }, "study-area-fill");

    addPopup(sourceId, ["-circle"], (props) => `
        <div style="color:#1a1a2e;font-size:13px;max-width:260px">
            <strong>${props.substancias || props.substancia || "?"}</strong><br>
            ${props.toponimia || ""}<br>
            ${props.status_economico || ""} — ${props.importancia || ""}
        </div>
    `);
}

function addPopup(sourceId, suffixes, htmlFn) {
    suffixes.forEach(s => {
        const lid = sourceId + s;
        map.on("click", lid, (e) => {
            if (!e.features || !e.features.length) return;
            const props = e.features[0].properties;
            new maplibregl.Popup()
                .setLngLat(e.lngLat)
                .setHTML(htmlFn(props))
                .addTo(map);
        });
        map.on("mouseenter", lid, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", lid, () => { map.getCanvas().style.cursor = ""; });
    });
}

function disableVectorLayers(layerId) {
    const sourceId = `layer-${layerId}`;
    const suffixes = ["-fill", "-line", "-circle", "-aura-fill", "-aura-line", "-other-fill", "-other-line"];
    suffixes.forEach(s => {
        if (map.getLayer(sourceId + s)) map.removeLayer(sourceId + s);
    });
    if (map.getSource(sourceId)) map.removeSource(sourceId);
}

function disableLayer(layerId) {
    const sourceId = `layer-${layerId}`;
    const layer = layersData.find(l => l.id === layerId);

    if (layer && layer.type === "vector") {
        disableVectorLayers(layerId);
    } else {
        if (map.getLayer(sourceId)) map.removeLayer(sourceId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
    }
    delete activeLayers[layerId];

    // Se era a layer selecionada, selecionar outra ativa ou limpar
    if (selectedLayerId === layerId) {
        const remaining = Object.keys(activeLayers);
        if (remaining.length > 0) {
            selectLayer(remaining[remaining.length - 1]);
        } else {
            selectedLayerId = null;
            showEmptyProperties();
        }
    }

    updateStatus("Pronto");
}

function getDefaultProps() {
    return {
        opacity: 70,
        brightness: 100,
        contrast: 0,
        saturation: 0,
        colormap: "viridis",
        vmin: null,
        vmax: null,
    };
}

function selectLayer(layerId) {
    if (!activeLayers[layerId]) return;

    document.querySelectorAll(".layer-item.selected").forEach(el => el.classList.remove("selected"));

    const item = document.getElementById(`layer-item-${layerId}`);
    if (item) item.classList.add("selected");

    openPropertiesPanel(layerId);
}

function selectBasemap() {
    document.querySelectorAll(".layer-item.selected").forEach(el => el.classList.remove("selected"));
    const item = document.getElementById("layer-item-basemap");
    if (item) item.classList.add("selected");

    selectedLayerId = "basemap";
    if (!layerProps["basemap"]) {
        layerProps["basemap"] = getDefaultProps();
    }

    const p = layerProps["basemap"];
    document.getElementById("props-layer-name").textContent = "Satelite";
    document.getElementById("props-content").style.display = "block";
    document.getElementById("props-empty").style.display = "none";
    document.getElementById("prop-opacity").value = p.opacity;
    document.getElementById("prop-opacity-val").textContent = p.opacity + "%";
    document.getElementById("prop-brightness").value = p.brightness;
    document.getElementById("prop-brightness-val").textContent = (p.brightness / 100).toFixed(2);
    document.getElementById("prop-contrast").value = p.contrast;
    document.getElementById("prop-contrast-val").textContent = (p.contrast / 100).toFixed(2);
    document.getElementById("prop-saturation").value = p.saturation;
    document.getElementById("prop-saturation-val").textContent = (p.saturation / 100).toFixed(2);
    document.getElementById("props-local-controls").style.display = "none";
}

async function openPropertiesPanel(layerId) {
    if (!activeLayers[layerId]) return;

    selectedLayerId = layerId;
    if (!layerProps[layerId]) {
        layerProps[layerId] = getDefaultProps();
    }

    const layer = layersData.find(l => l.id === layerId);
    const supportsColormap = layer && layer.supports_colormap;
    const isVector = layer && layer.type === "vector";

    document.getElementById("props-layer-name").textContent = layer ? layer.name : layerId;
    document.getElementById("props-content").style.display = "block";
    document.getElementById("props-empty").style.display = "none";

    // Esconder controles raster-only para layers vetoriais
    ["prop-brightness", "prop-contrast", "prop-saturation"].forEach(id => {
        document.getElementById(id).closest(".prop-group").style.display = isVector ? "none" : "";
    });

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
    document.getElementById("prop-brightness").value = p.brightness;
    document.getElementById("prop-brightness-val").textContent = (p.brightness / 100).toFixed(2);
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
            const absMin = stats.p2 - range;
            const absMax = stats.p98 + range;
            const vmin = p.vmin !== null ? p.vmin : stats.p2;
            const vmax = p.vmax !== null ? p.vmax : stats.p98;
            setRangeSlider("range-slider-cut", vmin, vmax, absMin, absMax);
            document.getElementById("prop-vrange-val").textContent =
                `${vmin.toFixed(2)} — ${vmax.toFixed(2)}`;
        }
    } else {
        localControls.style.display = "none";
    }
}

function showEmptyProperties() {
    document.getElementById("props-layer-name").textContent = "Propriedades";
    document.getElementById("props-content").style.display = "none";
    document.getElementById("props-empty").style.display = "block";
    document.querySelectorAll(".layer-item.selected").forEach(el => el.classList.remove("selected"));
}

function applyMapLibreProps(layerId) {
    const p = layerProps[layerId];
    if (!p) return;

    if (layerId === "basemap") {
        if (map.getLayer("esri-satellite")) {
            map.setPaintProperty("esri-satellite", "raster-opacity", p.opacity / 100);
            map.setPaintProperty("esri-satellite", "raster-brightness-max", p.brightness / 100);
            map.setPaintProperty("esri-satellite", "raster-contrast", p.contrast / 100);
            map.setPaintProperty("esri-satellite", "raster-saturation", p.saturation / 100);
        }
        return;
    }

    const sourceId = `layer-${layerId}`;
    const layer = layersData.find(l => l.id === layerId);

    if (layer && layer.type === "vector") {
        const opacity = p.opacity / 100;
        ["-fill", "-aura-fill", "-other-fill"].forEach(s => {
            if (map.getLayer(sourceId + s))
                map.setPaintProperty(sourceId + s, "fill-opacity", 0.4 * opacity);
        });
        ["-line", "-aura-line", "-other-line"].forEach(s => {
            if (map.getLayer(sourceId + s))
                map.setPaintProperty(sourceId + s, "line-opacity", opacity);
        });
        ["-circle"].forEach(s => {
            if (map.getLayer(sourceId + s))
                map.setPaintProperty(sourceId + s, "circle-opacity", opacity);
        });
        return;
    }

    if (!map.getLayer(sourceId)) return;

    map.setPaintProperty(sourceId, "raster-opacity", p.opacity / 100);
    map.setPaintProperty(sourceId, "raster-brightness-max", p.brightness / 100);
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
    const sliderConfigs = [
        { id: "prop-opacity", valId: "prop-opacity-val", prop: "opacity", format: v => v + "%" },
        { id: "prop-brightness", valId: "prop-brightness-val", prop: "brightness", format: v => (v / 100).toFixed(2) },
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

    // Custom range slider: Corte (vmin/vmax)
    initRangeSlider("range-slider-cut", {
        onUpdate: (lo, hi) => {
            document.getElementById("prop-vrange-val").textContent =
                `${lo.toFixed(2)} — ${hi.toFixed(2)}`;
            if (selectedLayerId && layerProps[selectedLayerId]) {
                layerProps[selectedLayerId].vmin = lo;
                layerProps[selectedLayerId].vmax = hi;
                rebuildTileUrl(selectedLayerId);
            }
        }
    });
}

// Custom range slider com drag de handles e da barra central
const rangeSliders = {};

function initRangeSlider(id, opts) {
    const container = document.getElementById(id);
    const fill = container.querySelector(".range-fill");
    const handleMin = container.querySelector(".range-handle-min");
    const handleMax = container.querySelector(".range-handle-max");

    const state = { min: 0, max: 1, absMin: 0, absMax: 1, onUpdate: opts.onUpdate };
    rangeSliders[id] = state;

    function render() {
        const range = state.absMax - state.absMin;
        if (range <= 0) return;
        const left = ((state.min - state.absMin) / range) * 100;
        const right = ((state.max - state.absMin) / range) * 100;
        handleMin.style.left = left + "%";
        handleMax.style.left = right + "%";
        fill.style.left = left + "%";
        fill.style.width = (right - left) + "%";
    }

    function startDrag(e, type) {
        e.preventDefault();
        const rect = container.getBoundingClientRect();
        const range = state.absMax - state.absMin;
        const startX = e.clientX || e.touches[0].clientX;
        const startMin = state.min;
        const startMax = state.max;
        const span = startMax - startMin;

        function onMove(ev) {
            const x = ev.clientX || ev.touches[0].clientX;
            const dx = ((x - startX) / rect.width) * range;

            if (type === "min") {
                state.min = Math.max(state.absMin, Math.min(state.max - range * 0.01, startMin + dx));
            } else if (type === "max") {
                state.max = Math.min(state.absMax, Math.max(state.min + range * 0.01, startMax + dx));
            } else {
                let newMin = startMin + dx;
                let newMax = startMax + dx;
                if (newMin < state.absMin) { newMin = state.absMin; newMax = state.absMin + span; }
                if (newMax > state.absMax) { newMax = state.absMax; newMin = state.absMax - span; }
                state.min = newMin;
                state.max = newMax;
            }
            render();
            state.onUpdate(state.min, state.max);
        }

        function onUp() {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            document.removeEventListener("touchmove", onMove);
            document.removeEventListener("touchend", onUp);
        }

        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
        document.addEventListener("touchmove", onMove);
        document.addEventListener("touchend", onUp);
    }

    handleMin.addEventListener("mousedown", e => startDrag(e, "min"));
    handleMin.addEventListener("touchstart", e => startDrag(e, "min"));
    handleMax.addEventListener("mousedown", e => startDrag(e, "max"));
    handleMax.addEventListener("touchstart", e => startDrag(e, "max"));
    fill.addEventListener("mousedown", e => startDrag(e, "fill"));
    fill.addEventListener("touchstart", e => startDrag(e, "fill"));

    render();
    return state;
}

function setRangeSlider(id, min, max, absMin, absMax) {
    const state = rangeSliders[id];
    if (!state) return;
    state.absMin = absMin;
    state.absMax = absMax;
    state.min = min;
    state.max = max;
    const container = document.getElementById(id);
    const fill = container.querySelector(".range-fill");
    const handleMin = container.querySelector(".range-handle-min");
    const handleMax = container.querySelector(".range-handle-max");
    const range = absMax - absMin;
    if (range <= 0) return;
    const left = ((min - absMin) / range) * 100;
    const right = ((max - absMin) / range) * 100;
    handleMin.style.left = left + "%";
    handleMax.style.left = right + "%";
    fill.style.left = left + "%";
    fill.style.width = (right - left) + "%";
}

function updateStatus(text) {
    document.getElementById("status-text").textContent = "Status: " + text;
}

init();
