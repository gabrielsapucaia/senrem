# Fase 3 — ASTER Local + Crosta/PCA/Ninomiya — Plano de Implementacao

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Download dados ASTER L2 via AppEEARS, processar com Metodo Crosta (PCA dirigida), ratios Ninomiya e PCA exploratoria TIR, e servir como tiles no mapa existente.

**Architecture:** Tres novos servicos (aster.py para download, processing.py para PCA/ratios, tiles.py para rio-tiler) integrados ao layers.py existente. COGs gerados em data/rasters/. Frontend sem mudancas — mesma UX de checkbox -> gerar -> tiles.

**Tech Stack:** Python 3.9.6, FastAPI, rasterio, rio-tiler, sklearn.decomposition.PCA, numpy, httpx (AppEEARS API)

---

## Contexto importante

- Projeto: `/Users/gabrielsapucaia/Code/senrem3/`
- Backend: FastAPI em `backend/`, frontend vanilla em `frontend/`
- GEE ja funciona com 7 layers (gee.py) servidas via getMapId()
- layers.py tem lista LAYERS com 12 entries, endpoint POST /api/layers/{id}/generate
- O POST /generate atualmente so aceita layers GEE — precisa ser estendido para layers locais
- Testes em `tests/` com pytest + FastAPI TestClient
- Python 3.9.6: usar typing compativel (sem `X | Y`, usar `Optional[X]`)
- `app.mount("/", StaticFiles(...))` DEVE ser a ultima linha no main.py
- requirements.txt ja tem rasterio, rio-tiler, scikit-learn, httpx, numpy
- Rodar servidor: `source .venv/bin/activate && python -m backend.main`
- Rodar testes: `source .venv/bin/activate && python -m pytest tests/ -v`

---

### Task 1: Servico de tiles locais (tiles.py)

Comecar pelo servico de tiles porque e independente e permite testar o pipeline inteiro depois.

**Files:**
- Create: `backend/services/tiles.py`
- Modify: `backend/main.py`
- Test: `tests/test_tiles.py`

**Step 1: Write the failing test**

Criar `tests/test_tiles.py`:

```python
import numpy as np
import os
import pytest
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS

from backend.services.tiles import TileService


@pytest.fixture
def sample_cog(tmp_path):
    """Cria um COG de teste com dados sinteticos."""
    path = str(tmp_path / "test.tif")
    data = np.random.rand(1, 256, 256).astype(np.float32)
    transform = from_bounds(-47.4, -11.9, -46.9, -11.5, 256, 256)
    with rasterio.open(
        path, "w", driver="GTiff",
        height=256, width=256, count=1, dtype="float32",
        crs=CRS.from_epsg(4326), transform=transform,
    ) as dst:
        dst.write(data)
    return path


def test_tile_service_init():
    service = TileService(processed_dir="/tmp/nonexistent")
    assert service.processed_dir == "/tmp/nonexistent"


def test_get_tile_from_cog(sample_cog):
    service = TileService(processed_dir=os.path.dirname(sample_cog))
    layer_id = "test"
    # Registrar o COG manualmente
    service.register_cog(layer_id, sample_cog)
    tile_bytes = service.get_tile(layer_id, z=10, x=300, y=500)
    assert tile_bytes is not None
    assert len(tile_bytes) > 0


def test_get_tile_unknown_layer():
    service = TileService(processed_dir="/tmp")
    with pytest.raises(ValueError, match="nao registrada"):
        service.get_tile("unknown", z=10, x=300, y=500)
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_tiles.py -v`
Expected: FAIL with "No module named 'backend.services.tiles'"

**Step 3: Write minimal implementation**

Criar `backend/services/tiles.py`:

```python
from typing import Dict, Optional

from rio_tiler.io import Reader


class TileService:
    def __init__(self, processed_dir: str):
        self.processed_dir = processed_dir
        self._cog_registry: Dict[str, str] = {}

    def register_cog(self, layer_id: str, cog_path: str):
        self._cog_registry[layer_id] = cog_path

    def get_tile(self, layer_id: str, z: int, x: int, y: int,
                 colormap: Optional[str] = None,
                 vmin: Optional[float] = None,
                 vmax: Optional[float] = None) -> bytes:
        if layer_id not in self._cog_registry:
            raise ValueError(f"Layer '{layer_id}' nao registrada")

        cog_path = self._cog_registry[layer_id]
        with Reader(cog_path) as src:
            img = src.tile(x, y, z)
            if vmin is not None and vmax is not None:
                img.rescale(in_range=((vmin, vmax),))
            return img.render(img_format="PNG")

    def is_registered(self, layer_id: str) -> bool:
        return layer_id in self._cog_registry

    def get_tile_url_template(self, layer_id: str, base_url: str) -> str:
        return f"{base_url}/api/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png"
```

**Step 4: Add tile endpoint to main.py**

Adicionar o endpoint de tiles. Modificar `backend/main.py` — adicionar ANTES do `app.mount(...)`:

