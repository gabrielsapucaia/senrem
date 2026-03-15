# Painel de Propriedades de Layer — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Adicionar segundo sidebar com controles de visualizacao por layer (opacidade, brilho, contraste, saturacao, colormap, min/max).

**Architecture:** Backend recebe query params no endpoint de tiles e expoe stats. Frontend abre painel lateral ao clicar em layer ativa, com sliders que manipulam MapLibre paint properties (instantaneo) ou reconstroem tile URL (recarrega tiles).

**Tech Stack:** FastAPI, rio-tiler, vanilla JS, MapLibre GL JS, CSS

---

### Task 1: Backend — Query params no endpoint de tiles + endpoint de stats

**Files:**
- Modify: `backend/main.py:27-35`
- Test: `tests/test_tile_properties.py`

**Step 1: Write failing tests**

Criar `tests/test_tile_properties.py`:

```python
import numpy as np
import os
import pytest
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from fastapi.testclient import TestClient

from backend.main import app, tile_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def register_test_cog(tmp_path, monkeypatch):
    """Cria um COG temporario e registra no tile_service."""
    cog_path = str(tmp_path / "test-layer.tif")
    data = np.random.rand(1, 256, 256).astype(np.float32)
    transform = from_bounds(-47.4, -11.9, -46.9, -11.5, 256, 256)
    with rasterio.open(
        cog_path, "w", driver="GTiff",
        height=256, width=256, count=1, dtype="float32",
        crs=CRS.from_epsg(4326), transform=transform,
    ) as dst:
        dst.write(data)
    tile_service.register_cog("test-layer", cog_path)
    yield
    if "test-layer" in tile_service._cog_registry:
        del tile_service._cog_registry["test-layer"]
        del tile_service._stats["test-layer"]


def test_tile_with_colormap_param():
    resp = client.get("/api/tiles/test-layer/8/170/127.png?colormap=magma")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


def test_tile_with_vmin_vmax_params():
    resp = client.get("/api/tiles/test-layer/8/170/127.png?vmin=0.1&vmax=0.9")
    assert resp.status_code == 200


def test_tile_stats_endpoint():
    resp = client.get("/api/tiles/test-layer/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "p2" in data
    assert "p98" in data
    assert data["p2"] < data["p98"]


def test_tile_stats_unknown_layer():
    resp = client.get("/api/tiles/unknown-layer/stats")
    assert resp.status_code == 404
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tile_properties.py -v`
Expected: FAIL — endpoint nao aceita query params, endpoint /stats nao existe

**Step 3: Implement backend changes**

Modify `backend/main.py:27-35` — add query params to tile endpoint and new stats endpoint:

```python
from typing import Optional

@app.get("/api/tiles/{layer_id}/{z}/{x}/{y}.png")
def get_tile(layer_id: str, z: int, x: int, y: int,
             colormap: Optional[str] = None,
             vmin: Optional[float] = None,
             vmax: Optional[float] = None):
    try:
        tile_bytes = tile_service.get_tile(
            layer_id, z, x, y,
            colormap=colormap,
            vmin=vmin,
            vmax=vmax,
        )
        return Response(content=tile_bytes, media_type="image/png")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tiles/{layer_id}/stats")
def get_tile_stats(layer_id: str):
    if not tile_service.is_registered(layer_id):
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' nao registrada")
    stats = tile_service._stats.get(layer_id)
    if not stats:
        raise HTTPException(status_code=404, detail=f"Stats nao disponiveis para '{layer_id}'")
    return {"p2": stats[0], "p98": stats[1]}
```

Note: `Optional` import from `typing` must be added at top of `backend/main.py`.

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tile_properties.py -v`
Expected: ALL PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS (34 existing + 4 new = 38)

**Step 6: Commit**

```bash
git add backend/main.py tests/test_tile_properties.py
git commit -m "feat: query params no tile endpoint + endpoint de stats"
```

---

### Task 2: Frontend — HTML do painel de propriedades

**Files:**
- Modify: `frontend/index.html:16-34`

**Step 1: Add properties panel HTML**

Add `#properties-panel` between `#sidebar` and `#map-container` inside `#app-container`:

