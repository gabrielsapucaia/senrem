"""Servico de processamento: PCA, metodo Crosta, ratios Ninomiya."""

from typing import List, Optional, Tuple

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine
from sklearn.decomposition import PCA


class ProcessingService:
    """Processamento de dados raster: PCA, Crosta, ratios espectrais."""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    def run_pca(
        self, bands: np.ndarray, n_components: Optional[int] = None
    ) -> Tuple[np.ndarray, np.ndarray, List[float]]:
        """Executa PCA sobre stack de bandas.

        Args:
            bands: Array (n_bands, height, width).
            n_components: Numero de componentes. Default = n_bands.

        Returns:
            Tuple (components, loadings, explained_variance_ratio):
                - components: (n_components, height, width)
                - loadings: (n_components, n_bands)
                - explained_variance_ratio: lista de floats
        """
        n_bands, height, width = bands.shape
        if n_components is None:
            n_components = n_bands

        # Reshape para (n_pixels, n_bands)
        pixels = bands.reshape(n_bands, -1).T
        valid_mask = np.all(np.isfinite(pixels), axis=1)
        valid_pixels = pixels[valid_mask]

        pca = PCA(n_components=n_components)
        transformed = pca.fit_transform(valid_pixels)

        # Reconstruir imagem, pixels invalidos ficam NaN
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
        """Seleciona componente principal pelo metodo Crosta (PCA dirigida).

        Seleciona a CP com maior peso absoluto na banda alvo.
        Ajusta o sinal para que altos valores indiquem presenca do mineral.

        Args:
            components: (n_components, height, width) do run_pca.
            loadings: (n_components, n_bands) do run_pca.
            target_band: Indice da banda associada ao mineral alvo.
            contrast_band: Indice da banda de contraste (sinal oposto esperado).

        Returns:
            Array 2D (height, width) com a componente selecionada e sinal ajustado.
        """
        target_weights = np.abs(loadings[:, target_band])
        best_cp = int(np.argmax(target_weights))

        selected = components[best_cp].copy()

        # Ajustar sinal: target e contrast devem ter sinais opostos
        if loadings[best_cp, target_band] < 0:
            selected = -selected

        if loadings[best_cp, target_band] * loadings[best_cp, contrast_band] > 0:
            selected = -selected

        return selected

    def compute_ratio(
        self, numerator: np.ndarray, denominator: np.ndarray
    ) -> np.ndarray:
        """Calcula ratio entre duas bandas, tratando divisao por zero."""
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = numerator / denominator
            ratio[~np.isfinite(ratio)] = np.nan
        return ratio

    def ninomiya_aloh(
        self, b6: np.ndarray, b7: np.ndarray, b8: np.ndarray
    ) -> np.ndarray:
        """Indice Ninomiya AlOH: B7 / (B6 * B8).

        Indica presenca de minerais com absorcao AlOH (sericita, muscovita).
        """
        with np.errstate(divide="ignore", invalid="ignore"):
            result = b7 / (b6 * b8)
            result[~np.isfinite(result)] = np.nan
        return result

    def ninomiya_mgoh(
        self, b6: np.ndarray, b7: np.ndarray, b9: np.ndarray
    ) -> np.ndarray:
        """Indice Ninomiya MgOH: B7 / (B6 + B9).

        Indica presenca de minerais com absorcao MgOH (clorita, talco).
        """
        with np.errstate(divide="ignore", invalid="ignore"):
            result = b7 / (b6 + b9)
            result[~np.isfinite(result)] = np.nan
        return result

    def ninomiya_ferrous(self, b4: np.ndarray, b5: np.ndarray) -> np.ndarray:
        """Indice Ninomiya Ferrous: B5 / B4.

        Indica presenca de minerais ferrosos.
        """
        return self.compute_ratio(b5, b4)

    def build_composite(
        self,
        scene_paths: List[str],
        output_path: str,
        bands: List[int],
    ) -> None:
        """Gera composite mediana a partir de multiplas cenas.

        Args:
            scene_paths: Lista de caminhos para cenas GeoTIFF.
            output_path: Caminho do arquivo de saida.
            bands: Lista de indices de banda (1-based) para incluir.
        """
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

    def save_as_cog(
        self,
        data: np.ndarray,
        output_path: str,
        transform: Affine,
        crs: CRS,
    ) -> None:
        """Salva array como GeoTIFF otimizado (tiled + comprimido).

        Args:
            data: Array 2D (height, width) ou 3D (count, height, width).
            output_path: Caminho do arquivo de saida.
            transform: Affine transform do raster.
            crs: Sistema de referencia de coordenadas.
        """
        if data.ndim == 2:
            data = data[np.newaxis, :]
        count, height, width = data.shape

        with rasterio.open(
            output_path,
            "w",
            driver="GTiff",
            height=height,
            width=width,
            count=count,
            dtype=data.dtype,
            crs=crs,
            transform=transform,
            tiled=True,
            blockxsize=256,
            blockysize=256,
            compress="deflate",
        ) as dst:
            dst.write(data)
