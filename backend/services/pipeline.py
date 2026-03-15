"""Pipeline completo ASTER: download + composite + processamento."""

import math
import os
from typing import Dict, List, Tuple

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from rasterio.warp import calculate_default_transform, reproject, Resampling
from scipy.ndimage import median_filter

from backend.services.aster import AsterService, BAND_SUFFIXES
from backend.services.processing import ProcessingService


LAYER_PRODUCT_MAP = {
    "crosta-feox": "AST_07XT",
    "crosta-oh": "AST_07XT",
    "ninomiya-aloh": "AST_07XT",
    "ninomiya-mgoh": "AST_07XT",
    "ninomiya-ferrous": "AST_07XT",
    "pca-tir": "AST_05",
}

PRODUCT_DATE_RANGES = {
    "AST_07XT": ("2000-01-01", "2008-04-01"),
    "AST_05": ("2000-01-01", "2024-12-31"),
}

# Ordem das bandas no composite multi-banda
BAND_ORDER = {
    "AST_07XT": [
        "SRF_VNIR_B01", "SRF_VNIR_B02", "SRF_VNIR_B03N",
        "SRF_SWIR_B04", "SRF_SWIR_B05", "SRF_SWIR_B06",
        "SRF_SWIR_B07", "SRF_SWIR_B08", "SRF_SWIR_B09",
    ],
    "AST_05": [
        "SRE_TIR_B10", "SRE_TIR_B11", "SRE_TIR_B12",
        "SRE_TIR_B13", "SRE_TIR_B14",
    ],
}