```python
from fastapi.responses import Response
from backend.services.tiles import TileService
from backend.config import settings
import os

tile_service = TileService(
    processed_dir=os.path.join(settings.data_dir, "rasters", "processed")
)

@app.get("/api/tiles/{layer_id}/{z}/{x}/{y}.png")
def get_tile(layer_id: str, z: int, x: int, y: int):
    try:
        tile_bytes = tile_service.get_tile(layer_id, z, x, y)
        return Response(content=tile_bytes, media_type="image/png")
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))
```

**IMPORTANTE:** O `app.mount("/", StaticFiles(...))` DEVE continuar como ultima linha.

**Step 5: Run tests**

Run: `source .venv/bin/activate && python -m pytest tests/test_tiles.py tests/ -v`
Expected: All tests PASS (novos + 13 existentes)

**Step 6: Commit**

```bash
git add backend/services/tiles.py backend/main.py tests/test_tiles.py
git commit -m "feat: servico de tiles locais via rio-tiler"
```

---

### Task 2: Servico de processamento (processing.py)

Core do processamento — PCA, Crosta, ratios Ninomiya. Tudo opera sobre arrays numpy.

**Files:**
- Create: `backend/services/processing.py`
- Test: `tests/test_processing.py`

**Step 1: Write the failing tests**

Criar `tests/test_processing.py`:

```python
import numpy as np
import os
import pytest
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS

from backend.services.processing import ProcessingService


@pytest.fixture
def processing_service(tmp_path):
    return ProcessingService(output_dir=str(tmp_path))


@pytest.fixture
def sample_raster_data():
    """Simula um stack de bandas ASTER (4 bandas, 100x100 pixels)."""
    np.random.seed(42)
    return np.random.rand(4, 100, 100).astype(np.float32) + 0.1


@pytest.fixture
def sample_raster_file(tmp_path, sample_raster_data):
    """Cria um raster multi-banda de teste."""
    path = str(tmp_path / "input.tif")
    transform = from_bounds(-47.4, -11.9, -46.9, -11.5, 100, 100)
    with rasterio.open(
        path, "w", driver="GTiff",
        height=100, width=100, count=4, dtype="float32",
        crs=CRS.from_epsg(4326), transform=transform,
    ) as dst:
        dst.write(sample_raster_data)
    return path


def test_processing_service_init(processing_service):
    assert processing_service is not None


def test_pca(processing_service, sample_raster_data):
    """PCA deve retornar n_components componentes."""
    components, loadings, explained = processing_service.run_pca(
        sample_raster_data, n_components=3
    )
    assert components.shape == (3, 100, 100)
    assert loadings.shape == (3, 4)
    assert len(explained) == 3
    assert abs(sum(explained) - 1.0) < 0.01


def test_crosta_select_component(processing_service, sample_raster_data):
    """Crosta deve selecionar a CP com maior peso na banda alvo."""
    components, loadings, _ = processing_service.run_pca(
        sample_raster_data, n_components=3
    )
    selected = processing_service.select_crosta_component(
        components, loadings, target_band=2, contrast_band=0
    )
    assert selected.shape == (100, 100)


def test_band_ratio(processing_service, sample_raster_data):
    """Ratio de duas bandas."""
    ratio = processing_service.compute_ratio(
        sample_raster_data[0], sample_raster_data[1]
    )
    assert ratio.shape == (100, 100)
    expected = sample_raster_data[0] / sample_raster_data[1]
    np.testing.assert_array_almost_equal(ratio, expected, decimal=5)


def test_ninomiya_aloh(processing_service, sample_raster_data):
    """AlOH index = B7 / (B6 * B8), simulado com bandas 0,1,2."""
    result = processing_service.ninomiya_aloh(
        b6=sample_raster_data[0],
        b7=sample_raster_data[1],
        b8=sample_raster_data[2],
    )
    assert result.shape == (100, 100)
    expected = sample_raster_data[1] / (sample_raster_data[0] * sample_raster_data[2])
    np.testing.assert_array_almost_equal(result, expected, decimal=5)


def test_save_as_cog(processing_service, sample_raster_data, tmp_path):
    """Salvar array como COG."""
    output_path = str(tmp_path / "output.tif")
    transform = from_bounds(-47.4, -11.9, -46.9, -11.5, 100, 100)
    crs = CRS.from_epsg(4326)
    processing_service.save_as_cog(
        sample_raster_data[0], output_path, transform=transform, crs=crs
    )
    assert os.path.exists(output_path)
    with rasterio.open(output_path) as src:
        assert src.count == 1
        assert src.width == 100
        assert src.height == 100
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_processing.py -v`
Expected: FAIL with "No module named 'backend.services.processing'"

**Step 3: Write implementation**

Criar `backend/services/processing.py`:

```python
from typing import List, Tuple

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine
from sklearn.decomposition import PCA


class ProcessingService:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    def run_pca(
        self, bands: np.ndarray, n_components: int = None
    ) -> Tuple[np.ndarray, np.ndarray, List[float]]:
        n_bands, height, width = bands.shape
        if n_components is None:
            n_components = n_bands

        pixels = bands.reshape(n_bands, -1).T
        valid_mask = np.all(np.isfinite(pixels), axis=1)
        valid_pixels = pixels[valid_mask]

        pca = PCA(n_components=n_components)
        transformed = pca.fit_transform(valid_pixels)

        components = np.full((n_components, height * width), np.nan, dtype=np.float32)
        components[:, valid_mask] = transformed.T
        components = components.reshape(n_components, height, width)

        return components, pca.components_, pca.explained_variance_ratio_.tolist()

    def select_crosta_component(
        self,
        components: np.ndarray,
        loadings: np.ndarray,
        target_band: int,
        contrast_band: int,
    ) -> np.ndarray:
        target_weights = np.abs(loadings[:, target_band])
        best_cp = int(np.argmax(target_weights))

        selected = components[best_cp].copy()

        if loadings[best_cp, target_band] < 0:
            selected = -selected

        if loadings[best_cp, target_band] * loadings[best_cp, contrast_band] > 0:
            selected = -selected

        return selected

    def compute_ratio(self, numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = numerator / denominator
            ratio[~np.isfinite(ratio)] = np.nan
        return ratio

    def ninomiya_aloh(self, b6: np.ndarray, b7: np.ndarray, b8: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            result = b7 / (b6 * b8)
            result[~np.isfinite(result)] = np.nan
        return result

    def ninomiya_mgoh(self, b6: np.ndarray, b7: np.ndarray, b9: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            result = b7 / (b6 + b9)
            result[~np.isfinite(result)] = np.nan
        return result

    def ninomiya_ferrous(self, b4: np.ndarray, b5: np.ndarray) -> np.ndarray:
        return self.compute_ratio(b5, b4)

    def save_as_cog(
        self,
        data: np.ndarray,
        output_path: str,
        transform: Affine,
        crs: CRS,
    ):
        if data.ndim == 2:
            data = data[np.newaxis, :]
        count, height, width = data.shape

        with rasterio.open(
            output_path, "w", driver="GTiff",
            height=height, width=width, count=count,
            dtype=data.dtype,
            crs=crs, transform=transform,
            tiled=True, blockxsize=256, blockysize=256,
            compress="deflate",
        ) as dst:
            dst.write(data)
```

**Step 4: Run tests**

Run: `source .venv/bin/activate && python -m pytest tests/test_processing.py tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add backend/services/processing.py tests/test_processing.py
git commit -m "feat: servico de processamento — PCA, Crosta, ratios Ninomiya"
```

---

### Task 3: Servico de download ASTER (aster.py)

Download via AppEEARS API da NASA. Inclui autenticacao, submissao de task, polling e download.

**Files:**
- Create: `backend/services/aster.py`
- Modify: `backend/config.py`
- Test: `tests/test_aster.py`

**Step 1: Write the failing tests**

Criar `tests/test_aster.py`:

```python
import os
import pytest

from backend.services.aster import AsterService
from backend.config import settings


def test_aster_service_init(tmp_path):
    service = AsterService(
        data_dir=str(tmp_path),
        username="test",
        password="test",
    )
    assert service.data_dir == str(tmp_path)


def test_build_aoi_geojson():
    service = AsterService(data_dir="/tmp", username="", password="")
    geojson = service.build_aoi_geojson(
        center_lon=-47.155531,
        center_lat=-11.699153,
        radius_km=25.0,
    )
    assert geojson["type"] == "Polygon"
    assert len(geojson["coordinates"][0]) >= 32


def test_get_task_payload():
    service = AsterService(data_dir="/tmp", username="", password="")
    aoi = service.build_aoi_geojson(-47.155531, -11.699153, 25.0)
    payload = service.build_task_payload(
        task_name="test",
        product="AST_07XT",
        aoi=aoi,
        start_date="2000-01-01",
        end_date="2008-12-31",
    )
    assert payload["task_name"] == "test"
    assert payload["task_type"] == "area"
    assert len(payload["params"]["dates"]) == 1


def test_cache_dir_structure(tmp_path):
    service = AsterService(data_dir=str(tmp_path), username="", password="")
    service.ensure_dirs()
    assert os.path.isdir(os.path.join(str(tmp_path), "aster", "raw"))
    assert os.path.isdir(os.path.join(str(tmp_path), "aster", "composite"))
    assert os.path.isdir(os.path.join(str(tmp_path), "processed"))
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_aster.py -v`
Expected: FAIL with "No module named 'backend.services.aster'"

**Step 3: Add config fields**

Modificar `backend/config.py` — adicionar campos para Earthdata:

```python
earthdata_username: str = ""
earthdata_password: str = ""
```

**Step 4: Write implementation**

Criar `backend/services/aster.py`:

```python
import math
import os
import time
from typing import Dict, List, Optional

import httpx


APPEEARS_BASE = "https://appeears.earthdatacloud.nasa.gov/api"


class AsterService:
    def __init__(self, data_dir: str, username: str, password: str):
        self.data_dir = data_dir
        self.username = username
        self.password = password
        self._token: Optional[str] = None

    def ensure_dirs(self):
        for subdir in ["aster/raw", "aster/composite", "processed"]:
            os.makedirs(os.path.join(self.data_dir, subdir), exist_ok=True)

    def build_aoi_geojson(
        self, center_lon: float, center_lat: float, radius_km: float
    ) -> Dict:
        points = 64
        coords = []
        for i in range(points + 1):
            angle = (i / points) * 2 * math.pi
            dx = radius_km * math.cos(angle)
            dy = radius_km * math.sin(angle)
            lat = center_lat + (dy / 111.32)
            lon = center_lon + (dx / (111.32 * math.cos(math.radians(center_lat))))
            coords.append([lon, lat])
        return {"type": "Polygon", "coordinates": [coords]}

    def build_task_payload(
        self,
        task_name: str,
        product: str,
        aoi: Dict,
        start_date: str,
        end_date: str,
    ) -> Dict:
        layer_map = {
            "AST_07XT": [
                f"AST_07XT.003_ImageData{i}" for i in range(1, 10)
            ],
            "AST_08": [
                f"AST_08.003_Emissivity_Mean_Band{i}" for i in range(10, 15)
            ],
        }
        layers = []
        for layer_name in layer_map.get(product, []):
            layers.append({"product": f"{product}.003", "layer": layer_name})

        return {
            "task_name": task_name,
            "task_type": "area",
            "params": {
                "dates": [{"startDate": start_date, "endDate": end_date}],
                "layers": layers,
                "geo": aoi,
                "output": {"format": {"type": "geotiff"}, "projection": "geographic"},
            },
        }

    def login(self) -> str:
        resp = httpx.post(
            f"{APPEEARS_BASE}/login",
            auth=(self.username, self.password),
            timeout=30,
        )
        resp.raise_for_status()
        self._token = resp.json()["token"]
        return self._token

    def submit_task(self, payload: Dict) -> str:
        if not self._token:
            self.login()
        resp = httpx.post(
            f"{APPEEARS_BASE}/task",
            json=payload,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["task_id"]

    def wait_for_task(self, task_id: str, poll_interval: int = 30, timeout: int = 3600) -> bool:
        if not self._token:
            self.login()
        elapsed = 0
        while elapsed < timeout:
            resp = httpx.get(
                f"{APPEEARS_BASE}/task/{task_id}",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=30,
            )
            resp.raise_for_status()
            status = resp.json()["status"]
            if status == "done":
                return True
            if status == "error":
                raise RuntimeError(f"AppEEARS task {task_id} failed")
            time.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(f"AppEEARS task {task_id} timed out after {timeout}s")

    def download_files(self, task_id: str) -> List[str]:
        if not self._token:
            self.login()
        self.ensure_dirs()

        resp = httpx.get(
            f"{APPEEARS_BASE}/bundle/{task_id}",
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30,
        )
        resp.raise_for_status()
        files = resp.json()["files"]

        downloaded = []
        raw_dir = os.path.join(self.data_dir, "aster", "raw")
        for f in files:
            if not f["file_name"].endswith(".tif"):
                continue
            file_path = os.path.join(raw_dir, os.path.basename(f["file_name"]))
            if os.path.exists(file_path):
                downloaded.append(file_path)
                continue
            resp = httpx.get(
                f"{APPEEARS_BASE}/bundle/{task_id}/{f['file_id']}",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=300,
            )
            resp.raise_for_status()
            with open(file_path, "wb") as out:
                out.write(resp.content)
            downloaded.append(file_path)
        return downloaded

    def has_cached_composite(self, product: str) -> bool:
        composite_dir = os.path.join(self.data_dir, "aster", "composite")
        return os.path.exists(os.path.join(composite_dir, f"{product}_composite.tif"))

    def get_composite_path(self, product: str) -> str:
        return os.path.join(self.data_dir, "aster", "composite", f"{product}_composite.tif")
```

**Step 5: Run tests**

Run: `source .venv/bin/activate && python -m pytest tests/test_aster.py tests/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add backend/services/aster.py backend/config.py tests/test_aster.py
git commit -m "feat: servico de download ASTER via AppEEARS API"
```

---

### Task 4: Pipeline de composicao ASTER (mediana)

Ler cenas brutas baixadas, gerar composite mediana por banda, salvar como COG.

**Files:**
- Modify: `backend/services/aster.py`
- Modify: `backend/services/processing.py`
- Test: `tests/test_composite.py`

**Step 1: Write the failing tests**

Criar `tests/test_composite.py`:

```python
import numpy as np
import os
import pytest
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS

from backend.services.processing import ProcessingService


@pytest.fixture
def processing_service(tmp_path):
    return ProcessingService(output_dir=str(tmp_path))


@pytest.fixture
def sample_scenes(tmp_path):
    """Cria 3 cenas simuladas com 4 bandas cada."""
    transform = from_bounds(-47.4, -11.9, -46.9, -11.5, 50, 50)
    crs = CRS.from_epsg(4326)
    paths = []
    np.random.seed(42)
    for i in range(3):
        path = str(tmp_path / f"scene_{i}.tif")
        data = np.random.rand(4, 50, 50).astype(np.float32) + 0.1 + i * 0.1
        with rasterio.open(
            path, "w", driver="GTiff",
            height=50, width=50, count=4, dtype="float32",
            crs=crs, transform=transform,
        ) as dst:
            dst.write(data)
        paths.append(path)
    return paths


def test_build_composite_median(processing_service, sample_scenes, tmp_path):
    output_path = str(tmp_path / "composite.tif")
    processing_service.build_composite(
        scene_paths=sample_scenes,
        output_path=output_path,
        bands=[1, 2, 3, 4],
    )
    assert os.path.exists(output_path)
    with rasterio.open(output_path) as src:
        assert src.count == 4
        assert src.width == 50
        assert src.height == 50
        data = src.read()
        assert data.shape == (4, 50, 50)
        assert np.all(np.isfinite(data))


def test_composite_is_median(processing_service, sample_scenes, tmp_path):
    """Verifica que o composite e realmente a mediana."""
    output_path = str(tmp_path / "composite.tif")
    processing_service.build_composite(
        scene_paths=sample_scenes,
        output_path=output_path,
        bands=[1],
    )
    # Ler cenas originais e calcular mediana manualmente
    arrays = []
    for path in sample_scenes:
        with rasterio.open(path) as src:
            arrays.append(src.read(1))
    expected_median = np.median(arrays, axis=0)

    with rasterio.open(output_path) as src:
        actual = src.read(1)
    np.testing.assert_array_almost_equal(actual, expected_median, decimal=5)
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_composite.py -v`
Expected: FAIL with "ProcessingService has no attribute build_composite" (metodo nao implementado ainda)

**Step 3: Add build_composite to ProcessingService**

Adicionar metodo em `backend/services/processing.py`:

```python
def build_composite(
    self,
    scene_paths: List[str],
    output_path: str,
    bands: List[int],
):
    import rasterio
    from rasterio.crs import CRS

    ref = rasterio.open(scene_paths[0])
    height, width = ref.height, ref.width
    transform = ref.transform
    crs = ref.crs
    ref.close()

    all_data = []
    for path in scene_paths:
        with rasterio.open(path) as src:
            scene_bands = src.read(bands)
            all_data.append(scene_bands)

    stacked = np.stack(all_data, axis=0)
    median = np.median(stacked, axis=0).astype(np.float32)

    self.save_as_cog(median, output_path, transform=transform, crs=crs)
```

Nota: `save_as_cog` ja existe da Task 2 e aceita arrays multi-banda (3D).

**Step 4: Run tests**

Run: `source .venv/bin/activate && python -m pytest tests/test_composite.py tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add backend/services/processing.py tests/test_composite.py
git commit -m "feat: pipeline de composicao mediana para cenas ASTER"
```

---

### Task 5: Integrar layers locais no layers.py

Estender o endpoint POST /generate para aceitar layers locais (source="local") alem das GEE.

**Files:**
- Modify: `backend/api/layers.py`
- Modify: `backend/main.py`
- Test: `tests/test_local_layers.py`

**Step 1: Write the failing tests**

Criar `tests/test_local_layers.py`:

```python
import numpy as np
import os
import pytest
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from fastapi.testclient import TestClient


def test_layers_list_includes_local():
    from backend.main import app
    client = TestClient(app)
    resp = client.get("/api/layers")
    assert resp.status_code == 200
    layers = resp.json()
    local_layers = [l for l in layers if l["source"] == "local"]
    assert len(local_layers) >= 6
    layer_ids = [l["id"] for l in local_layers]
    assert "crosta-feox" in layer_ids
    assert "crosta-oh" in layer_ids
    assert "ninomiya-aloh" in layer_ids


def test_local_layer_available_when_cog_exists(tmp_path):
    """Se o COG existe no cache, available=True."""
    # Este teste verifica a logica, nao o endpoint completo
    from backend.api.layers import _check_local_available
    cog_path = str(tmp_path / "crosta-feox.tif")
    # Sem arquivo -> False
    assert _check_local_available("crosta-feox", str(tmp_path)) is False
    # Com arquivo -> True
    data = np.random.rand(1, 10, 10).astype(np.float32)
    transform = from_bounds(-47.4, -11.9, -46.9, -11.5, 10, 10)
    with rasterio.open(
        cog_path, "w", driver="GTiff",
        height=10, width=10, count=1, dtype="float32",
        crs=CRS.from_epsg(4326), transform=transform,
    ) as dst:
        dst.write(data)
    assert _check_local_available("crosta-feox", str(tmp_path)) is True
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_local_layers.py -v`
Expected: FAIL

**Step 3: Modify layers.py**

Atualizar `backend/api/layers.py` para incluir as 6 novas layers e suportar source="local":