```html
<div id="app-container">
    <aside id="sidebar">
        <section id="layers-panel">
            <h2>Layers</h2>
            <div id="layers-list"></div>
        </section>

        <section id="opacity-panel">
            <h2>Opacidade</h2>
            <input type="range" id="opacity-slider" min="0" max="100" value="70">
            <span id="opacity-value">70%</span>
        </section>

        <section id="weights-panel">
            <h2>Pesos</h2>
            <div id="weights-list"></div>
            <button id="btn-generate-targets" disabled>Gerar Alvos</button>
        </section>
    </aside>

    <aside id="properties-panel">
        <div id="props-header">
            <h2 id="props-layer-name">Layer</h2>
            <button id="props-close">&times;</button>
        </div>
        <div id="props-content">
            <div class="prop-group">
                <label>Opacidade</label>
                <input type="range" id="prop-opacity" min="0" max="100" value="70" step="1">
                <span class="prop-value" id="prop-opacity-val">70%</span>
            </div>
            <div class="prop-group">
                <label>Brilho Min</label>
                <input type="range" id="prop-brightness-min" min="0" max="100" value="0" step="1">
                <span class="prop-value" id="prop-brightness-min-val">0</span>
            </div>
            <div class="prop-group">
                <label>Brilho Max</label>
                <input type="range" id="prop-brightness-max" min="0" max="100" value="100" step="1">
                <span class="prop-value" id="prop-brightness-max-val">1</span>
            </div>
            <div class="prop-group">
                <label>Contraste</label>
                <input type="range" id="prop-contrast" min="-100" max="100" value="0" step="1">
                <span class="prop-value" id="prop-contrast-val">0</span>
            </div>
            <div class="prop-group">
                <label>Saturacao</label>
                <input type="range" id="prop-saturation" min="-100" max="100" value="0" step="1">
                <span class="prop-value" id="prop-saturation-val">0</span>
            </div>
            <div id="props-local-controls" style="display:none">
                <div class="prop-group">
                    <label>Colormap</label>
                    <select id="prop-colormap">
                        <option value="viridis">Viridis</option>
                        <option value="magma">Magma</option>
                        <option value="plasma">Plasma</option>
                        <option value="inferno">Inferno</option>
                        <option value="turbo">Turbo</option>
                        <option value="cividis">Cividis</option>
                        <option value="greys">Greys</option>
                    </select>
                </div>
                <div class="prop-group">
                    <label>Min</label>
                    <input type="range" id="prop-vmin" min="0" max="1000" value="0" step="1">
                    <span class="prop-value" id="prop-vmin-val">0</span>
                </div>
                <div class="prop-group">
                    <label>Max</label>
                    <input type="range" id="prop-vmax" min="0" max="1000" value="1000" step="1">
                    <span class="prop-value" id="prop-vmax-val">1</span>
                </div>
            </div>
        </div>
    </aside>

    <main id="map-container">
        <div id="map"></div>
    </main>
</div>
```

**Step 2: Commit**

```bash
git add frontend/index.html
git commit -m "feat: HTML do painel de propriedades de layer"
```

---

### Task 3: Frontend — CSS do painel de propriedades

**Files:**
- Modify: `frontend/style.css` (append at end)

**Step 1: Add styles**

Append to `frontend/style.css`:

```css
/* Properties Panel */
#properties-panel {
    width: 240px;
    min-width: 240px;
    background: #16213e;
    border-right: 1px solid #0f3460;
    overflow-y: auto;
    padding: 12px;
    display: none;
    flex-direction: column;
    gap: 4px;
}

#properties-panel.open {
    display: flex;
}

#props-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}

#props-header h2 {
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #e94560;
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
}

#props-close {
    background: none;
    border: none;
    color: #888;
    font-size: 18px;
    cursor: pointer;
    padding: 0 4px;
    line-height: 1;
}

#props-close:hover {
    color: #e94560;
}

.prop-group {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 4px 0;
}

.prop-group label {
    font-size: 11px;
    color: #888;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.prop-group input[type="range"] {
    width: 100%;
    accent-color: #e94560;
}

.prop-group select {
    width: 100%;
    padding: 4px 6px;
    background: #0f3460;
    color: #e0e0e0;
    border: 1px solid #1a4a8a;
    border-radius: 3px;
    font-size: 12px;
}

.prop-value {
    font-size: 11px;
    color: #888;
    text-align: right;
}

#props-local-controls {
    border-top: 1px solid #0f3460;
    margin-top: 8px;
    padding-top: 8px;
}
```

