import json
import os

import ee
import requests as http_requests

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
        if settings.gee_service_account_key:
            key_data = json.loads(settings.gee_service_account_key)
            credentials = ee.ServiceAccountCredentials(
                key_data["client_email"],
                key_data=settings.gee_service_account_key,
            )
            ee.Initialize(credentials=credentials, project=settings.gee_project)
        else:
            ee.Initialize(project=settings.gee_project)
        self._center = ee.Geometry.Point(
            settings.study_area_center_lon, settings.study_area_center_lat
        )
        self._region = self._center.buffer(settings.study_area_radius_km * 1000)

    def set_area(self, center_lon, center_lat, radius_km):
        """Define uma nova area de estudo para downloads."""
        self._center = ee.Geometry.Point(center_lon, center_lat)
        self._region = self._center.buffer(radius_km * 1000)

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

    def _get_aster_l1t_improved(self, bands, normalize=True):
        """ASTER L1T melhorado: sazonal ago-out + normalizacao por cena + NDVI mask.

        Replica o pipeline local: filtra estacao seca, normaliza cada cena
        (mean/std) antes do composite mediana, aplica mascara NDVI<0.4.

        Args:
            bands: Lista de nomes de bandas ASTER (ex: ["B01", "B02", "B3N"]).
            normalize: Se True, normaliza cada cena para mean=0/std=1.
                       Essencial para PCA. Desnecessario para ratios.
        """
        col = (
            ee.ImageCollection("ASTER/AST_L1T_003")
            .filterBounds(self._region)
            .filterDate("2000-01-01", "2008-04-01")
            .filter(ee.Filter.calendarRange(8, 10, "month"))
            .select(bands)
        )

        if normalize:
            region = self._region

            def norm_scene(image):
                stats = image.reduceRegion(
                    reducer=ee.Reducer.mean().combine(
                        ee.Reducer.stdDev(), sharedInputs=True
                    ),
                    geometry=region,
                    scale=90,
                    maxPixels=1e9,
                    bestEffort=True,
                )
                normalized = image
                for b in bands:
                    mean = ee.Number(stats.get(b + "_mean"))
                    std = ee.Number(stats.get(b + "_stdDev")).max(0.0001)
                    normalized = normalized.addBands(
                        image.select(b).subtract(mean).divide(std).toFloat(),
                        overwrite=True,
                    )
                return normalized

            col = col.map(norm_scene)

        median = col.median().clip(self._region)
        s2 = self._get_sentinel2_median(dry_season_only=True)
        mask = self._get_ndvi_mask(s2)
        return median.updateMask(mask)

    def _smooth(self, image):
        """Filtro mediana 3x3 para suavizar artefatos residuais."""
        return image.focalMedian(1.5, "square", "pixels")

    def _pca_gee(self, image, bands, scale=30):
        """PCA via eigendecomposicao no GEE. Retorna (pca_array_image, eigenvectors).

        Usa bestEffort=True para auto-ajustar escala se exceder memoria.
        A projecao (matrixMultiply) roda pixel-a-pixel na resolucao nativa,
        independente da escala usada para estatisticas.
        """
        selected = image.select(bands)
        mean_dict = selected.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=self._region,
            scale=scale,
            maxPixels=1e9,
            bestEffort=True,
        )
        means = ee.Image.constant([mean_dict.get(b) for b in bands])
        centered = selected.subtract(means)
        arrays = centered.toArray()
        covar = arrays.reduceRegion(
            reducer=ee.Reducer.covariance(),
            geometry=self._region,
            scale=scale,
            maxPixels=1e9,
            bestEffort=True,
        )
        covar_array = ee.Array(covar.get("array"))
        eigens = covar_array.eigen()
        eigen_vectors = eigens.slice(1, 1)
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
        """Constroi imagem ASTER processada via GEE.

        Pipeline melhorado (equivalente ao local):
        1. Filtro sazonal ago-out (estacao seca)
        2. Normalizacao por cena (mean/std) antes do composite
        3. Mediana das cenas normalizadas
        4. Mascara NDVI<0.4 (Sentinel-2)
        5. Processamento (PCA/Crosta/ratios)
        6. Filtro mediana 3x3 (suavizacao)
        """
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
            pc2 = self._extract_pc(pca_image, 1)
            return self._smooth(pc2)

        # Ratios Ninomiya: normalize=False (ratio e auto-normalizante)
        if layer_id.startswith("gee-ninomiya"):
            ninomiya_bands = {
                "gee-ninomiya-aloh": ["B04", "B05", "B06", "B07", "B08"],
                "gee-ninomiya-mgoh": ["B04", "B05", "B06", "B07", "B09"],
                "gee-ninomiya-ferrous": ["B04", "B05"],
            }
            bands = ninomiya_bands[layer_id]
            l1t = self._get_aster_l1t_improved(bands, normalize=False)

            if layer_id == "gee-ninomiya-aloh":
                result = l1t.select("B07").divide(
                    l1t.select("B06").multiply(l1t.select("B08"))
                )
            elif layer_id == "gee-ninomiya-mgoh":
                result = l1t.select("B07").divide(
                    l1t.select("B06").add(l1t.select("B09"))
                )
            else:
                result = l1t.select("B05").divide(l1t.select("B04"))
            return self._smooth(result)

        # Crosta (PCA dirigida): normalize=True (essencial para PCA)
        if layer_id == "gee-crosta-feox":
            bands = ["B01", "B02", "B3N"]
            l1t = self._get_aster_l1t_improved(bands, normalize=True)
            result = self._build_crosta_gee(
                l1t, bands, target_band=2, contrast_band=0, scale=60,
            )
            return self._smooth(result)

        elif layer_id == "gee-crosta-oh":
            bands = ["B04", "B05", "B06", "B07"]
            l1t = self._get_aster_l1t_improved(bands, normalize=True)
            result = self._build_crosta_gee(
                l1t, bands, target_band=2, contrast_band=1, scale=60,
            )
            return self._smooth(result)

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

    def _get_download_config(self, layer_id):
        """Retorna (scale, grid_size) para download de cada layer.

        PCA/Crosta ASTER com normalizacao por cena sao computacionalmente pesados
        e excedem o limite de memoria do GEE em regioes grandes — precisam de grid.
        """
        if layer_id == "gee-pca-tir":
            return 90, 2   # ASTER TIR 90m, PCA pesado
        elif layer_id in ("gee-crosta-oh", "gee-ninomiya-aloh", "gee-ninomiya-mgoh"):
            return 30, 3   # ASTER SWIR 30m, PCA/ratio pesado
        elif layer_id in ("gee-crosta-feox", "gee-ninomiya-ferrous"):
            return 15, 8   # ASTER VNIR 15m, PCA pesado, 8x8 grid
        elif layer_id.startswith("gee-"):
            return 30, 2
        elif layer_id == "dem":
            return 30, 1   # SRTM 30m, leve
        elif "ASTER" in LAYER_CONFIGS[layer_id].get("collection", ""):
            return 90, 2
        elif self.is_rgb_layer(layer_id):
            return 10, 7   # S2 RGB 10m, median 512 imgs, 7x7 grid
        else:
            return 20, 5   # S2 ratios (SWIR) 20m, 5x5 grid

    def is_rgb_layer(self, layer_id):
        """True se a layer e multi-banda RGB."""
        config = LAYER_CONFIGS[layer_id]
        bands = config.get("bands")
        return (
            bands is not None
            and len(bands) >= 3
            and "ratio" not in config
            and not config.get("is_hillshade")
        )

    def get_rgb_range(self, layer_id):
        """Retorna (min, max) para rescaling de layers RGB."""
        config = LAYER_CONFIGS[layer_id]
        vis = config.get("vis", {})
        return (vis.get("min", 0), vis.get("max", 3000))

    def _download_region(self, image, output_path, scale, region):
        """Download de uma regiao como GeoTIFF."""
        url = image.getDownloadURL({
            "scale": scale,
            "region": region,
            "crs": "EPSG:4326",
            "format": "GEO_TIFF",
            "filePerBand": False,
        })
        response = http_requests.get(url, timeout=300)
        response.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(response.content)

    def _download_grid_and_mosaic(self, image, output_path, scale, grid_size):
        """Download paralelo em grid de sub-regioes e mosaic local."""
        import rasterio
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from rasterio.merge import merge

        bounds_info = self._region.bounds().getInfo()["coordinates"][0]
        west, south = bounds_info[0]
        east, north = bounds_info[2]
        dx = (east - west) / grid_size
        dy = (north - south) / grid_size

        # Preparar todas as sub-regioes
        tasks = []
        for i in range(grid_size):
            for j in range(grid_size):
                sub_west = west + i * dx
                sub_south = south + j * dy
                sub_region = ee.Geometry.Rectangle([
                    sub_west, sub_south, sub_west + dx, sub_south + dy,
                ])
                part_path = output_path.replace(".tif", f"_part_{i}_{j}.tif")
                tasks.append((part_path, sub_region))

        total = len(tasks)
        done = [0]

        def _download_part(args):
            part_path, sub_region = args
            self._download_region(image, part_path, scale, sub_region)
            done[0] += 1
            print(f"    Grid {done[0]}/{total} OK")
            return part_path

        # Download paralelo (max 4 threads para nao sobrecarregar GEE)
        max_workers = min(4, total)
        part_paths = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_download_part, t): t for t in tasks}
            for future in as_completed(futures):
                part_paths.append(future.result())

        # Mosaic
        datasets = [rasterio.open(p) for p in part_paths]
        mosaic, mosaic_transform = merge(datasets)
        for ds in datasets:
            ds.close()

        # Salvar mosaic
        with rasterio.open(part_paths[0]) as ref:
            profile = ref.profile.copy()
        profile.update(
            height=mosaic.shape[1],
            width=mosaic.shape[2],
            transform=mosaic_transform,
        )
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(mosaic)

        # Cleanup
        for p in part_paths:
            os.remove(p)

    def download_layer_cog(self, layer_id, output_path):
        """Download de imagem GEE processada como GeoTIFF.

        Usa grid de sub-regioes para layers pesadas (S2 median de 512 imagens).
        """
        image = self._build_image(layer_id)
        scale, grid_size = self._get_download_config(layer_id)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        if grid_size == 1:
            self._download_region(image, output_path, scale, self._region.bounds())
        else:
            print(f"    Download em grid {grid_size}x{grid_size} a {scale}m...")
            self._download_grid_and_mosaic(image, output_path, scale, grid_size)
