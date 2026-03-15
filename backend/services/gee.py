import ee

from backend.config import settings

VIRIDIS_PALETTE = [
    "440154", "482878", "3e4989", "31688e", "26828e",
    "1f9e89", "35b779", "6ece58", "b5de2b", "fde725",
]

LAYER_CONFIGS = {
    "rgb-true": {
        "name": "RGB Verdadeira",
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": ["B4", "B3", "B2"],
        "vis": {"min": 0, "max": 3000},
        "use_dry_season": True,
        "mask_vegetation": False,
        "description": "Sentinel-2 RGB verdadeira (ago-out 2017-2024, <20% nuvens)",
    },
    "rgb-false": {
        "name": "RGB Falsa-cor",
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": ["B11", "B8", "B4"],
        "vis": {"min": 0, "max": 5000},
        "use_dry_season": True,
        "mask_vegetation": False,
        "description": "Sentinel-2 SWIR/NIR/Red — destaque de solo exposto (ago-out 2017-2024)",
    },
    "iron-oxide": {
        "name": "Oxidos de Ferro",
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": None,
        "vis": {"min": 1.65, "max": 2.45, "palette": ["blue", "white", "red"]},
        "ratio": "B4/B2",
        "use_dry_season": True,
        "mask_vegetation": True,
        "description": "Ratio B4/B2 — oxidos de ferro (ago-out 2017-2024, NDVI<0.4)",
    },
    "clay": {
        "name": "Argilas / Sericita",
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": None,
        "vis": {"min": 1.26, "max": 1.60, "palette": ["blue", "white", "red"]},
        "ratio": "B11/B12",
        "use_dry_season": True,
        "mask_vegetation": True,
        "description": "Ratio SWIR1/SWIR2 — argilas e sericita (ago-out 2017-2024, NDVI<0.4)",
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
    # --- GEE ASTER comparison layers ---
    "gee-crosta-feox": {
        "name": "Crosta FeOx (GEE)",
        "vis": {"palette": VIRIDIS_PALETTE},
        "compute_stretch": True,
        "description": "PCA dirigida VNIR — FeOx (ASTER L1T, 2000-2008)",
    },
    "gee-crosta-oh": {
        "name": "Crosta OH (GEE)",
        "vis": {"palette": VIRIDIS_PALETTE},
        "compute_stretch": True,
        "description": "PCA dirigida SWIR — sericita (ASTER L1T, 2000-2008)",
    },
    "gee-ninomiya-aloh": {
        "name": "Ninomiya AlOH (GEE)",
        "vis": {"palette": VIRIDIS_PALETTE},
        "compute_stretch": True,
        "description": "B7/(B6*B8) — argilas AlOH (ASTER L1T, 2000-2008)",
    },
    "gee-ninomiya-mgoh": {
        "name": "Ninomiya MgOH (GEE)",
        "vis": {"palette": VIRIDIS_PALETTE},
        "compute_stretch": True,
        "description": "B7/(B6+B9) — clorita/talco (ASTER L1T, 2000-2008)",
    },
    "gee-ninomiya-ferrous": {
        "name": "Ninomiya Fe2+ (GEE)",
        "vis": {"palette": VIRIDIS_PALETTE},
        "compute_stretch": True,
        "description": "B5/B4 — ferro ferroso (ASTER L1T, 2000-2008)",
    },
    "gee-pca-tir": {
        "name": "PCA TIR (GEE)",
        "vis": {"palette": VIRIDIS_PALETTE},
        "compute_stretch": True,
        "description": "PCA emissividade TIR — silicificacao (ASTER GED, 2000-2008)",
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
                col.filterDate("2017-01-01", "2024-12-31")
                .filter(ee.Filter.calendarRange(8, 10, "month"))
                .filter(
                    ee.Filter.Or(
                        ee.Filter.calendarRange(2017, 2017, "year"),
                        ee.Filter.calendarRange(2019, 2024, "year"),
                    )
                )
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

    def _get_aster_l1t_masked(self):
        """ASTER L1T 2000-2008 (SWIR funcional) com mascara NDVI Sentinel-2."""
        l1t = (
            ee.ImageCollection("ASTER/AST_L1T_003")
            .filterBounds(self._region)
            .filterDate("2000-01-01", "2008-04-01")
            .median()
            .clip(self._region)
        )
        s2 = self._get_sentinel2_median(dry_season_only=True)
        mask = self._get_ndvi_mask(s2)
        return l1t.updateMask(mask)

    def _pca_gee(self, image, bands, scale=30):
        """PCA via eigendecomposicao no GEE. Retorna (pca_array_image, eigenvectors)."""
        selected = image.select(bands)
        mean_dict = selected.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=self._region,
            scale=scale,
            maxPixels=1e9,
        )
        means = ee.Image.constant([mean_dict.get(b) for b in bands])
        centered = selected.subtract(means)
        arrays = centered.toArray()
        covar = arrays.reduceRegion(
            reducer=ee.Reducer.covariance(),
            geometry=self._region,
            scale=scale,
            maxPixels=1e9,
        )
        covar_array = ee.Array(covar.get("array"))
        eigens = covar_array.eigen()
        eigen_vectors = eigens.slice(1, 1)
        # Projetar: (NxN) @ (Nx1) = (Nx1) por pixel
        pca_image = ee.Image(eigen_vectors).matrixMultiply(arrays.toArray(1))
        return pca_image, eigen_vectors

    def _extract_pc(self, pca_image, index):
        """Extrai componente principal pelo indice."""
        return (
            pca_image.arraySlice(0, index, index + 1)
            .arrayProject([1])
            .arrayFlatten([["PC"]])
        )

    def _build_crosta_gee(self, l1t, bands, target_band, contrast_band, scale):
        """Metodo Crosta (PCA dirigida) via GEE."""
        pca_image, eigen_vectors = self._pca_gee(l1t, bands, scale)
        ev = eigen_vectors.getInfo()
        n = len(bands)

        best_pc = max(range(n), key=lambda i: abs(ev[i][target_band]))

        negate = ev[best_pc][target_band] < 0
        if ev[best_pc][target_band] * ev[best_pc][contrast_band] > 0:
            negate = not negate

        pc = self._extract_pc(pca_image, best_pc)
        if negate:
            pc = pc.multiply(-1)
        return pc

    def _build_gee_aster(self, layer_id):
        """Constroi imagem ASTER processada via GEE para comparacao."""
        if layer_id == "gee-pca-tir":
            ged = ee.Image("NASA/ASTER_GED/AG100_003").clip(self._region)
            bands = [
                "emissivity_band10", "emissivity_band11",
                "emissivity_band12", "emissivity_band13", "emissivity_band14",
            ]
            s2 = self._get_sentinel2_median(dry_season_only=True)
            mask = self._get_ndvi_mask(s2)
            ged = ged.select(bands).updateMask(mask)
            pca_image, _ = self._pca_gee(ged, bands, scale=100)
            return self._extract_pc(pca_image, 1)  # PC2 (PC1 = albedo)

        l1t = self._get_aster_l1t_masked()

        if layer_id == "gee-ninomiya-aloh":
            return l1t.select("B07").divide(
                l1t.select("B06").multiply(l1t.select("B08"))
            )
        elif layer_id == "gee-ninomiya-mgoh":
            return l1t.select("B07").divide(
                l1t.select("B06").add(l1t.select("B09"))
            )
        elif layer_id == "gee-ninomiya-ferrous":
            return l1t.select("B05").divide(l1t.select("B04"))
        elif layer_id == "gee-crosta-feox":
            return self._build_crosta_gee(
                l1t, ["B01", "B02", "B3N"],
                target_band=2, contrast_band=0, scale=60,
            )
        elif layer_id == "gee-crosta-oh":
            return self._build_crosta_gee(
                l1t, ["B04", "B05", "B06", "B07"],
                target_band=2, contrast_band=1, scale=60,
            )

    def _build_image(self, layer_id):
        config = LAYER_CONFIGS[layer_id]

        if layer_id == "dem":
            dem = ee.Image("USGS/SRTMGL1_003").clip(self._region)
            return ee.Terrain.hillshade(dem)

        if layer_id.startswith("gee-"):
            return self._build_gee_aster(layer_id)

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

        if config.get("compute_stretch"):
            stats = image.reduceRegion(
                reducer=ee.Reducer.percentile([2, 98]),
                geometry=self._region,
                scale=100,
                maxPixels=1e9,
            ).getInfo()
            band_name = image.bandNames().getInfo()[0]
            vis_params["min"] = stats.get(f"{band_name}_p2", 0)
            vis_params["max"] = stats.get(f"{band_name}_p98", 1)

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
