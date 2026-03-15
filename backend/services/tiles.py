from typing import Dict, Optional

from rio_tiler.io import Reader


class TileService:
    def __init__(self, processed_dir: str):
        self.processed_dir = processed_dir
        self._cog_registry: Dict[str, str] = {}

    def register_cog(self, layer_id: str, cog_path: str):
        self._cog_registry[layer_id] = cog_path

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
            return img.render(img_format="PNG")

    def is_registered(self, layer_id: str) -> bool:
        return layer_id in self._cog_registry

    def get_tile_url_template(self, layer_id: str, base_url: str) -> str:
        return f"{base_url}/api/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png"
