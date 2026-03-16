# Fase 4: Dados CPRM/SGB e Aerogeofísica — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrar geologia, ocorrências minerais e aerogeofísica (XYZ bruto → grids interpolados) ao dashboard SENREM3.

**Architecture:** Três pipelines: (1) WFS GeoSGB → GeoJSON cache → endpoint `/api/vectors/` → MapLibre geojson layers, (2) XYZ bruto → recorte bbox → interpolação cubic 125m → COGs → rio-tiler, (3) derivados magnéticos via FFT. Frontend renderiza vetoriais como polígonos/pontos e rasters via tiles existentes.

**Tech Stack:** FastAPI, scipy (griddata, fft), numpy, rasterio, requests, MapLibre GL JS

---

### Task 1: Serviço CPRM — download WFS e cache GeoJSON

**Files:**
- Create: `backend/services/cprm.py`
- Create: `tests/test_cprm.py`

**Step 1: Write tests**

```python
# tests/test_cprm.py
import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest


def _make_wfs_response(features):
    return {"type": "FeatureCollection", "features": features}


def _make_geology_feature(sigla="PP4nat2qt", nome="Quartzito Natividade", era="Paleoproterozóico"):
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[-47.2, -11.7], [-47.1, -11.7], [-47.1, -11.6], [-47.2, -11.6], [-47.2, -11.7]]]},
        "properties": {"sigla": sigla, "nome": nome, "era_max": era, "litotipos": "Quartzito", "legenda": "Quartzitos"}
    }


def _make_occurrence_feature(substancia="Ouro", lon=-47.15, lat=-11.70):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"substancias": substancia, "status_economico": "Mina", "toponimia": "Test Mine", "longitude": lon, "latitude": lat}
    }


class TestCPRMService:
    def test_download_geology(self):
        from backend.services.cprm import CPRMService

        with tempfile.TemporaryDirectory() as tmpdir:
            svc = CPRMService(vectors_dir=tmpdir, bbox=(-47.38, -11.93, -46.93, -11.47))
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = _make_wfs_response([_make_geology_feature()])

            with patch("requests.get", return_value=mock_resp):
                result = svc.download_geology()

            assert len(result["features"]) == 1
            assert os.path.exists(os.path.join(tmpdir, "geology-litho.geojson"))
            assert os.path.exists(os.path.join(tmpdir, "geology-age.geojson"))

    def test_download_occurrences(self):
        from backend.services.cprm import CPRMService

        with tempfile.TemporaryDirectory() as tmpdir:
            svc = CPRMService(vectors_dir=tmpdir, bbox=(-47.38, -11.93, -46.93, -11.47))
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = _make_wfs_response([
                _make_occurrence_feature("Ouro"),
                _make_occurrence_feature("Ferro", -47.14, -11.55),
            ])

            with patch("requests.get", return_value=mock_resp):
                result = svc.download_occurrences()

            assert len(result["features"]) == 2
            assert os.path.exists(os.path.join(tmpdir, "mineral-occurrences.geojson"))

    def test_get_cached_geology(self):
        from backend.services.cprm import CPRMService

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write cache file
            geojson = _make_wfs_response([_make_geology_feature()])
            with open(os.path.join(tmpdir, "geology-litho.geojson"), "w") as f:
                json.dump(geojson, f)

            svc = CPRMService(vectors_dir=tmpdir, bbox=(-47.38, -11.93, -46.93, -11.47))
            result = svc.get_layer("geology-litho")
            assert len(result["features"]) == 1

    def test_age_color_mapping(self):
        from backend.services.cprm import CPRMService

        with tempfile.TemporaryDirectory() as tmpdir:
            svc = CPRMService(vectors_dir=tmpdir, bbox=(-47.38, -11.93, -46.93, -11.47))
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            features = [
                _make_geology_feature("A", "Unit A", "Paleoproterozóico"),
                _make_geology_feature("B", "Unit B", "Neoproterozóico"),
            ]
            mock_resp.json.return_value = _make_wfs_response(features)

            with patch("requests.get", return_value=mock_resp):
                svc.download_geology()

            age_geojson = svc.get_layer("geology-age")
            for feat in age_geojson["features"]:
                assert "color" in feat["properties"]
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_cprm.py -v`
Expected: FAIL (module not found)

**Step 3: Implement CPRMService**

