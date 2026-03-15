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

    def download_and_composite(self, product: str) -> str:
        """Baixa cenas ASTER e gera composite mediana multi-banda."""
        if self.aster_service.has_cached_composite(product):
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

        # Mascara de vegetacao NDVI < 0.4 (AST_07XT: B02=Red, B03N=NIR)
        if product == "AST_07XT":
            red = data[1].astype(np.float32)   # B02
            nir = data[2].astype(np.float32)   # B03N
            ndvi = np.where(
                (nir + red) > 0,
                (nir - red) / (nir + red),
                np.nan,
            )
            veg_mask = ndvi >= 0.4
            for i in range(data.shape[0]):
                data[i][veg_mask] = np.nan
            pct_masked = np.sum(veg_mask) / veg_mask.size * 100
            print(f"  Mascara NDVI<0.4: {pct_masked:.1f}% vegetacao mascarada")

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
