"""Testes do servico de geofisica: parser XYZ, interpolacao, derivados FFT."""

import io

import numpy as np
import pytest

from backend.services.geophysics import (
    analytic_signal,
    filter_bbox,
    first_vertical_derivative,
    interpolate_grid,
    parse_gamma_xyz,
    parse_mag_xyz,
)


# --- Fixtures com dados no formato real Geosoft XYZ ---


MAG_SAMPLE = """\
/ MAGLINE HEADER
/ Projeto 1073
Line     10010
  1  2  3  4  5  6  7  8  9  10  25432.5  11  12  -47.1000  -11.7000  99.0  100.0
  1  2  3  4  5  6  7  8  9  10  25433.1  11  12  -47.1010  -11.7010  99.0  100.0
  1  2  3  4  5  6  7  8  9  10  *  11  12  -47.1020  -11.7020  99.0  100.0
Line     10020
  1  2  3  4  5  6  7  8  9  10  25500.0  11  12  -47.1100  -11.7100  99.0  100.0
"""

GAMMA_SAMPLE = """\
/ GAMALINE HEADER
/ Projeto 1073
Line     20010
  0  1  2  3  4  5  6  7  8  9  10  11  12  150.5  14  15  16  17  2.50  0.80  12.3  5.0  22  23  -47.1500  -11.8000
  0  1  2  3  4  5  6  7  8  9  10  11  12  155.0  14  15  16  17  3.10  1.20  15.1  4.8  22  23  -47.1510  -11.8010
Line     20020
  0  1  2  3  4  5  6  7  8  9  10  11  12  148.2  14  15  16  17  2.80  0.95  13.7  4.9  22  23  -47.1600  -11.8100
"""


def test_parse_mag_xyz():
    """Parse magnetico deve extrair LONGITUDE, LATITUDE, MAGCOR e ignorar * e headers."""
    f = io.StringIO(MAG_SAMPLE)
    df = parse_mag_xyz(f)
    assert len(df) == 3  # 4 linhas de dados, 1 com * = 3 validas
    assert list(df.columns) == ["LONGITUDE", "LATITUDE", "MAGCOR"]
    assert df.iloc[0]["LONGITUDE"] == pytest.approx(-47.1000)
    assert df.iloc[0]["LATITUDE"] == pytest.approx(-11.7000)
    assert df.iloc[0]["MAGCOR"] == pytest.approx(25432.5)
    # Linha com * deve ser ignorada
    assert not df["MAGCOR"].isna().any()


def test_parse_gamma_xyz():
    """Parse gamma deve extrair LONGITUDE, LATITUDE, KPERC, eU, eTH, THKRAZAO, CTCOR."""
    f = io.StringIO(GAMMA_SAMPLE)
    df = parse_gamma_xyz(f)
    assert len(df) == 3
    assert list(df.columns) == [
        "LONGITUDE", "LATITUDE", "KPERC", "eU", "eTH", "THKRAZAO", "CTCOR"
    ]
    assert df.iloc[0]["LONGITUDE"] == pytest.approx(-47.1500)
    assert df.iloc[0]["LATITUDE"] == pytest.approx(-11.8000)
    assert df.iloc[0]["KPERC"] == pytest.approx(2.50)
    assert df.iloc[0]["eU"] == pytest.approx(0.80)
    assert df.iloc[0]["eTH"] == pytest.approx(12.3)
    assert df.iloc[0]["THKRAZAO"] == pytest.approx(5.0)
    assert df.iloc[0]["CTCOR"] == pytest.approx(150.5)


def test_parse_mag_xyz_bytes():
    """Parse deve funcionar com file-like retornando bytes (como ZipFile)."""
    f = io.BytesIO(MAG_SAMPLE.encode("utf-8"))
    df = parse_mag_xyz(f)
    assert len(df) == 3


def test_filter_bbox():
    """Filtra pontos por bounding box."""
    import pandas as pd

    df = pd.DataFrame({
        "LONGITUDE": [-47.1, -47.2, -47.5, -46.9],
        "LATITUDE": [-11.7, -11.8, -11.9, -11.5],
        "MAGCOR": [100, 200, 300, 400],
    })
    bbox = (-47.15, -11.75, -46.85, -11.45)
    filtered = filter_bbox(df, bbox)
    assert len(filtered) == 2  # -47.1/-11.7 e -46.9/-11.5
    assert -47.5 not in filtered["LONGITUDE"].values
    assert -47.2 not in filtered["LONGITUDE"].values


def test_interpolate_grid():
    """Interpolacao com dados sinteticos deve gerar grid finito."""
    np.random.seed(42)
    n = 200
    lon = np.random.uniform(-47.2, -47.0, n)
    lat = np.random.uniform(-11.8, -11.6, n)
    values = np.sin(lon * 100) + np.cos(lat * 100)

    bbox = (-47.2, -11.8, -47.0, -11.6)
    grid, transform = interpolate_grid(lon, lat, values, resolution=0.005, bbox=bbox)

    assert grid.ndim == 2
    assert grid.dtype == np.float32
    # Grid deve ter dimensoes baseadas no bbox e resolucao
    expected_nx = len(np.arange(-47.2, -47.0 + 0.005 / 2, 0.005))
    expected_ny = len(np.arange(-11.8, -11.6 + 0.005 / 2, 0.005))
    assert grid.shape == (expected_ny, expected_nx)
    # Sem NaNs (nearest preenche borda)
    assert np.all(np.isfinite(grid))
    # Transform valido
    assert transform is not None


def test_first_vertical_derivative():
    """1DV deve preservar shape e produzir resultado finito."""
    np.random.seed(42)
    grid = np.random.rand(100, 100).astype(np.float32)
    dx = 125.0  # metros

    result = first_vertical_derivative(grid, dx)
    assert result.shape == grid.shape
    assert result.dtype == np.float32
    assert np.all(np.isfinite(result))


def test_analytic_signal():
    """ASA deve preservar shape e produzir valores >= 0."""
    np.random.seed(42)
    grid = np.random.rand(100, 100).astype(np.float32)
    dx = 125.0

    result = analytic_signal(grid, dx)
    assert result.shape == grid.shape
    assert result.dtype == np.float32
    assert np.all(np.isfinite(result))
    assert np.all(result >= -1e-6)  # tolerancia numerica
