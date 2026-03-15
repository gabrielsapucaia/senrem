import ee

from backend.config import settings

LAYER_CONFIGS = {
    "rgb-true": {
        "name": "RGB Verdadeira",
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": ["B4", "B3", "B2"],
        "vis": {"min": 0, "max": 3000},
        "description": "Sentinel-2 RGB verdadeira (mediana 2024, <20% nuvens)",
    },
    "rgb-false": {
        "name": "RGB Falsa-cor",
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": ["B11", "B8", "B4"],
        "vis": {"min": 0, "max": 5000},
        "description": "Sentinel-2 SWIR/NIR/Red — destaque de solo exposto e vegetacao",
    },
    "iron-oxide": {
        "name": "Oxidos de Ferro",
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": None,
        "vis": {"min": 1.2, "max": 2.6, "palette": ["blue", "white", "red"]},
        "ratio": "B4/B2",
        "description": "Ratio B4/B2 — indicador de oxidos de ferro (gossan)",
    },
    "clay": {
        "name": "Argilas / Sericita",
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": None,
        "vis": {"min": 1.3, "max": 2.3, "palette": ["blue", "white", "red"]},
        "ratio": "B11/B12",
        "description": "Ratio SWIR1/SWIR2 — indicador de argilas e sericita",
    },
    "dem": {
        "name": "DEM / Hillshade",
        "collection": "USGS/SRTMGL1_003",
        "bands": ["elevation"],
        "vis": {"min": 0, "max": 255},
        "is_hillshade": True,
        "description": "SRTM 30m hillshade — relevo e estruturas",
    },
    "carbonate": {
        "name": "Carbonatos",
        "collection": "ASTER/AST_L1T_003",
        "bands": None,
        "vis": {"min": 0.94, "max": 0.98, "palette": ["blue", "white", "red"]},
        "ratio": "B13/B14",
        "description": "ASTER B13/B14 — indicador de carbonatos",
    },
    "silica": {
        "name": "Silica",
        "collection": "ASTER/AST_L1T_003",
        "bands": None,
        "vis": {"min": 1.37, "max": 1.41, "palette": ["blue", "white", "yellow"]},
        "ratio": "B13/B10",
        "description": "ASTER B13/B10 — indicador de silica",
    },
}


class GEEService:
    def __init__(self):
        self.ee = ee
        ee.Initialize(project=settings.gee_project)
        self._center = ee.Geometry.Point(
            settings.study_area_center_lon, settings.study_area_center_lat
        )
        self._region = self._center.buffer(settings.study_area_radius_km * 1000)

    def get_study_area_bbox(self):
        return self._region.bounds().getInfo()

    def _get_sentinel2_median(self):
        return (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(self._region)
            .filterDate("2024-01-01", "2024-12-31")
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
            .median()
            .clip(self._region)
        )

    def _get_aster_median(self):
        return (
            ee.ImageCollection("ASTER/AST_L1T_003")
            .filterBounds(self._region)
            .filterDate("2000-01-01", "2024-12-31")
            .median()
            .clip(self._region)
        )

    def _build_image(self, layer_id):
        config = LAYER_CONFIGS[layer_id]

        if layer_id == "dem":
            dem = ee.Image("USGS/SRTMGL1_003").clip(self._region)
            return ee.Terrain.hillshade(dem)

        if config["collection"] == "ASTER/AST_L1T_003":
            median = self._get_aster_median()
        else:
            median = self._get_sentinel2_median()

        if "ratio" in config:
            parts = config["ratio"].split("/")
            return median.select(parts[0]).divide(median.select(parts[1]))

        return median.select(config["bands"])

    def get_layer_tiles(self, layer_id):
        if layer_id not in LAYER_CONFIGS:
            raise ValueError(f"Layer desconhecida: {layer_id}")

        config = LAYER_CONFIGS[layer_id]
        image = self._build_image(layer_id)

        vis_params = dict(config["vis"])
        if config.get("bands") and not config.get("is_hillshade") and "ratio" not in config:
            vis_params["bands"] = config["bands"]

        map_id = image.getMapId(vis_params)

        return {
            "layer_id": layer_id,
            "name": config["name"],
            "description": config["description"],
            "tile_url": map_id["tile_fetcher"].url_format,
        }

    def get_available_layers(self):
        return list(LAYER_CONFIGS.keys())