```python
import os

from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.services.gee import GEEService

router = APIRouter(prefix="/api")

gee_service = GEEService()

_generated_tiles = {}

LOCAL_LAYER_CONFIGS = {
    "crosta-feox": {
        "name": "Crosta FeOx",
        "description": "PCA dirigida VNIR — oxidos de ferro (ASTER 2000-2008)",
    },
    "crosta-oh": {
        "name": "Crosta OH/Sericita",
        "description": "PCA dirigida SWIR — sericita/argilas (ASTER 2000-2008)",
    },
    "ninomiya-aloh": {
        "name": "Ninomiya AlOH",
        "description": "B7/(B6*B8) — argilas AlOH (ASTER 2000-2008)",
    },
    "ninomiya-mgoh": {
        "name": "Ninomiya MgOH",
        "description": "B7/(B6+B9) — clorita/talco/serpentina (ASTER 2000-2008)",
    },
    "ninomiya-ferrous": {
        "name": "Ninomiya Fe2+",
        "description": "B5/B4 — ferro ferroso (ASTER 2000-2008)",
    },
    "pca-tir": {
        "name": "PCA TIR",
        "description": "PCA exploratoria B10-B14 — silicificacao (ASTER 2000-2024)",
    },
}

LAYERS = [
    {"id": "rgb-true", "name": "RGB Verdadeira", "category": "spectral", "source": "gee"},
    {"id": "rgb-false", "name": "RGB Falsa-cor", "category": "spectral", "source": "gee"},
    {"id": "iron-oxide", "name": "Oxidos de Ferro", "category": "spectral", "source": "gee"},
    {"id": "clay", "name": "Argilas / Sericita", "category": "spectral", "source": "gee"},
    {"id": "carbonate", "name": "Carbonatos", "category": "spectral", "source": "gee"},
    {"id": "silica", "name": "Silica", "category": "spectral", "source": "gee"},
    {"id": "dem", "name": "DEM / Hillshade", "category": "terrain", "source": "gee"},
    {"id": "crosta-feox", "name": "Crosta FeOx", "category": "spectral", "source": "local"},
    {"id": "crosta-oh", "name": "Crosta OH/Sericita", "category": "spectral", "source": "local"},
    {"id": "ninomiya-aloh", "name": "Ninomiya AlOH", "category": "spectral", "source": "local"},
    {"id": "ninomiya-mgoh", "name": "Ninomiya MgOH", "category": "spectral", "source": "local"},
    {"id": "ninomiya-ferrous", "name": "Ninomiya Fe2+", "category": "spectral", "source": "local"},
    {"id": "pca-tir", "name": "PCA TIR", "category": "spectral", "source": "local"},
    {"id": "lineaments", "name": "Lineamentos", "category": "terrain", "source": "local"},
    {"id": "geology", "name": "Geologia (CPRM)", "category": "cprm", "source": "cprm"},
    {"id": "magnetic", "name": "Magnetico", "category": "cprm", "source": "cprm"},
    {"id": "gamma", "name": "Gamaespectrometrico", "category": "cprm", "source": "cprm"},
    {"id": "targets", "name": "Alvos", "category": "prospectivity", "source": "model"},
]


def _check_local_available(layer_id: str, processed_dir: str) -> bool:
    cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
    return os.path.exists(cog_path)


@router.get("/layers")
def list_layers():
    gee_layers = gee_service.get_available_layers()
    processed_dir = os.path.join(settings.data_dir, "rasters", "processed")
    has_earthdata = bool(settings.earthdata_username and settings.earthdata_password)
    result = []
    for layer in LAYERS:
        if layer["source"] == "gee":
            available = layer["id"] in _generated_tiles
            can_generate = layer["id"] in gee_layers
        elif layer["source"] == "local" and layer["id"] in LOCAL_LAYER_CONFIGS:
            available = _check_local_available(layer["id"], processed_dir)
            can_generate = has_earthdata or available
        else:
            available = False
            can_generate = False
        result.append({**layer, "available": available, "can_generate": can_generate})
    return result


@router.post("/layers/{layer_id}/generate")
def generate_layer(layer_id: str):
    gee_layers = gee_service.get_available_layers()

    # Layer GEE
    if layer_id in gee_layers:
        try:
            tile_data = gee_service.get_layer_tiles(layer_id)
            _generated_tiles[layer_id] = tile_data
            return tile_data
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # Layer local
    if layer_id in LOCAL_LAYER_CONFIGS:
        processed_dir = os.path.join(settings.data_dir, "rasters", "processed")
        cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
        config = LOCAL_LAYER_CONFIGS[layer_id]

        if not os.path.exists(cog_path):
            raise HTTPException(
                status_code=404,
                detail=f"COG para '{layer_id}' nao encontrado. Execute o download ASTER primeiro.",
            )

        # Registrar no tile service e retornar URL
        from backend.main import tile_service
        tile_service.register_cog(layer_id, cog_path)

        tile_url = f"/api/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png"
        result = {
            "layer_id": layer_id,
            "name": config["name"],
            "description": config["description"],
            "tile_url": tile_url,
        }
        _generated_tiles[layer_id] = result
        return result

    raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' nao disponivel para geracao")
```

