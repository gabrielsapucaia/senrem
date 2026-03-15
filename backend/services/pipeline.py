"""Pipeline completo ASTER: download + composite + processamento."""

import os
from typing import Dict, List

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.warp import calculate_default_transform, reproject, Resampling

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
        "Emissivity_B10", "Emissivity_B11", "Emissivity_B12",
        "Emissivity_B13", "Emissivity_B14",
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

    def _build_band_composite(
        self, scenes: List[Dict[str, str]], band_name: str
    ) -> np.ndarray:
        """Calcula mediana de uma banda across todas as cenas."""
        band_arrays = []
        for scene in scenes:
            if band_name not in scene:
                continue
            with rasterio.open(scene[band_name]) as src:
                band_arrays.append(src.read(1).astype(np.float32))

        if not band_arrays:
            raise ValueError(f"Nenhuma cena com banda {band_name}")

        stacked = np.stack(band_arrays, axis=0)
        # Substituir zeros e nodata por NaN antes da mediana
        stacked[stacked <= 0] = np.nan
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

        # Usar primeira cena como referencia de geometria
        first_band = band_names[0]
        ref_path = scenes[0][first_band]
        with rasterio.open(ref_path) as ref:
            ref_transform = ref.transform
            ref_crs = ref.crs
            ref_height = ref.height
            ref_width = ref.width

        composites = []
        for band_name in band_names:
            print(f"  Composite {band_name}...")
            median = self._build_band_composite(scenes, band_name)
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

        self.processing_service.save_as_cog(
            result, output_path, transform=transform, crs=crs
        )
        return output_path