```python
# backend/services/cprm.py
import json
import os

import requests

WFS_BASE = "https://geoservicos.sgb.gov.br/geoserver/wfs"

ERA_COLORS = {
    "Paleoproterozóico": "#2ca02c",
    "Mesoproterozóico": "#98df8a",
    "Neoproterozóico": "#1f77b4",
    "Paleozóico": "#ff7f0e",
    "Mesozóico": "#d62728",
    "Cenozóico": "#ffbb78",
    "Arqueano": "#9467bd",
}

# Cores para siglas geologicas (paleta categorica)
LITHO_PALETTE = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
    "#469990", "#dcbeff", "#9A6324", "#fffac8", "#800000",
    "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
    "#e6beff", "#1abc9c", "#7f8c8d", "#2ecc71", "#e74c3c",
]


class CPRMService:
    def __init__(self, vectors_dir: str, bbox: tuple):
        self.vectors_dir = vectors_dir
        self.bbox = bbox  # (lon_min, lat_min, lon_max, lat_max)
        os.makedirs(vectors_dir, exist_ok=True)

    def _wfs_request(self, type_name: str) -> dict:
        bbox_str = f"{self.bbox[0]},{self.bbox[1]},{self.bbox[2]},{self.bbox[3]},EPSG:4326"
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": type_name,
            "bbox": bbox_str,
            "outputFormat": "application/json",
        }
        resp = requests.get(WFS_BASE, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def download_geology(self) -> dict:
        data = self._wfs_request("geosgb:litoestratigrafia_estados")

        # Litho: add color per sigla
        siglas = sorted(set(f["properties"].get("sigla", "") for f in data["features"]))
        sigla_colors = {s: LITHO_PALETTE[i % len(LITHO_PALETTE)] for i, s in enumerate(siglas)}
        for feat in data["features"]:
            feat["properties"]["color"] = sigla_colors.get(feat["properties"].get("sigla", ""), "#888")

        with open(os.path.join(self.vectors_dir, "geology-litho.geojson"), "w") as f:
            json.dump(data, f)

        # Age: add color per era
        age_data = json.loads(json.dumps(data))
        for feat in age_data["features"]:
            era = feat["properties"].get("era_max", "")
            feat["properties"]["color"] = ERA_COLORS.get(era, "#888888")

        with open(os.path.join(self.vectors_dir, "geology-age.geojson"), "w") as f:
            json.dump(age_data, f)

        return data

    def download_occurrences(self) -> dict:
        data = self._wfs_request("geosgb:ocorrencias_recursos_minerais")

        for feat in data["features"]:
            subst = feat["properties"].get("substancias", "")
            feat["properties"]["color"] = "#ffd700" if "Ouro" in subst else "#aaaaaa"
            feat["properties"]["radius"] = 8 if "Ouro" in subst else 5

        with open(os.path.join(self.vectors_dir, "mineral-occurrences.geojson"), "w") as f:
            json.dump(data, f)

        return data

    def download_all(self):
        print("  Baixando geologia WFS...")
        self.download_geology()
        print("  Baixando ocorrencias minerais WFS...")
        self.download_occurrences()
        print("  CPRM download completo!")

    def get_layer(self, layer_id: str) -> dict:
        path = os.path.join(self.vectors_dir, f"{layer_id}.geojson")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def has_cache(self, layer_id: str) -> bool:
        return os.path.exists(os.path.join(self.vectors_dir, f"{layer_id}.geojson"))
```

**Step 4: Run tests**

Run: `source .venv/bin/activate && python -m pytest tests/test_cprm.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/services/cprm.py tests/test_cprm.py
git commit -m "feat: servico CPRM — download WFS geologia e ocorrencias minerais"
```

---

### Task 2: Serviço de Geofísica — parser XYZ e interpolação

**Files:**
- Create: `backend/services/geophysics.py`
- Create: `tests/test_geophysics.py`

**Step 1: Write tests**