**Step 4: Run tests**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`
Expected: All PASS (novos + existentes)

**Step 5: Commit**

```bash
git add backend/api/layers.py tests/test_local_layers.py
git commit -m "feat: integrar layers locais ASTER no endpoint /generate"
```

---

### Task 6: Pipeline completo — orquestrar download + processamento

Criar o orquestrador que conecta download ASTER -> composite -> Crosta/Ninomiya/PCA -> COGs -> registro de tiles.

**Files:**
- Create: `backend/services/pipeline.py`
- Test: `tests/test_pipeline.py`

**Step 1: Write the failing test**

Criar `tests/test_pipeline.py`:

```python
import pytest

from backend.services.pipeline import AsterPipeline


def test_pipeline_init(tmp_path):
    pipeline = AsterPipeline(
        data_dir=str(tmp_path),
        earthdata_username="test",
        earthdata_password="test",
        center_lon=-47.155531,
        center_lat=-11.699153,
        radius_km=25.0,
    )
    assert pipeline is not None


def test_pipeline_get_available_products(tmp_path):
    pipeline = AsterPipeline(
        data_dir=str(tmp_path),
        earthdata_username="",
        earthdata_password="",
        center_lon=-47.155531,
        center_lat=-11.699153,
        radius_km=25.0,
    )
    products = pipeline.get_required_products()
    assert "AST_07XT" in products
    assert "AST_08" in products


def test_pipeline_layer_to_product_mapping(tmp_path):
    pipeline = AsterPipeline(
        data_dir=str(tmp_path),
        earthdata_username="",
        earthdata_password="",
        center_lon=-47.155531,
        center_lat=-11.699153,
        radius_km=25.0,
    )
    assert pipeline.get_product_for_layer("crosta-feox") == "AST_07XT"
    assert pipeline.get_product_for_layer("crosta-oh") == "AST_07XT"
    assert pipeline.get_product_for_layer("pca-tir") == "AST_08"
    assert pipeline.get_product_for_layer("ninomiya-aloh") == "AST_07XT"
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_pipeline.py -v`
Expected: FAIL

**Step 3: Write implementation**

Criar `backend/services/pipeline.py`:

```python
import os
from typing import Dict, List, Optional

from backend.services.aster import AsterService
from backend.services.processing import ProcessingService


LAYER_PRODUCT_MAP = {
    "crosta-feox": "AST_07XT",
    "crosta-oh": "AST_07XT",
    "ninomiya-aloh": "AST_07XT",
    "ninomiya-mgoh": "AST_07XT",
    "ninomiya-ferrous": "AST_07XT",
    "pca-tir": "AST_08",
}

PRODUCT_DATE_RANGES = {
    "AST_07XT": ("2000-01-01", "2008-04-01"),
    "AST_08": ("2000-01-01", "2024-12-31"),
}


class AsterPipeline:
    def __init__(
        self,
        data_dir: str,
        earthdata_username: str,
        earthdata_password: str,
        center_lon: float,
        center_lat: float,
        radius_km: float,
    ):
        self.data_dir = data_dir
        self.center_lon = center_lon
        self.center_lat = center_lat
        self.radius_km = radius_km
        self.aster_service = AsterService(
            data_dir=data_dir,
            username=earthdata_username,
            password=earthdata_password,
        )
        self.processing_service = ProcessingService(
            output_dir=os.path.join(data_dir, "rasters", "processed")
        )

    def get_required_products(self) -> List[str]:
        return list(PRODUCT_DATE_RANGES.keys())

    def get_product_for_layer(self, layer_id: str) -> str:
        return LAYER_PRODUCT_MAP[layer_id]

    def get_processed_path(self, layer_id: str) -> str:
        return os.path.join(self.data_dir, "rasters", "processed", f"{layer_id}.tif")

    def is_processed(self, layer_id: str) -> bool:
        return os.path.exists(self.get_processed_path(layer_id))

    def download_and_composite(self, product: str) -> str:
        if self.aster_service.has_cached_composite(product):
            return self.aster_service.get_composite_path(product)

        self.aster_service.ensure_dirs()
        aoi = self.aster_service.build_aoi_geojson(
            self.center_lon, self.center_lat, self.radius_km
        )
        start_date, end_date = PRODUCT_DATE_RANGES[product]
        payload = self.aster_service.build_task_payload(
            task_name=f"senrem3_{product}",
            product=product,
            aoi=aoi,
            start_date=start_date,
            end_date=end_date,
        )
        task_id = self.aster_service.submit_task(payload)
        self.aster_service.wait_for_task(task_id)
        scene_paths = self.aster_service.download_files(task_id)

        composite_path = self.aster_service.get_composite_path(product)
        n_bands = 9 if product == "AST_07XT" else 5
        self.processing_service.build_composite(
            scene_paths=scene_paths,
            output_path=composite_path,
            bands=list(range(1, n_bands + 1)),
        )
        return composite_path

    def process_layer(self, layer_id: str) -> str:
        import rasterio
        import numpy as np

        if self.is_processed(layer_id):
            return self.get_processed_path(layer_id)

        product = self.get_product_for_layer(layer_id)
        composite_path = self.download_and_composite(product)

        with rasterio.open(composite_path) as src:
            data = src.read()
            transform = src.transform
            crs = src.crs

        output_path = self.get_processed_path(layer_id)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        if layer_id == "crosta-feox":
            vnir = data[:3]  # B1, B2, B3
            components, loadings, _ = self.processing_service.run_pca(vnir, n_components=3)
            result = self.processing_service.select_crosta_component(
                components, loadings, target_band=2, contrast_band=0
            )
        elif layer_id == "crosta-oh":
            swir = data[3:7]  # B4, B5, B6, B7
            components, loadings, _ = self.processing_service.run_pca(swir, n_components=4)
            result = self.processing_service.select_crosta_component(
                components, loadings, target_band=2, contrast_band=1
            )
        elif layer_id == "ninomiya-aloh":
            result = self.processing_service.ninomiya_aloh(
                b6=data[5], b7=data[6], b8=data[7]
            )
        elif layer_id == "ninomiya-mgoh":
            result = self.processing_service.ninomiya_mgoh(
                b6=data[5], b7=data[6], b9=data[8]
            )
        elif layer_id == "ninomiya-ferrous":
            result = self.processing_service.ninomiya_ferrous(
                b4=data[3], b5=data[4]
            )
        elif layer_id == "pca-tir":
            tir = data[:5]  # B10-B14
            components, _, _ = self.processing_service.run_pca(tir, n_components=3)
            result = components[1]  # CP2 (CP1 = albedo)
        else:
            raise ValueError(f"Layer desconhecida: {layer_id}")

        self.processing_service.save_as_cog(result, output_path, transform=transform, crs=crs)
        return output_path
