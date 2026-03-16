"""Servico de geofisica: parser XYZ, interpolacao, derivados FFT.

Processa dados XYZ brutos de aerogeofisica (magnetometria e gamaespectrometria)
em grids interpolados salvos como COGs.
"""

import logging
import os
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from scipy.interpolate import griddata

logger = logging.getLogger(__name__)


def parse_mag_xyz(file_obj) -> pd.DataFrame:
    """Parse arquivo magnetico Geosoft XYZ.

    Args:
        file_obj: File-like object com conteudo XYZ.

    Returns:
        DataFrame com colunas LONGITUDE, LATITUDE, MAGCOR.
    """
    rows = []
    for line in file_obj:
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        line = line.strip()
        if not line or line.startswith("/") or line.lower().startswith("line"):
            continue
        parts = line.split()
        if len(parts) < 11:
            continue
        try:
            magcor = parts[10]
            if magcor == "*":
                continue
            lon = float(parts[-4])
            lat = float(parts[-3])
            mag = float(magcor)
            rows.append((lon, lat, mag))
        except (ValueError, IndexError):
            continue
    return pd.DataFrame(rows, columns=["LONGITUDE", "LATITUDE", "MAGCOR"])


def parse_gamma_xyz(file_obj) -> pd.DataFrame:
    """Parse arquivo gamaespectrometrico Geosoft XYZ.

    Args:
        file_obj: File-like object com conteudo XYZ.

    Returns:
        DataFrame com colunas LONGITUDE, LATITUDE, KPERC, eU, eTH, THKRAZAO, CTCOR.
    """
    rows = []
    for line in file_obj:
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        line = line.strip()
        if not line or line.startswith("/") or line.lower().startswith("line"):
            continue
        parts = line.split()
        if len(parts) < 26:
            continue
        try:
            lon = float(parts[24])
            lat = float(parts[25])
            kperc = float(parts[18])
            eu = float(parts[19])
            eth = float(parts[20])
            thkrazao = float(parts[21])
            ctcor = float(parts[13])
            rows.append((lon, lat, kperc, eu, eth, thkrazao, ctcor))
        except (ValueError, IndexError):
            continue
    return pd.DataFrame(
        rows, columns=["LONGITUDE", "LATITUDE", "KPERC", "eU", "eTH", "THKRAZAO", "CTCOR"]
    )


def filter_bbox(df: pd.DataFrame, bbox: Tuple[float, float, float, float]) -> pd.DataFrame:
    """Filtra DataFrame por bounding box (lon_min, lat_min, lon_max, lat_max)."""
    lon_min, lat_min, lon_max, lat_max = bbox
    mask = (
        (df["LONGITUDE"] >= lon_min)
        & (df["LONGITUDE"] <= lon_max)
        & (df["LATITUDE"] >= lat_min)
        & (df["LATITUDE"] <= lat_max)
    )
    return df[mask].copy()


def interpolate_grid(
    lon: np.ndarray,
    lat: np.ndarray,
    values: np.ndarray,
    resolution: float = 0.00125,
    bbox: Optional[Tuple[float, float, float, float]] = None,
) -> Tuple[np.ndarray, rasterio.transform.Affine]:
    """Interpola pontos irregulares em grid regular.

    Args:
        lon: Array de longitudes.
        lat: Array de latitudes.
        values: Array de valores.
        resolution: Resolucao do grid em graus (~125m).
        bbox: (lon_min, lat_min, lon_max, lat_max). Se None, usa extent dos dados.

    Returns:
        Tuple (grid_2d, rasterio_transform).
        Grid orientado com norte no topo (lat decrescente de cima para baixo).
    """
    if bbox is not None:
        lon_min, lat_min, lon_max, lat_max = bbox
    else:
        lon_min, lat_min = lon.min(), lat.min()
        lon_max, lat_max = lon.max(), lat.max()

    grid_lon = np.arange(lon_min, lon_max + resolution / 2, resolution)
    grid_lat = np.arange(lat_min, lat_max + resolution / 2, resolution)
    grid_x, grid_y = np.meshgrid(grid_lon, grid_lat)

    points = np.column_stack((lon, lat))

    # Interpolacao cubic
    grid = griddata(points, values, (grid_x, grid_y), method="cubic")

    # Preencher NaNs de borda com nearest
    nan_mask = np.isnan(grid)
    if nan_mask.any():
        nearest = griddata(points, values, (grid_x, grid_y), method="nearest")
        grid[nan_mask] = nearest[nan_mask]

    # Flip vertical: rasterio espera norte no topo (row 0 = lat_max)
    grid = np.flipud(grid).astype(np.float32)

    height, width = grid.shape
    transform = from_bounds(lon_min, lat_min, lon_max, lat_max, width, height)

    return grid, transform