```python
# tests/test_geophysics.py
import io
import os
import tempfile

import numpy as np
import pytest


SAMPLE_MAG_XYZ = """/ XYZ EXPORT
/ DATABASE [test]
/
/          X            Y   FIDUCIAL   GPSALT     BARO   ALTURA      MDT     MAGBASE      MAGBRU      MAGCOM      MAGCOR      MAGNIV      MAGMIC   MAGIGRF        IGRF      LONGITUDE       LATITUDE           DATA          HORA
/=========== ============ ========== ======== ======== ======== ======== =========== =========== =========== =========== =========== =========== ========= =========== ============== ============== ================ =============
/
Line  10010
   334174.95   9006391.43   66604.77   281.44   321.77    97.38   184.90   24264.192   24745.239           *           *           *           *         *   24777.932   -47.15845393   -11.68566707       2005/08/01   18:30:04.77
   334174.57   9006386.06   66604.85   281.58   321.77    97.22   185.20   24264.192   24745.293   24739.635   24775.443   24771.783   24772.030    -5.876   24777.906   -47.15845754   -11.69571567       2005/08/01   18:30:04.85
   334174.20   9006380.68   66604.93   281.72   320.06    97.08   185.47   24264.191   24745.359   24739.697   24775.507   24771.856   24772.100    -5.801   24777.902   -47.15846114   -11.70576426       2005/08/01   18:30:04.93
Line  10020
   335174.95   9006391.43   66604.77   281.44   321.77    97.38   184.90   24264.192   24745.239           *   24780.000   24776.000   24776.200    -5.500   24777.932   -47.14845393   -11.68566707       2005/08/01   18:30:04.77
   335174.57   9006386.06   66604.85   281.58   321.77    97.22   185.20   24264.192   24745.293   24739.635   24778.443   24774.783   24775.030    -5.876   24777.906   -47.14845754   -11.69571567       2005/08/01   18:30:04.85
"""

SAMPLE_GAMMA_XYZ = """/ XYZ EXPORT
/ DATABASE [test]
/
/          X            Y   GPSALT       BARO     Altura        MDT        CTB         KB         UB        THB        UUP    COSMICO       TEMP      CTCOR       KCOR       UCOR      THCOR      CTEXP      KPERC         eU        eTH   THKRAZAO    UKRAZAO   UTHRAZAO      LONGITUDE      LATITUDE      HORA  FIDUCIAL        DATA
/=========== ============ ======== ========== ========== ========== ========== ========== ========== ========== ========== ========== ========== ========== ========== ========== ========== ========== ========== ========== ========== ========== ========== ========== ============== ============= ========= ========= ===========
/
Line  10010
   334178.38   9006435.09   278.81     320.86      96.76          *    2748.00     164.00     116.00     159.00      11.00      39.56      37.83    2079.58      37.45      50.02      73.88       9.45       0.60       3.97      20.75      34.78       6.65       0.19  -47.158421093  -11.685272483  18:30:04     66604  2005/08/01
   334173.40   9006367.71   280.21     324.46      94.71     186.07    2757.00     146.00      88.00     125.00       8.00      38.70      37.82    2196.64       2.02      66.53      88.80      10.66       0.03       5.28      24.94     773.41     163.70       0.21  -47.158468848  -11.695881495  18:30:05     66605  2005/08/01
   334168.76   9006300.55   281.39     322.66      96.61     189.03    2563.00     145.00     124.00     105.00       5.00      37.00      37.82    2311.73      -0.28      79.55      97.27      11.96      -0.00       6.31      27.32    1366.09     315.66       0.23  -47.158513627  -11.706488613  18:30:06     66606  2005/08/01
"""


class TestXYZParser:
    def test_parse_mag_xyz(self):
        from backend.services.geophysics import parse_mag_xyz
        df = parse_mag_xyz(io.StringIO(SAMPLE_MAG_XYZ))
        assert len(df) >= 4
        assert "LONGITUDE" in df.columns
        assert "LATITUDE" in df.columns
        assert "MAGCOR" in df.columns

    def test_parse_gamma_xyz(self):
        from backend.services.geophysics import parse_gamma_xyz
        df = parse_gamma_xyz(io.StringIO(SAMPLE_GAMMA_XYZ))
        assert len(df) == 3
        assert "KPERC" in df.columns
        assert "eTH" in df.columns
        assert "eU" in df.columns

    def test_filter_bbox(self):
        from backend.services.geophysics import parse_gamma_xyz, filter_bbox
        df = parse_gamma_xyz(io.StringIO(SAMPLE_GAMMA_XYZ))
        filtered = filter_bbox(df, (-47.20, -11.72, -47.10, -11.68))
        assert len(filtered) <= len(df)


class TestInterpolation:
    def test_interpolate_grid(self):
        from backend.services.geophysics import interpolate_grid
        lon = np.array([-47.2, -47.1, -47.2, -47.1, -47.15])
        lat = np.array([-11.8, -11.8, -11.7, -11.7, -11.75])
        values = np.array([100.0, 200.0, 150.0, 250.0, 175.0])
        grid, transform = interpolate_grid(lon, lat, values, resolution=0.01)
        assert grid.shape[0] > 0
        assert grid.shape[1] > 0
        assert not np.all(np.isnan(grid))


class TestDerivatives:
    def test_first_vertical_derivative(self):
        from backend.services.geophysics import first_vertical_derivative
        grid = np.random.rand(64, 64)
        dx = 125.0
        result = first_vertical_derivative(grid, dx)
        assert result.shape == grid.shape

    def test_analytic_signal(self):
        from backend.services.geophysics import analytic_signal
        grid = np.random.rand(64, 64)
        dx = 125.0
        result = analytic_signal(grid, dx)
        assert result.shape == grid.shape
        assert np.all(result[~np.isnan(result)] >= 0)
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_geophysics.py -v`
Expected: FAIL

**Step 3: Implement geophysics service**

