import os
from typing import Dict, Optional, Tuple

import numpy as np
import rasterio
from rio_tiler.colormap import cmap as rio_cmap
from rio_tiler.errors import TileOutsideBounds
from rio_tiler.io import Reader

# Tile PNG transparente 256x256 pre-computado (1x1 pixel transparente escalado pelo browser)
_EMPTY_TILE = None


def _get_empty_tile() -> bytes:
    """Gera tile PNG transparente 256x256 usando rio-tiler."""
    global _EMPTY_TILE
    if _EMPTY_TILE is None:
        from rio_tiler.models import ImageData
        empty = ImageData(
            np.zeros((1, 256, 256), dtype=np.uint8),
            np.zeros((256, 256), dtype=np.uint8),
        )
        _EMPTY_TILE = empty.render(img_format="PNG")
    return _EMPTY_TILE


class TileService:
    def __init__(self, processed_dir: str):
        self.processed_dir = processed_dir
        self._cog_registry: Dict[str, str] = {}
        self._stats: Dict[str, Tuple[float, float]] = {}
        self._rgb_layers: set = set()
        self._rgb_defaults: Dict[str, Tuple[float, float]] = {}

    def register_cog(self, layer_id: str, cog_path: str,
                     is_rgb: bool = False,
                     default_range: Optional[Tuple[float, float]] = None):
        self._cog_registry[layer_id] = cog_path
        if is_rgb:
            self._rgb_layers.add(layer_id)
            if default_range:
                self._rgb_defaults[layer_id] = default_range
        else:
            self._compute_stats(layer_id, cog_path)

    def _compute_stats(self, layer_id: str, cog_path: str):
        """Calcula percentis p2/p98 para rescaling."""
        with rasterio.open(cog_path) as src:
            data = src.read(1)
            valid = data[np.isfinite(data) & (data != 0)]
            if len(valid) > 0:
                p2, p98 = np.percentile(valid, [2, 98])
                self._stats[layer_id] = (float(p2), float(p98))

    def get_tile(self, layer_id: str, z: int, x: int, y: int,
                 colormap: Optional[str] = None,
                 vmin: Optional[float] = None,
                 vmax: Optional[float] = None) -> bytes:
        if layer_id not in self._cog_registry:
            raise ValueError(f"Layer '{layer_id}' nao registrada")

        cog_path = self._cog_registry[layer_id]
        with Reader(cog_path) as src:
            try:
                img = src.tile(x, y, z)
            except TileOutsideBounds:
                return _get_empty_tile()

            if layer_id in self._rgb_layers:
                defaults = self._rgb_defaults.get(layer_id, (0, 3000))
                r_min = vmin if vmin is not None else defaults[0]
                r_max = vmax if vmax is not None else defaults[1]
                n_bands = img.data.shape[0]
                img.rescale(in_range=tuple([(r_min, r_max)] * n_bands))
                return img.render(img_format="PNG")

            if vmin is not None and vmax is not None:
                img.rescale(in_range=((vmin, vmax),))
            elif layer_id in self._stats:
                p2, p98 = self._stats[layer_id]
                img.rescale(in_range=((p2, p98),))

            cm = rio_cmap.get(colormap or "viridis")
            return img.render(img_format="PNG", colormap=cm)

    def is_registered(self, layer_id: str) -> bool:
        return layer_id in self._cog_registry

    def is_rgb(self, layer_id: str) -> bool:
        return layer_id in self._rgb_layers

    def get_tile_url_template(self, layer_id: str, base_url: str) -> str:
        return f"{base_url}/api/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png"
