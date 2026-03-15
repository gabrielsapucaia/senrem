import os
from typing import Dict, Optional, Tuple

import numpy as np
import rasterio
from rio_tiler.colormap import cmap as rio_cmap
from rio_tiler.io import Reader


class TileService:
    def __init__(self, processed_dir: str):
        self.processed_dir = processed_dir
        self._cog_registry: Dict[str, str] = {}
        self._stats: Dict[str, Tuple[float, float]] = {}

    def register_cog(self, layer_id: str, cog_path: str):
        self._cog_registry[layer_id] = cog_path
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
            img = src.tile(x, y, z)

            if vmin is not None and vmax is not None:
                img.rescale(in_range=((vmin, vmax),))
            elif layer_id in self._stats:
                p2, p98 = self._stats[layer_id]
                img.rescale(in_range=((p2, p98),))

            cm = rio_cmap.get(colormap or "viridis")
            return img.render(img_format="PNG", colormap=cm)

    def is_registered(self, layer_id: str) -> bool:
        return layer_id in self._cog_registry

    def get_tile_url_template(self, layer_id: str, base_url: str) -> str:
        return f"{base_url}/api/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png"
