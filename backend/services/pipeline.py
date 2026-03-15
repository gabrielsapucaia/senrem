"""Pipeline completo ASTER: download + composite + processamento."""

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
        """Retorna lista de produtos ASTER necessarios."""
        return list(PRODUCT_DATE_RANGES.keys())

    def get_product_for_layer(self, layer_id: str) -> str:
        """Retorna o produto ASTER necessario para uma layer."""
        return LAYER_PRODUCT_MAP[layer_id]

    def get_processed_path(self, layer_id: str) -> str:
        """Retorna caminho do raster processado para uma layer."""
        return os.path.join(self.data_dir, "rasters", "processed", f"{layer_id}.tif")

    def is_processed(self, layer_id: str) -> bool:
        """Verifica se a layer ja foi processada."""
        return os.path.exists(self.get_processed_path(layer_id))

    def download_and_composite(self, product: str) -> str:
        """Baixa cenas ASTER e gera composite mediana.

        Se o composite ja existe em cache, retorna o caminho direto.

        Args:
            product: Produto ASTER (AST_07XT ou AST_08).

        Returns:
            Caminho do composite GeoTIFF.
        """
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
        """Processa uma layer ASTER completa.

        Executa download + composite (se necessario) e aplica o
        processamento especifico (Crosta, Ninomiya, PCA TIR).

        Args:
            layer_id: Identificador da layer (ex: crosta-feox, pca-tir).

        Returns:
            Caminho do COG processado.
        """
        import numpy as np
        import rasterio

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