class AsterPipeline:
    """Orquestra download ASTER -> composite -> processamento -> COGs."""

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

    def _get_ndvi_path(self) -> str:
        return os.path.join(self.data_dir, "aster", "composite", "AST_07XT_ndvi.tif")

    def _compute_ref_grid(
        self, res_deg: float = 0.00027
    ) -> Tuple[CRS, rasterio.transform.Affine, int, int]:
        """Calcula grid de referencia em EPSG:4326 para a AOI.

        Args:
            res_deg: Resolucao em graus (~30m no equador).

        Returns:
            (crs, transform, height, width)
        """
        dlat = self.radius_km / 111.32
        dlon = self.radius_km / (111.32 * math.cos(math.radians(self.center_lat)))
        west = self.center_lon - dlon
        east = self.center_lon + dlon
        south = self.center_lat - dlat
        north = self.center_lat + dlat

        width = int(round((east - west) / res_deg))
        height = int(round((north - south) / res_deg))
        transform = from_bounds(west, south, east, north, width, height)
        return CRS.from_epsg(4326), transform, height, width

    def _build_band_composite(
        self,
        scenes: List[Dict[str, str]],
        band_name: str,
        ref_crs: CRS,
        ref_transform: rasterio.transform.Affine,
        ref_height: int,
        ref_width: int,
    ) -> np.ndarray:
        """Calcula mediana de uma banda reprojetando cada cena para o grid comum."""
        band_arrays = []
        for scene in scenes:
            if band_name not in scene:
                continue
            with rasterio.open(scene[band_name]) as src:
                dst = np.empty((ref_height, ref_width), dtype=np.float32)
                reproject(
                    source=rasterio.band(src, 1),
                    destination=dst,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=ref_transform,
                    dst_crs=ref_crs,
                    resampling=Resampling.bilinear,
                    dst_nodata=np.nan,
                )
                band_arrays.append(dst)

        if not band_arrays:
            raise ValueError(f"Nenhuma cena com banda {band_name}")

        stacked = np.stack(band_arrays, axis=0)
        stacked[stacked <= 0] = np.nan

        # Normalizar cada cena para mesma media/std antes da mediana
        # Remove artefatos de borda de cena (diferentes subsets = valores diferentes)
        global_mean = np.nanmean(stacked)
        global_std = np.nanstd(stacked)
        for i in range(stacked.shape[0]):
            scene = stacked[i]
            valid = np.isfinite(scene)
            if valid.any():
                s_mean = np.nanmean(scene)
                s_std = np.nanstd(scene)
                if s_std > 0:
                    stacked[i] = (scene - s_mean) / s_std * global_std + global_mean

        return np.nanmedian(stacked, axis=0).astype(np.float32)

    def _build_ndvi_composite(
        self,
        scenes: List[Dict[str, str]],
        ref_crs: CRS,
        ref_transform: rasterio.transform.Affine,
        ref_height: int,
        ref_width: int,
    ) -> np.ndarray:
        """Computa NDVI por cena (pre-normalizacao) e retorna mediana.

        Mais preciso que computar NDVI do composite normalizado, pois
        a normalizacao mean/std por banda distorce as relacoes inter-banda.
        """
        ndvi_arrays = []
        for scene in scenes:
            if "SRF_VNIR_B02" not in scene or "SRF_VNIR_B03N" not in scene:
                continue
            red = np.empty((ref_height, ref_width), dtype=np.float32)
            nir = np.empty((ref_height, ref_width), dtype=np.float32)
            for band_name, dst in [("SRF_VNIR_B02", red), ("SRF_VNIR_B03N", nir)]:
                with rasterio.open(scene[band_name]) as src:
                    reproject(
                        source=rasterio.band(src, 1),
                        destination=dst,
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=ref_transform,
                        dst_crs=ref_crs,
                        resampling=Resampling.bilinear,
                        dst_nodata=np.nan,
                    )
            valid = (nir + red) > 0
            with np.errstate(divide="ignore", invalid="ignore"):
                ndvi = np.where(valid, (nir - red) / (nir + red), np.nan)
            ndvi_arrays.append(ndvi)

        if not ndvi_arrays:
            raise ValueError("Nenhuma cena com B02+B03N para NDVI")

        stacked = np.stack(ndvi_arrays, axis=0)
        return np.nanmedian(stacked, axis=0).astype(np.float32)

    @staticmethod
    def _get_scene_month(scene: Dict[str, str]) -> int:
        """Extrai mes da cena a partir do nome do arquivo (AST_07XT_004MMDD...)."""
        path = next(iter(scene.values()))
        filename = os.path.basename(path)
        # Formato: AST_07XT_004MMDDYYYY... → MM nos chars 12-13
        return int(filename[12:14])

    def _build_ndvi_from_scenes(self, scenes: List[Dict[str, str]]) -> None:
        """Gera composite NDVI pre-normalizacao a partir de cenas AST_07XT.

        Filtra apenas cenas da estacao seca (ago-out) para consistencia
        com a mascara GEE Fase 2 (Sentinel-2 ago-out). O composite das
        bandas espectrais continua usando TODAS as cenas.
        """
        ndvi_path = self._get_ndvi_path()
        if os.path.exists(ndvi_path):
            return

        # Filtrar cenas da estacao seca (ago=8, set=9, out=10)
        dry_scenes = [s for s in scenes if self._get_scene_month(s) in (8, 9, 10)]
        print(f"  NDVI: {len(dry_scenes)} cenas seca (ago-out) de {len(scenes)} total")

        if not dry_scenes:
            print("  AVISO: Nenhuma cena seca, usando todas as cenas para NDVI")
            dry_scenes = scenes

        ref_crs, ref_transform, ref_height, ref_width = self._compute_ref_grid()
        print("  Gerando composite NDVI (estacao seca, pre-normalizacao)...")
        ndvi = self._build_ndvi_composite(
            dry_scenes, ref_crs, ref_transform, ref_height, ref_width
        )
        self.processing_service.save_as_cog(
            ndvi, ndvi_path, transform=ref_transform, crs=ref_crs,
        )
        print(f"  NDVI composite salvo: {ndvi_path}")

    def _ensure_ndvi_composite(self) -> bool:
        """Garante que o composite NDVI existe, baixando cenas AST_07XT se necessario."""
        if os.path.exists(self._get_ndvi_path()):
            return True

        self.aster_service.ensure_dirs()
        start_date, end_date = PRODUCT_DATE_RANGES["AST_07XT"]
        scenes = self.aster_service.download_all_scenes(
            product="AST_07XT",
            center_lon=self.center_lon,
            center_lat=self.center_lat,
            radius_km=self.radius_km,
            start_date=start_date,
            end_date=end_date,
        )
        if not scenes:
            print("  AVISO: Nenhuma cena AST_07XT para gerar NDVI")
            return False

        self._build_ndvi_from_scenes(scenes)
        return True

    def download_and_composite(self, product: str) -> str:
        """Baixa cenas ASTER e gera composite mediana multi-banda."""
        composite_cached = self.aster_service.has_cached_composite(product)
        ndvi_exists = os.path.exists(self._get_ndvi_path())

        if composite_cached and (product != "AST_07XT" or ndvi_exists):
            return self.aster_service.get_composite_path(product)

        self.aster_service.ensure_dirs()
        start_date, end_date = PRODUCT_DATE_RANGES[product]

        scenes = self.aster_service.download_all_scenes(
            product=product,
            center_lon=self.center_lon,
            center_lat=self.center_lat,
            radius_km=self.radius_km,
            start_date=start_date,
            end_date=end_date,
        )

        if not scenes:
            raise RuntimeError(f"Nenhuma cena {product} encontrada na area de estudo")

        # Gerar NDVI composite pre-normalizacao (AST_07XT)
        if product == "AST_07XT":
            self._build_ndvi_from_scenes(scenes)

        if composite_cached:
            return self.aster_service.get_composite_path(product)

        band_names = BAND_ORDER[product]
        print(f"Gerando composite mediana de {len(scenes)} cenas, {len(band_names)} bandas...")

        ref_crs, ref_transform, ref_height, ref_width = self._compute_ref_grid()
        print(f"  Grid de referencia: {ref_width}x{ref_height} pixels, EPSG:4326, ~30m")

        composites = []
        for band_name in band_names:
            print(f"  Composite {band_name}...")
            median = self._build_band_composite(
                scenes, band_name, ref_crs, ref_transform, ref_height, ref_width
            )
            composites.append(median)

        composite_stack = np.stack(composites, axis=0)

        composite_path = self.aster_service.get_composite_path(product)
        self.processing_service.save_as_cog(
            composite_stack, composite_path,
            transform=ref_transform, crs=ref_crs,
        )
        print(f"Composite salvo: {composite_path}")
        return composite_path

    def process_layer(self, layer_id: str) -> str:
        """Processa uma layer ASTER completa."""
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

        # Mascara de vegetacao NDVI < 0.4 (composite NDVI pre-normalizacao)
        # Aplica em TODAS as layers (AST_07XT e AST_05), consistente com GEE Fase 2
        self._ensure_ndvi_composite()
        ndvi_path = self._get_ndvi_path()
        if os.path.exists(ndvi_path):
            with rasterio.open(ndvi_path) as ndvi_src:
                ndvi = ndvi_src.read(1)
            veg_mask = ndvi >= 0.4
            for i in range(data.shape[0]):
                data[i][veg_mask] = np.nan
            pct_masked = np.sum(veg_mask) / veg_mask.size * 100
            print(f"  Mascara NDVI<0.4: {pct_masked:.1f}% vegetacao mascarada")
        else:
            print("  AVISO: NDVI composite nao disponivel, sem mascara de vegetacao")

        if layer_id == "crosta-feox":
            vnir = data[:3]  # B1, B2, B3
            components, loadings, _ = self.processing_service.run_pca(
                vnir, n_components=3
            )
            result = self.processing_service.select_crosta_component(
                components, loadings, target_band=2, contrast_band=0
            )
        elif layer_id == "crosta-oh":
            swir = data[3:7]  # B4, B5, B6, B7
            components, loadings, _ = self.processing_service.run_pca(
                swir, n_components=4
            )
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
            components, _, _ = self.processing_service.run_pca(
                tir, n_components=3
            )
            result = components[1]  # CP2 (CP1 = albedo)
        else:
            raise ValueError(f"Layer desconhecida: {layer_id}")

        # Suavizar resultado final para remover artefatos residuais
        if result.ndim == 2:
            mask = np.isfinite(result)
            if mask.any():
                smoothed = median_filter(np.nan_to_num(result), size=3)
                result[mask] = smoothed[mask]

        self.processing_service.save_as_cog(
            result, output_path, transform=transform, crs=crs
        )
        return output_path