**Step 2: Commit**

```bash
git add frontend/style.css
git commit -m "feat: CSS do painel de propriedades"
```

---

### Task 4: Frontend — Logica JS do painel de propriedades

**Files:**
- Modify: `frontend/app.js`

**Step 1: Add state and helper functions**

Add after `let pollInterval = null;` (line 34):

```javascript
let selectedLayerId = null;
let layerProps = {};  // per-layer properties: {opacity, brightnessMin, brightnessMax, contrast, saturation, colormap, vmin, vmax}
let layerStats = {};  // per-layer stats from backend: {p2, p98}
```

**Step 2: Add panel open/close/update logic**

Add new functions after `updateStatus`:

```javascript
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
    const isLocal = layer && layer.source === "local";

    // Header
    document.getElementById("props-layer-name").textContent = layer ? layer.name : layerId;

    // Load stats for local layers
    if (isLocal && !layerStats[layerId]) {
        try {
            const resp = await fetch(`/api/tiles/${layerId}/stats`);
            if (resp.ok) {
                layerStats[layerId] = await resp.json();
            }
        } catch (e) { /* ignore */ }
    }

    // Set slider values from stored props
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

    // Local controls
    const localControls = document.getElementById("props-local-controls");
    if (isLocal) {
        localControls.style.display = "block";
        document.getElementById("prop-colormap").value = p.colormap;

        // Set min/max slider range from stats
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
```

**Step 3: Wire up event listeners**

Add new function `setupPropertiesPanel()` and call it from `init()`:

```javascript
function setupPropertiesPanel() {
    document.getElementById("props-close").addEventListener("click", closePropertiesPanel);

    // Universal controls
    const opSlider = document.getElementById("prop-opacity");
    opSlider.addEventListener("input", () => {
        const val = parseInt(opSlider.value);
        document.getElementById("prop-opacity-val").textContent = val + "%";
        if (selectedLayerId && layerProps[selectedLayerId]) {
            layerProps[selectedLayerId].opacity = val;
            applyMapLibreProps(selectedLayerId);
        }
    });

    const bMinSlider = document.getElementById("prop-brightness-min");
    bMinSlider.addEventListener("input", () => {
        const val = parseInt(bMinSlider.value);
        document.getElementById("prop-brightness-min-val").textContent = (val / 100).toFixed(2);
        if (selectedLayerId && layerProps[selectedLayerId]) {
            layerProps[selectedLayerId].brightnessMin = val;
            applyMapLibreProps(selectedLayerId);
        }
    });

    const bMaxSlider = document.getElementById("prop-brightness-max");
    bMaxSlider.addEventListener("input", () => {
        const val = parseInt(bMaxSlider.value);
        document.getElementById("prop-brightness-max-val").textContent = (val / 100).toFixed(2);
        if (selectedLayerId && layerProps[selectedLayerId]) {
            layerProps[selectedLayerId].brightnessMax = val;
            applyMapLibreProps(selectedLayerId);
        }
    });

    const contrastSlider = document.getElementById("prop-contrast");
    contrastSlider.addEventListener("input", () => {
        const val = parseInt(contrastSlider.value);
        document.getElementById("prop-contrast-val").textContent = (val / 100).toFixed(2);
        if (selectedLayerId && layerProps[selectedLayerId]) {
            layerProps[selectedLayerId].contrast = val;
            applyMapLibreProps(selectedLayerId);
        }
    });

    const satSlider = document.getElementById("prop-saturation");
    satSlider.addEventListener("input", () => {
        const val = parseInt(satSlider.value);
        document.getElementById("prop-saturation-val").textContent = (val / 100).toFixed(2);
        if (selectedLayerId && layerProps[selectedLayerId]) {
            layerProps[selectedLayerId].saturation = val;
            applyMapLibreProps(selectedLayerId);
        }
    });

    // Local-only controls
    const cmSelect = document.getElementById("prop-colormap");
    cmSelect.addEventListener("change", () => {
        if (selectedLayerId && layerProps[selectedLayerId]) {
            layerProps[selectedLayerId].colormap = cmSelect.value;
            rebuildTileUrl(selectedLayerId);
        }
    });

    const vminSlider = document.getElementById("prop-vmin");
    vminSlider.addEventListener("input", () => {
        const val = parseInt(vminSlider.value) / 100;
        document.getElementById("prop-vmin-val").textContent = val.toFixed(2);
        if (selectedLayerId && layerProps[selectedLayerId]) {
            layerProps[selectedLayerId].vmin = val;
            rebuildTileUrl(selectedLayerId);
        }
    });

    const vmaxSlider = document.getElementById("prop-vmax");
    vmaxSlider.addEventListener("input", () => {
        const val = parseInt(vmaxSlider.value) / 100;
        document.getElementById("prop-vmax-val").textContent = val.toFixed(2);
        if (selectedLayerId && layerProps[selectedLayerId]) {
            layerProps[selectedLayerId].vmax = val;
            rebuildTileUrl(selectedLayerId);
        }
    });
}
```