def first_vertical_derivative(grid: np.ndarray, dx: float) -> np.ndarray:
    """Calcula primeira derivada vertical (1DV) via FFT.

    F^-1(F(data) * 2*pi*|k|)

    Args:
        grid: Array 2D com dados interpolados.
        dx: Espacamento do grid em metros.

    Returns:
        Array 2D com a primeira derivada vertical.
    """
    ny, nx = grid.shape

    # Frequencias espaciais
    kx = np.fft.fftfreq(nx, d=dx)
    ky = np.fft.fftfreq(ny, d=dx)
    KX, KY = np.meshgrid(kx, ky)
    K = np.sqrt(KX**2 + KY**2)

    # FFT 2D
    F = np.fft.fft2(grid)

    # Filtro 1DV: multiplicar por 2*pi*|k|
    filt = 2.0 * np.pi * K
    F_deriv = F * filt

    # Inversa
    result = np.real(np.fft.ifft2(F_deriv)).astype(np.float32)
    return result


def analytic_signal(grid: np.ndarray, dx: float) -> np.ndarray:
    """Calcula amplitude do sinal analitico (ASA) via FFT.

    ASA = sqrt(dT/dx^2 + dT/dy^2 + dT/dz^2)

    Args:
        grid: Array 2D com dados interpolados.
        dx: Espacamento do grid em metros.

    Returns:
        Array 2D com a amplitude do sinal analitico (>= 0).
    """
    ny, nx = grid.shape

    kx = np.fft.fftfreq(nx, d=dx)
    ky = np.fft.fftfreq(ny, d=dx)
    KX, KY = np.meshgrid(kx, ky)
    K = np.sqrt(KX**2 + KY**2)

    F = np.fft.fft2(grid)

    # Derivadas horizontais via FFT: multiplicar por i*2*pi*k
    dTdx = np.real(np.fft.ifft2(F * (1j * 2.0 * np.pi * KX)))
    dTdy = np.real(np.fft.ifft2(F * (1j * 2.0 * np.pi * KY)))

    # Derivada vertical
    dTdz = np.real(np.fft.ifft2(F * (2.0 * np.pi * K)))

    result = np.sqrt(dTdx**2 + dTdy**2 + dTdz**2).astype(np.float32)
    return result


def save_cog(
    grid: np.ndarray,
    transform: rasterio.transform.Affine,
    output_path: str,
    is_rgb: bool = False,
) -> None:
    """Salva array como GeoTIFF COG (tiled + comprimido).

    Args:
        grid: Array 2D (height, width) ou 3D (count, height, width).
        transform: Affine transform do raster.
        output_path: Caminho de saida.
        is_rgb: Se True, espera 3 bandas uint8.
    """
    if grid.ndim == 2:
        grid = grid[np.newaxis, :]
    count, height, width = grid.shape

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=count,
        dtype=grid.dtype,
        crs=CRS.from_epsg(4326),
        transform=transform,
        tiled=True,
        blockxsize=256,
        blockysize=256,
        compress="deflate",
    ) as dst:
        dst.write(grid)