```python
# backend/services/geophysics.py
import os

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_bounds
from scipy.interpolate import griddata


def parse_mag_xyz(file_obj) -> pd.DataFrame:
    """Parse Geosoft XYZ magnético. Retorna DataFrame com LONGITUDE, LATITUDE, MAGCOR."""
    rows = []
    for line in file_obj:
        line = line.strip()
        if not line or line.startswith("/") or line.startswith("Line"):
            continue
        parts = line.split()
        if len(parts) < 18:
            continue
        try:
            lon = float(parts[-4])
            lat = float(parts[-3])
            magcor = parts[10]
            if magcor == "*":
                continue
            magcor = float(magcor)
            rows.append({"LONGITUDE": lon, "LATITUDE": lat, "MAGCOR": magcor})
        except (ValueError, IndexError):
            continue
    return pd.DataFrame(rows)


def parse_gamma_xyz(file_obj) -> pd.DataFrame:
    """Parse Geosoft XYZ gamaespectrométrico. Retorna DataFrame com LONGITUDE, LATITUDE, KPERC, eU, eTH, etc."""
    rows = []
    for line in file_obj:
        line = line.strip()
        if not line or line.startswith("/") or line.startswith("Line"):
            continue
        parts = line.split()
        if len(parts) < 28:
            continue
        try:
            lon = float(parts[24])
            lat = float(parts[25])
            kperc = float(parts[18])
            eu = float(parts[19])
            eth = float(parts[20])
            thk = float(parts[21])
            ctcor = float(parts[13])
            rows.append({
                "LONGITUDE": lon, "LATITUDE": lat,
                "KPERC": kperc, "eU": eu, "eTH": eth,
                "THKRAZAO": thk, "CTCOR": ctcor,
            })
        except (ValueError, IndexError):
            continue
    return pd.DataFrame(rows)


def filter_bbox(df: pd.DataFrame, bbox: tuple) -> pd.DataFrame:
    """Filtra DataFrame por bbox (lon_min, lat_min, lon_max, lat_max)."""
    return df[
        (df["LONGITUDE"] >= bbox[0]) & (df["LONGITUDE"] <= bbox[2]) &
        (df["LATITUDE"] >= bbox[1]) & (df["LATITUDE"] <= bbox[3])
    ].copy()


def interpolate_grid(lon, lat, values, resolution=0.00125):
    """Interpola pontos irregulares em grid regular via cubic (minimum curvature approx).

    resolution em graus (~125m ≈ 0.00125°)
    Retorna (grid_2d, rasterio_transform)
    """
    lon_min, lon_max = lon.min(), lon.max()
    lat_min, lat_max = lat.min(), lat.max()

    xi = np.arange(lon_min, lon_max + resolution, resolution)
    yi = np.arange(lat_min, lat_max + resolution, resolution)
    XI, YI = np.meshgrid(xi, yi)

    grid = griddata((lon, lat), values, (XI, YI), method="cubic")

    # Preencher NaNs de borda com nearest
    mask = np.isnan(grid)
    if mask.any():
        nearest = griddata((lon, lat), values, (XI, YI), method="nearest")
        grid[mask] = nearest[mask]

    # Flip vertical (rasterio espera norte no topo)
    grid = grid[::-1]

    transform = from_bounds(lon_min, lat_min, lon_max + resolution, lat_max + resolution, len(xi), len(yi))
    return grid, transform


def first_vertical_derivative(grid, dx):
    """1a derivada vertical via FFT."""
    ny, nx = grid.shape
    # Pad NaN com 0
    data = np.nan_to_num(grid, nan=0.0)

    F = np.fft.fft2(data)
    kx = np.fft.fftfreq(nx, d=dx)
    ky = np.fft.fftfreq(ny, d=dx)
    KX, KY = np.meshgrid(kx, ky)
    K = np.sqrt(KX**2 + KY**2)

    # 1DV = F^-1(F(data) * 2*pi*|k|)
    F_1dv = F * 2 * np.pi * K
    result = np.real(np.fft.ifft2(F_1dv))
    return result


def analytic_signal(grid, dx):
    """Amplitude do sinal analítico via FFT: sqrt(dx² + dy² + dz²)."""
    ny, nx = grid.shape
    data = np.nan_to_num(grid, nan=0.0)

    F = np.fft.fft2(data)
    kx = np.fft.fftfreq(nx, d=dx)
    ky = np.fft.fftfreq(ny, d=dx)
    KX, KY = np.meshgrid(kx, ky)
    K = np.sqrt(KX**2 + KY**2)

    # Derivadas horizontais
    dx_grid = np.real(np.fft.ifft2(F * 2j * np.pi * KX))
    dy_grid = np.real(np.fft.ifft2(F * 2j * np.pi * KY))
    dz_grid = np.real(np.fft.ifft2(F * 2 * np.pi * K))

    asa = np.sqrt(dx_grid**2 + dy_grid**2 + dz_grid**2)
    return asa


def save_cog(grid, transform, output_path, is_rgb=False):
    """Salva grid como COG (Cloud Optimized GeoTIFF)."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if is_rgb:
        count = 3
        dtype = "uint8"
    else:
        count = 1
        dtype = "float32"

    with rasterio.open(
        output_path, "w", driver="GTiff",
        height=grid.shape[-2], width=grid.shape[-1],
        count=count, dtype=dtype,
        crs="EPSG:4326", transform=transform,
    ) as dst:
        if is_rgb:
            for i in range(3):
                dst.write(grid[i], i + 1)
        else:
            dst.write(grid.astype(np.float32), 1)


class GeophysicsProcessor:
    def __init__(self, data_dir: str, bbox: tuple):
        self.data_dir = data_dir
        self.bbox = bbox
        self.processed_dir = os.path.join(data_dir, "rasters", "processed")
        self.xyz_dir = os.path.join(data_dir, "aerogeofisica", "1073_tocantins")
        os.makedirs(self.processed_dir, exist_ok=True)

    def process_all(self):
        """Processa todos os grids geofísicos a partir do XYZ bruto."""
        print("  Processando magnético...")
        self._process_mag()
        print("  Processando gamaespectrometria...")
        self._process_gamma()
        print("  Geofísica processada!")

    def _read_mag_xyz(self):
        import zipfile
        zip_path = os.path.join(self.xyz_dir, "1073-XYZ.zip")
        with zipfile.ZipFile(zip_path) as zf:
            # Ler MAGLINE_SA1 (cobre a maior parte)
            mag_files = [n for n in zf.namelist() if "MAGLINE" in n and n.endswith(".XYZ")]
            frames = []
            for mf in mag_files:
                print(f"    Lendo {mf.split('/')[-1]}...")
                with zf.open(mf) as f:
                    import io
                    text = io.TextIOWrapper(f, encoding="latin-1")
                    df = parse_mag_xyz(text)
                    frames.append(df)
            return pd.concat(frames, ignore_index=True)

    def _read_gamma_xyz(self):
        import zipfile
        zip_path = os.path.join(self.xyz_dir, "1073-XYZ.zip")
        with zipfile.ZipFile(zip_path) as zf:
            gamma_files = [n for n in zf.namelist() if "GAMALINE" in n and n.endswith(".XYZ")]
            frames = []
            for gf in gamma_files:
                print(f"    Lendo {gf.split('/')[-1]}...")
                with zf.open(gf) as f:
                    import io
                    text = io.TextIOWrapper(f, encoding="latin-1")
                    df = parse_gamma_xyz(text)
                    frames.append(df)
            return pd.concat(frames, ignore_index=True)

    def _process_mag(self):
        df = self._read_mag_xyz()
        df = filter_bbox(df, self.bbox)
        print(f"    {len(df)} pontos magnéticos na área de estudo")

        if len(df) < 10:
            print("    AVISO: poucos pontos magnéticos, pulando")
            return

        lon = df["LONGITUDE"].values
        lat = df["LATITUDE"].values
        mag = df["MAGCOR"].values

        # Grid magnético
        grid, transform = interpolate_grid(lon, lat, mag)
        save_cog(grid, transform, os.path.join(self.processed_dir, "mag-anomaly.tif"))
        print(f"    mag-anomaly: {grid.shape}")

        # Resolução em metros (~125m)
        dx = 125.0

        # 1a derivada vertical
        dv1 = first_vertical_derivative(grid, dx)
        save_cog(dv1, transform, os.path.join(self.processed_dir, "mag-1dv.tif"))
        print(f"    mag-1dv: {dv1.shape}")

        # Sinal analítico
        asa = analytic_signal(grid, dx)
        save_cog(asa, transform, os.path.join(self.processed_dir, "mag-asa.tif"))
        print(f"    mag-asa: {asa.shape}")

    def _process_gamma(self):
        df = self._read_gamma_xyz()
        df = filter_bbox(df, self.bbox)
        print(f"    {len(df)} pontos gamma na área de estudo")

        if len(df) < 10:
            print("    AVISO: poucos pontos gamma, pulando")
            return

        lon = df["LONGITUDE"].values
        lat = df["LATITUDE"].values

        # Grids individuais
        for col, layer_id in [("KPERC", "gamma-k"), ("eTH", "gamma-th"), ("THKRAZAO", "gamma-thk")]:
            values = df[col].values
            grid, transform = interpolate_grid(lon, lat, values)
            save_cog(grid, transform, os.path.join(self.processed_dir, f"{layer_id}.tif"))
            print(f"    {layer_id}: {grid.shape}")

        # Ternário K-Th-U (RGB)
        k_grid, transform = interpolate_grid(lon, lat, df["KPERC"].values)
        th_grid, _ = interpolate_grid(lon, lat, df["eTH"].values)
        u_grid, _ = interpolate_grid(lon, lat, df["eU"].values)

        def normalize_channel(arr):
            valid = arr[np.isfinite(arr)]
            if len(valid) == 0:
                return np.zeros_like(arr, dtype=np.uint8)
            p2, p98 = np.percentile(valid, [2, 98])
            clipped = np.clip(arr, p2, p98)
            return ((clipped - p2) / (p98 - p2) * 255).astype(np.uint8)

        rgb = np.stack([
            normalize_channel(k_grid),   # R = K
            normalize_channel(th_grid),  # G = Th
            normalize_channel(u_grid),   # B = U
        ])
        save_cog(rgb, transform, os.path.join(self.processed_dir, "gamma-ternary.tif"), is_rgb=True)
        print(f"    gamma-ternary: {rgb.shape}")
```