```

**Step 4: Run tests**

Run: `source .venv/bin/activate && python -m pytest tests/test_pipeline.py tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add backend/services/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline completo ASTER — download + composite + processamento"
```

---

### Task 7: Integracao final e testes end-to-end

Conectar o pipeline ao endpoint /generate para layers locais. Atualizar CLAUDE.md.

**Files:**
- Modify: `backend/api/layers.py`
- Modify: `backend/main.py`
- Modify: `CLAUDE.md`
- Test: verificar todos os testes passam

**Step 1: Atualizar layers.py para usar pipeline**

No `generate_layer`, quando o COG nao existe e tem credenciais, rodar o pipeline:

```python
# Na secao "Layer local" do generate_layer:
if not os.path.exists(cog_path):
    if not settings.earthdata_username or not settings.earthdata_password:
        raise HTTPException(
            status_code=400,
            detail="Credenciais Earthdata nao configuradas. Defina earthdata_username e earthdata_password.",
        )
    from backend.services.pipeline import AsterPipeline
    pipeline = AsterPipeline(
        data_dir=settings.data_dir,
        earthdata_username=settings.earthdata_username,
        earthdata_password=settings.earthdata_password,
        center_lon=settings.study_area_center_lon,
        center_lat=settings.study_area_center_lat,
        radius_km=settings.study_area_radius_km,
    )
    pipeline.process_layer(layer_id)
```

**Step 2: Rodar todos os testes**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`
Expected: All PASS

**Step 3: Atualizar CLAUDE.md com status da Fase 3**

Adicionar secao Fase 3 no status atual, atualizar estrutura de arquivos, mencionar novos endpoints e layers.

**Step 4: Commit**

```bash
git add backend/api/layers.py backend/main.py CLAUDE.md
git commit -m "feat: integracao final Fase 3 — pipeline ASTER completo"
```

---

## Resumo de tasks

| Task | Descricao | Arquivos |
|------|-----------|----------|
| 1 | Servico de tiles locais (rio-tiler) | tiles.py, main.py, test_tiles.py |
| 2 | Servico de processamento (PCA/Crosta/Ninomiya) | processing.py, test_processing.py |
| 3 | Servico de download ASTER (AppEEARS) | aster.py, config.py, test_aster.py |
| 4 | Pipeline de composicao mediana | processing.py, test_composite.py |
| 5 | Integrar layers locais no layers.py | layers.py, test_local_layers.py |
| 6 | Pipeline completo (orquestrador) | pipeline.py, test_pipeline.py |
| 7 | Integracao final e CLAUDE.md | layers.py, main.py, CLAUDE.md |

## Dependencias entre tasks

- Tasks 1, 2, 3 sao independentes (podem ser feitas em paralelo)
- Task 4 depende de Task 2 (usa ProcessingService.build_composite)
- Task 5 depende de Task 1 (usa TileService)
- Task 6 depende de Tasks 2, 3, 4 (usa AsterService + ProcessingService)
- Task 7 depende de Tasks 5, 6 (integracao final)
