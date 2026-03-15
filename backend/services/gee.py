import ee

from backend.config import settings

LAYER_CONFIGS = {
    "rgb-true": {
        "name": "RGB Verdadeira",
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": ["B4", "B3", "B2"],
        "vis": {"min": 0, "max": 3000},
        "use_dry_season": True,
        "mask_vegetation": False,
        "description": "Sentinel-2 RGB verdadeira (seca jun-set, <20% nuvens)",
    },
    "rgb-false": {
        "name": "RGB Falsa-cor",
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": ["B11", "B8", "B4"],
        "vis": {"min": 0, "max": 5000},
        "use_dry_season": True,
        "mask_vegetation": False,
        "description": "Sentinel-2 SWIR/NIR/Red — destaque de solo exposto (seca)",
    },
    "iron-oxide": {
        "name": "Oxidos de Ferro",
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": None,
        "vis": {"min": 1.5, "max": 2.9, "palette": ["blue", "white", "red"]},
        "ratio": "B4/B2",
        "use_dry_season": True,
        "mask_vegetation": True,
        "description": "Ratio B4/B2 — oxidos de ferro (seca, sem vegetacao densa)",
    },
    "clay": {
        "name": "Argilas / Sericita",
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": None,
        "vis": {"min": 1.2, "max": 1.6, "palette": ["blue", "white", "red"]},
        "ratio": "B11/B12",
        "use_dry_season": True,
        "mask_vegetation": True,
        "description": "Ratio SWIR1/SWIR2 — argilas e sericita (seca, sem vegetacao densa)",
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
        "mask_vegetation": True,
        "description": "ASTER B13/B14 — indicador de carbonatos (sem vegetacao densa)",
    },
    "silica": {
        "name": "Silica",
        "collection": "ASTER/AST_L1T_003",
        "bands": None,
        "vis": {"min": 1.37, "max": 1.41, "palette": ["blue", "white", "yellow"]},
        "ratio": "B13/B10",
        "mask_vegetation": True,
        "description": "ASTER B13/B10 — indicador de silica (sem vegetacao densa)",
    },
}

NDVI_THRESHOLD = 0.4


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

    def _get_sentinel2_median(self, dry_season_only=False):
        col = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(self._region)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        )
        if dry_season_only:
            col = (
                col.filterDate("2022-01-01", "2024-12-31")
                .filter(ee.Filter.calendarRange(6, 9, "month"))
            )
        else:
            col = col.filterDate("2024-01-01", "2024-12-31")
        return col.median().clip(self._region)

    def _get_ndvi_mask(self, s2_image):
        ndvi = s2_image.normalizedDifference(["B8", "B4"])
        return ndvi.lt(NDVI_THRESHOLD)

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

        use_dry = config.get("use_dry_season", False)
        apply_mask = config.get("mask_vegetation", False)

        if config["collection"] == "ASTER/AST_L1T_003":
            median = self._get_aster_median()
            if apply_mask:
                s2_for_mask = self._get_sentinel2_median(dry_season_only=True)
                mask = self._get_ndvi_mask(s2_for_mask)
                median = median.updateMask(mask)
        else:
            median = self._get_sentinel2_median(dry_season_only=use_dry)
            if apply_mask:
                mask = self._get_ndvi_mask(median)
                median = median.updateMask(mask)

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