**Step 4: Run tests**

Run: `source .venv/bin/activate && python -m pytest tests/test_geophysics.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/services/geophysics.py tests/test_geophysics.py
git commit -m "feat: servico geofisica — parser XYZ, interpolacao, derivados FFT"
```

---

### Task 3: Endpoints de vetoriais e integração no layers.py

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/api/layers.py`
- Create: `tests/test_vectors.py`

**Step 1: Write tests**

```python
# tests/test_vectors.py
import json
import os
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient


def _mock_geojson():
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[-47.2, -11.7], [-47.1, -11.7], [-47.1, -11.6], [-47.2, -11.6], [-47.2, -11.7]]]},
            "properties": {"sigla": "PP4", "nome": "Test", "color": "#e6194b"}
        }]
    }


class TestVectorEndpoints:
    def setup_method(self):
        os.environ["DATA_DIR"] = tempfile.mkdtemp()
        vectors_dir = os.path.join(os.environ["DATA_DIR"], "vectors")
        os.makedirs(vectors_dir, exist_ok=True)
        with open(os.path.join(vectors_dir, "geology-litho.geojson"), "w") as f:
            json.dump(_mock_geojson(), f)

    def test_get_vector_layer(self):
        from backend.main import app
        client = TestClient(app)
        resp = client.get("/api/vectors/geology-litho")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 1

    def test_get_missing_vector(self):
        from backend.main import app
        client = TestClient(app)
        resp = client.get("/api/vectors/nonexistent")
        assert resp.status_code == 404