class GeophysicsProcessor:
    """Processador de dados aerogeofisicos XYZ -> COGs interpolados."""

    def __init__(self, data_dir: str, bbox: Tuple[float, float, float, float]):
        """
        Args:
            data_dir: Diretorio raiz dos dados (contem aerogeofisica/).
            bbox: (lon_min, lat_min, lon_max, lat_max) da area de estudo.
        """
        self.data_dir = data_dir
        self.bbox = bbox
        self.output_dir = os.path.join(data_dir, "rasters", "processed")
        self.zip_path = os.path.join(
            data_dir, "aerogeofisica", "1073_tocantins", "1073-XYZ.zip"
        )
        self.resolution = 0.00125  # ~125m

    def process_all(self) -> dict:
        """Processa todos os produtos geofisicos.

        Returns:
            Dict com layer_id -> caminho do COG gerado.
        """
        results = {}
        logger.info("Processando magnetometria...")
        mag_results = self._process_mag()
        results.update(mag_results)

        logger.info("Processando gamaespectrometria...")
        gamma_results = self._process_gamma()
        results.update(gamma_results)

        logger.info("Geofisica concluida: %d COGs gerados", len(results))
        return results

    def _process_mag(self) -> dict:
        """Processa magnetometria: MAGCOR -> anomalia, 1DV, ASA."""
        import io
        import zipfile

        results = {}
        df_list = []

        with zipfile.ZipFile(self.zip_path, "r") as zf:
            for name in zf.namelist():
                if name.upper().endswith("_MAGLINE_SA1.XYZ") or name.upper().endswith(
                    "_MAGLINE_SA2.XYZ"
                ):
                    logger.info("Lendo %s", name)
                    with zf.open(name) as f:
                        wrapper = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
                        df = parse_mag_xyz(wrapper)
                        df_list.append(df)

        if not df_list:
            logger.warning("Nenhum arquivo magnetico encontrado no ZIP")
            return results

        df_all = pd.concat(df_list, ignore_index=True)
        logger.info("Pontos magneticos totais: %d", len(df_all))

        df_bbox = filter_bbox(df_all, self.bbox)
        logger.info("Pontos apos filtro bbox: %d", len(df_bbox))

        if len(df_bbox) < 10:
            logger.warning("Poucos pontos magneticos na bbox, pulando")
            return results

        lon = df_bbox["LONGITUDE"].values
        lat = df_bbox["LATITUDE"].values
        mag = df_bbox["MAGCOR"].values

        grid, transform = interpolate_grid(lon, lat, mag, self.resolution, self.bbox)
        logger.info("Grid magnetico: %s", grid.shape)

        # Espacamento em metros (~125m)
        dx = self.resolution * 111000  # graus -> metros aproximado

        # Anomalia magnetica
        path_anom = os.path.join(self.output_dir, "mag-anomaly.tif")
        save_cog(grid, transform, path_anom)
        results["mag-anomaly"] = path_anom
        logger.info("Salvo: %s", path_anom)

        # Primeira derivada vertical
        dv1 = first_vertical_derivative(grid, dx)
        path_1dv = os.path.join(self.output_dir, "mag-1dv.tif")
        save_cog(dv1, transform, path_1dv)
        results["mag-1dv"] = path_1dv
        logger.info("Salvo: %s", path_1dv)

        # Sinal analitico
        asa = analytic_signal(grid, dx)
        path_asa = os.path.join(self.output_dir, "mag-asa.tif")
        save_cog(asa, transform, path_asa)
        results["mag-asa"] = path_asa
        logger.info("Salvo: %s", path_asa)

        return results

    def _process_gamma(self) -> dict:
        """Processa gamaespectrometria: K, Th, Th/K, ternario RGB."""
        import io
        import zipfile

        results = {}

        with zipfile.ZipFile(self.zip_path, "r") as zf:
            gamma_name = None
            for name in zf.namelist():
                if name.upper().endswith("_GAMALINE.XYZ"):
                    gamma_name = name
                    break

            if gamma_name is None:
                logger.warning("Arquivo GAMALINE nao encontrado no ZIP")
                return results

            logger.info("Lendo %s", gamma_name)
            with zf.open(gamma_name) as f:
                wrapper = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
                df = parse_gamma_xyz(wrapper)

        logger.info("Pontos gamma totais: %d", len(df))

        df_bbox = filter_bbox(df, self.bbox)
        logger.info("Pontos apos filtro bbox: %d", len(df_bbox))

        if len(df_bbox) < 10:
            logger.warning("Poucos pontos gamma na bbox, pulando")
            return results

        lon = df_bbox["LONGITUDE"].values
        lat = df_bbox["LATITUDE"].values

        # Potassio (K%)
        k_grid, transform = interpolate_grid(
            lon, lat, df_bbox["KPERC"].values, self.resolution, self.bbox
        )
        path_k = os.path.join(self.output_dir, "gamma-k.tif")
        save_cog(k_grid, transform, path_k)
        results["gamma-k"] = path_k

        # Torio (eTh)
        th_grid, transform = interpolate_grid(
            lon, lat, df_bbox["eTH"].values, self.resolution, self.bbox
        )
        path_th = os.path.join(self.output_dir, "gamma-th.tif")
        save_cog(th_grid, transform, path_th)
        results["gamma-th"] = path_th

        # Razao Th/K
        thk_grid, transform = interpolate_grid(
            lon, lat, df_bbox["THKRAZAO"].values, self.resolution, self.bbox
        )
        path_thk = os.path.join(self.output_dir, "gamma-thk.tif")
        save_cog(thk_grid, transform, path_thk)
        results["gamma-thk"] = path_thk

        # Ternario RGB: R=K, G=Th, B=U (normalizado p2/p98 -> 0-255)
        eu_grid, _ = interpolate_grid(
            lon, lat, df_bbox["eU"].values, self.resolution, self.bbox
        )

        def _normalize_to_uint8(arr: np.ndarray) -> np.ndarray:
            """Normaliza array para 0-255 uint8 usando percentis p2/p98."""
            valid = arr[np.isfinite(arr)]
            if len(valid) == 0:
                return np.zeros_like(arr, dtype=np.uint8)
            p2, p98 = np.percentile(valid, [2, 98])
            if p98 <= p2:
                return np.zeros_like(arr, dtype=np.uint8)
            clipped = np.clip(arr, p2, p98)
            scaled = ((clipped - p2) / (p98 - p2) * 255).astype(np.uint8)
            return scaled

        r = _normalize_to_uint8(k_grid)
        g = _normalize_to_uint8(th_grid)
        b = _normalize_to_uint8(eu_grid)

        ternary = np.stack([r, g, b], axis=0)  # (3, H, W)
        path_tern = os.path.join(self.output_dir, "gamma-ternary.tif")
        save_cog(ternary, transform, path_tern, is_rgb=True)
        results["gamma-ternary"] = path_tern

        logger.info("Gamma: 4 COGs salvos")
        return results