**Step 4: Modify existing functions**

In `init()`, add `setupPropertiesPanel()` call after `setupOpacitySlider()`:

```javascript
setupOpacitySlider();
setupPropertiesPanel();
```

In `refreshLayersList()`, modify the label click to open properties panel. Change the label creation block to add a click handler:

```javascript
label.addEventListener("click", (e) => {
    if (checkbox.checked) {
        e.preventDefault();
        openPropertiesPanel(layer.id);
    }
});
```

In `enableLayer()`, apply per-layer props after adding the layer. Replace the hardcoded opacity with stored props:

```javascript
// After map.addLayer, replace the paint opacity line:
if (!layerProps[layerId]) {
    layerProps[layerId] = getDefaultProps();
}
applyMapLibreProps(layerId);
```

In `disableLayer()`, close properties panel if this layer is selected:

```javascript
if (selectedLayerId === layerId) {
    closePropertiesPanel();
}
```

Remove the global `setupOpacitySlider()` function and its call — per-layer opacity replaces it.
Keep the global slider in HTML for now but hide it (or remove the `#opacity-panel` section from HTML).

Actually, keep the global opacity slider as a "default" that applies to newly activated layers. The per-layer panel overrides it. This avoids breaking existing behavior.

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 6: Manual test**

Run: `python -m backend.main`
- Open browser at http://localhost:8000
- Activate a GEE layer (e.g. RGB Verdadeira)
- Click on layer name → properties panel should open
- Adjust brightness/contrast/saturation sliders → instant visual change
- Activate a local layer (e.g. crosta-feox)
- Click on its name → properties panel with colormap dropdown and min/max sliders
- Change colormap to magma → tiles should reload with new colors
- Close panel with X → panel hides

**Step 7: Commit**

```bash
git add frontend/app.js
git commit -m "feat: logica JS do painel de propriedades de layer"
```

---

### Task 5: Remover slider de opacidade global

**Files:**
- Modify: `frontend/index.html` — remove `#opacity-panel` section
- Modify: `frontend/app.js` — remove `setupOpacitySlider()` function
- Modify: `frontend/style.css` — remove `#opacity-slider`, `#opacity-value` styles

**Step 1: Remove opacity panel from HTML**

Remove the entire `<section id="opacity-panel">` block from `index.html`.

**Step 2: Remove setupOpacitySlider from JS**

Remove the `setupOpacitySlider()` function and its call in `init()`.

Remove the hardcoded opacity reference in `enableLayer()` (already replaced by `applyMapLibreProps` in Task 4).

**Step 3: Remove opacity-related CSS**

Remove `#opacity-slider` and `#opacity-value` rules from `style.css`.

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add frontend/index.html frontend/app.js frontend/style.css
git commit -m "refactor: remover slider de opacidade global — substituido por opacidade per-layer"
```