```

**Step 2: Implement endpoint and update layers**

Add to `backend/main.py`:
```python
@app.get("/api/vectors/{layer_id}")
def get_vector_layer(layer_id: str):
    vectors_dir = os.path.join(settings.data_dir, "vectors")
    path = os.path.join(vectors_dir, f"{layer_id}.geojson")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Layer vetorial '{layer_id}' nao encontrada")
    with open(path) as f:
        return json.load(f)
```

Update LAYERS list in `backend/api/layers.py` — replace the placeholder CPRM entries with:
```python
    # CPRM
    {"id": "geology-litho", "name": "Geologia (Litologia)", "category": "cprm", "source": "vector", "group": "CPRM"},
    {"id": "geology-age", "name": "Geologia (Idade)", "category": "cprm", "source": "vector", "group": "CPRM"},
    {"id": "mineral-occurrences", "name": "Ocorrencias Minerais", "category": "cprm", "source": "vector", "group": "CPRM"},
    # Geofísica
    {"id": "mag-anomaly", "name": "Campo Magnetico", "category": "geophysics", "source": "local", "group": "Geofisica"},
    {"id": "mag-1dv", "name": "1a Derivada Vertical", "category": "geophysics", "source": "local", "group": "Geofisica"},
    {"id": "mag-asa", "name": "Sinal Analitico", "category": "geophysics", "source": "local", "group": "Geofisica"},
    {"id": "gamma-k", "name": "Potassio (K%)", "category": "geophysics", "source": "local", "group": "Geofisica"},
    {"id": "gamma-th", "name": "Torio (eTh)", "category": "geophysics", "source": "local", "group": "Geofisica"},
    {"id": "gamma-thk", "name": "Razao Th/K", "category": "geophysics", "source": "local", "group": "Geofisica"},
    {"id": "gamma-ternary", "name": "Ternario K-Th-U", "category": "geophysics", "source": "local", "group": "Geofisica"},
```

Update `list_layers()` to handle `source == "vector"`:
```python
        elif layer["source"] == "vector":
            vectors_dir = os.path.join(settings.data_dir, "vectors")
            available = os.path.exists(os.path.join(vectors_dir, f"{layer['id']}.geojson"))
            can_generate = True  # sempre pode baixar do WFS
            supports_colormap = False
```

Add geophysics layers to LOCAL_LAYER_CONFIGS:
```python
GEOPHYSICS_CONFIGS = {
    "mag-anomaly": {"name": "Campo Magnetico", "description": "Campo magnetico anomalo (Projeto 1073 Tocantins)"},
    "mag-1dv": {"name": "1a Derivada Vertical", "description": "1a derivada vertical do campo magnetico"},
    "mag-asa": {"name": "Sinal Analitico", "description": "Amplitude do sinal analitico magnetico"},
    "gamma-k": {"name": "Potassio (K%)", "description": "Potassio percentual — gamaespectrometria"},
    "gamma-th": {"name": "Torio (eTh)", "description": "Torio equivalente (ppm) — gamaespectrometria"},
    "gamma-thk": {"name": "Razao Th/K", "description": "Razao Th/K — indicador de alteracao hidrotermal"},
    "gamma-ternary": {"name": "Ternario K-Th-U", "description": "Composicao RGB: R=K, G=Th, B=U"},
}
```

**Step 3: Run tests**

Run: `source .venv/bin/activate && python -m pytest tests/test_vectors.py tests/test_cprm.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add backend/main.py backend/api/layers.py tests/test_vectors.py
git commit -m "feat: endpoints vetoriais e novas layers CPRM/geofisica"
```

---

### Task 4: Frontend — renderização de layers vetoriais

**Files:**
- Modify: `frontend/app.js`

**Step 1: Implement vector layer support in enableLayer/disableLayer**

Na função `enableLayer`, antes de adicionar como raster, verificar se a layer é vetorial:

```javascript
async function enableLayer(layerId, checkbox) {
    const layer = layersData.find(l => l.id === layerId);

    if (layer && layer.source === "vector") {
        await enableVectorLayer(layerId, layer, checkbox);
        return;
    }
    // ... resto do código existente para raster
}
```

Adicionar funções para layers vetoriais:

```javascript
async function enableVectorLayer(layerId, layer, checkbox) {
    updateStatus(`Carregando ${layer.name}...`);
    try {
        const geojson = await fetch(`/api/vectors/${layerId}`).then(r => {
            if (!r.ok) throw new Error(`Erro ${r.status}`);
            return r.json();
        });

        const sourceId = `layer-${layerId}`;

        if (map.getSource(sourceId)) {
            // Remove all sublayers
            [`${sourceId}-fill`, `${sourceId}-line`, `${sourceId}-circle`].forEach(id => {
                if (map.getLayer(id)) map.removeLayer(id);
            });
            map.removeSource(sourceId);
        }

        map.addSource(sourceId, { type: "geojson", data: geojson });

        if (layerId.includes("occurrence")) {
            // Points
            map.addLayer({
                id: `${sourceId}-circle`,
                type: "circle",
                source: sourceId,
                paint: {
                    "circle-radius": ["get", "radius"],
                    "circle-color": ["get", "color"],
                    "circle-stroke-color": "#fff",
                    "circle-stroke-width": 1,
                    "circle-opacity": 0.9,
                }
            }, "study-area-fill");

            // Popup on click
            map.on("click", `${sourceId}-circle`, (e) => {
                const props = e.features[0].properties;
                new maplibregl.Popup()
                    .setLngLat(e.lngLat)
                    .setHTML(`<strong>${props.substancias || "?"}</strong><br>
                        ${props.toponimia || ""}<br>
                        ${props.status_economico || ""} — ${props.importancia || ""}`)
                    .addTo(map);
            });
            map.on("mouseenter", `${sourceId}-circle`, () => map.getCanvas().style.cursor = "pointer");
            map.on("mouseleave", `${sourceId}-circle`, () => map.getCanvas().style.cursor = "");
        } else {
            // Polygons (geology)
            map.addLayer({
                id: `${sourceId}-fill`,
                type: "fill",
                source: sourceId,
                paint: {
                    "fill-color": ["get", "color"],
                    "fill-opacity": 0.4,
                }
            }, "study-area-fill");

            map.addLayer({
                id: `${sourceId}-line`,
                type: "line",
                source: sourceId,
                paint: {
                    "line-color": ["get", "color"],
                    "line-width": 1,
                    "line-opacity": 0.8,
                }
            }, "study-area-fill");

            // Popup on click
            map.on("click", `${sourceId}-fill`, (e) => {
                const props = e.features[0].properties;
                new maplibregl.Popup()
                    .setLngLat(e.lngLat)
                    .setHTML(`<strong>${props.sigla || ""}</strong><br>
                        ${props.nome || ""}<br>
                        <em>${props.litotipos || ""}</em>`)
                    .addTo(map);
            });
            map.on("mouseenter", `${sourceId}-fill`, () => map.getCanvas().style.cursor = "pointer");
            map.on("mouseleave", `${sourceId}-fill`, () => map.getCanvas().style.cursor = "");
        }

        activeLayers[layerId] = sourceId;
        if (!layerProps[layerId]) layerProps[layerId] = getDefaultProps();
        selectLayer(layerId);
        updateStatus(`${layer.name} carregada`);
    } catch (err) {
        checkbox.checked = false;
        updateStatus(`Erro: ${err.message}`);
    }
}
```

Atualizar `disableLayer` para remover sublayers vetoriais:

```javascript
function disableLayer(layerId) {
    const sourceId = `layer-${layerId}`;
    // Remove all possible sublayers
    [`${sourceId}`, `${sourceId}-fill`, `${sourceId}-line`, `${sourceId}-circle`].forEach(id => {
        if (map.getLayer(id)) map.removeLayer(id);
    });
    if (map.getSource(sourceId)) map.removeSource(sourceId);
    delete activeLayers[layerId];
    // ... resto igual
}
```

Atualizar `applyMapLibreProps` para suportar layers vetoriais (opacidade):

```javascript
// No applyMapLibreProps, para layers vetoriais:
const layer = layersData.find(l => l.id === layerId);
if (layer && layer.source === "vector") {
    const fillId = `${sourceId}-fill`;
    const circleId = `${sourceId}-circle`;
    if (map.getLayer(fillId)) {
        map.setPaintProperty(fillId, "fill-opacity", p.opacity / 100 * 0.6);
    }
    if (map.getLayer(circleId)) {
        map.setPaintProperty(circleId, "circle-opacity", p.opacity / 100);
    }
    return;
}
```

**Step 2: Test manually no browser**

**Step 3: Commit**

```bash
git add frontend/app.js
git commit -m "feat: frontend — renderizacao de layers vetoriais (geologia + ocorrencias)"
```

---

### Task 5: Integrar processamento e preload

**Files:**
- Modify: `backend/api/layers.py`
- Modify: `backend/main.py`

**Step 1: Atualizar preload_layers para registrar COGs geofísicos e gerar vetoriais**

No `preload_layers`, adicionar registro de COGs geofísicos (mesma lógica dos LOCAL_LAYER_CONFIGS) e download WFS se não houver cache:

```python
# Em preload_layers, após registrar COGs locais e GEE:

# 3. Registrar COGs geofísicos
for layer_id, config in GEOPHYSICS_CONFIGS.items():
    cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
    if os.path.exists(cog_path) and os.path.getsize(cog_path) > 0:
        try:
            is_rgb = layer_id == "gamma-ternary"
            tile_service.register_cog(layer_id, cog_path, is_rgb=is_rgb)
            _generated_tiles[layer_id] = {
                "layer_id": layer_id,
                "name": config["name"],
                "description": config["description"],
                "tile_url": f"/api/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png",
            }
            print(f"  Geofisica registrada: {layer_id}")
        except Exception as e:
            print(f"  AVISO: COG geofisico corrompido {layer_id}: {e}")

# 4. Baixar vetoriais WFS se não houver cache
vectors_dir = os.path.join(settings.data_dir, "vectors")
from backend.services.cprm import CPRMService
bbox = (
    settings.study_area_center_lon - settings.study_area_radius_km / 111.32,
    settings.study_area_center_lat - settings.study_area_radius_km / 111.32,
    settings.study_area_center_lon + settings.study_area_radius_km / 111.32,
    settings.study_area_center_lat + settings.study_area_radius_km / 111.32,
)
cprm = CPRMService(vectors_dir=vectors_dir, bbox=bbox)
for vid in ["geology-litho", "geology-age", "mineral-occurrences"]:
    if not cprm.has_cache(vid):
        try:
            if "geology" in vid:
                cprm.download_geology()
            else:
                cprm.download_occurrences()
        except Exception as e:
            print(f"  AVISO: falha WFS {vid}: {e}")
```

Adicionar endpoint `generate_layer` para layers vetoriais e geofísica:

```python
# No generate_layer, adicionar caso para vetoriais:
if layer_id in ("geology-litho", "geology-age", "mineral-occurrences"):
    vectors_dir = os.path.join(settings.data_dir, "vectors")
    cprm = CPRMService(vectors_dir=vectors_dir, bbox=bbox)
    if not cprm.has_cache(layer_id):
        if "geology" in layer_id:
            cprm.download_geology()
        else:
            cprm.download_occurrences()
    return {"layer_id": layer_id, "name": layer_id, "vector": True}
```

**Step 2: Adicionar endpoint de processamento geofísico**

Em `backend/main.py`:
```python
@app.post("/api/geophysics/process")
def process_geophysics():
    from backend.services.geophysics import GeophysicsProcessor
    bbox = (
        settings.study_area_center_lon - settings.study_area_radius_km / 111.32,
        settings.study_area_center_lat - settings.study_area_radius_km / 111.32,
        settings.study_area_center_lon + settings.study_area_radius_km / 111.32,
        settings.study_area_center_lat + settings.study_area_radius_km / 111.32,
    )
    processor = GeophysicsProcessor(data_dir=settings.data_dir, bbox=bbox)
    processor.process_all()
    preload_layers(tile_service)
    return {"status": "ok"}
```

**Step 3: Run all tests**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`
Expected: PASS

**Step 4: Commit**

```bash
git add backend/api/layers.py backend/main.py
git commit -m "feat: integrar geofisica e vetoriais no preload e endpoints"
```

---

### Task 6: Processar dados e testar end-to-end

**Step 1: Processar geofísica localmente**

```bash
source .venv/bin/activate
python -c "
from backend.services.geophysics import GeophysicsProcessor
bbox = (-47.38, -11.93, -46.93, -11.47)
proc = GeophysicsProcessor(data_dir='data', bbox=bbox)
proc.process_all()
"
```

**Step 2: Baixar vetoriais WFS**

```bash
python -c "
from backend.services.cprm import CPRMService
bbox = (-47.38, -11.93, -46.93, -11.47)
svc = CPRMService(vectors_dir='data/vectors', bbox=bbox)
svc.download_all()
"
```

**Step 3: Iniciar servidor e testar no browser**

```bash
python -m backend.main
# Abrir http://localhost:8000
# Testar: ativar geology-litho, geology-age, mineral-occurrences
# Testar: ativar mag-anomaly, gamma-k, gamma-ternary
```

**Step 4: Run all tests**

```bash
python -m pytest tests/ -v
```

**Step 5: Commit final**

```bash
git add -A
git commit -m "feat: Fase 4 completa — CPRM/SGB + aerogeofisica processada"
git push
```

---
