import math
import os
from typing import Dict, List, Optional

import httpx


CMR_BASE = "https://cmr.earthdata.nasa.gov/search"
URS_TOKEN_URL = "https://urs.earthdata.nasa.gov/api/users/tokens"

BAND_SUFFIXES = {
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


class AsterService:
    def __init__(self, data_dir: str, username: str, password: str):
        self.data_dir = data_dir
        self.username = username
        self.password = password
        self._token: Optional[str] = None

    def ensure_dirs(self):
        for subdir in ["aster/raw", "aster/composite", "processed"]:
            os.makedirs(os.path.join(self.data_dir, subdir), exist_ok=True)

    def build_aoi_geojson(
        self, center_lon: float, center_lat: float, radius_km: float
    ) -> Dict:
        points = 64
        coords = []
        for i in range(points + 1):
            angle = (i / points) * 2 * math.pi
            dx = radius_km * math.cos(angle)
            dy = radius_km * math.sin(angle)
            lat = center_lat + (dy / 111.32)
            lon = center_lon + (dx / (111.32 * math.cos(math.radians(center_lat))))
            coords.append([lon, lat])
        return {"type": "Polygon", "coordinates": [coords]}

    def _get_bbox(self, center_lon: float, center_lat: float, radius_km: float) -> str:
        dlat = radius_km / 111.32
        dlon = radius_km / (111.32 * math.cos(math.radians(center_lat)))
        return f"{center_lon - dlon},{center_lat - dlat},{center_lon + dlon},{center_lat + dlat}"

    def login(self) -> str:
        with httpx.Client(follow_redirects=True, timeout=30) as client:
            resp = client.get(
                URS_TOKEN_URL,
                auth=(self.username, self.password),
            )
            resp.raise_for_status()
            tokens = resp.json()
            if tokens:
                self._token = tokens[0]["access_token"]
            else:
                resp2 = client.post(
                    "https://urs.earthdata.nasa.gov/api/users/token",
                    auth=(self.username, self.password),
                )
                resp2.raise_for_status()
                self._token = resp2.json()["access_token"]
        return self._token

    def search_granules(
        self,
        product: str,
        bbox: str,
        start_date: str,
        end_date: str,
    ) -> List[Dict]:
        all_entries = []
        page = 1
        while True:
            resp = httpx.get(
                f"{CMR_BASE}/granules.json",
                params={
                    "short_name": product,
                    "version": "004",
                    "bounding_box": bbox,
                    "temporal": f"{start_date}T00:00:00Z,{end_date}T00:00:00Z",
                    "page_size": 200,
                    "page_num": page,
                },
                timeout=30,
            )
            resp.raise_for_status()
            entries = resp.json().get("feed", {}).get("entry", [])
            if not entries:
                break
            all_entries.extend(entries)
            page += 1
        return all_entries

    def _get_band_urls(self, granule: Dict, product: str) -> Dict[str, str]:
        suffixes = BAND_SUFFIXES.get(product, [])
        band_urls = {}
        for link in granule.get("links", []):
            href = link.get("href", "")
            if not href.startswith("https://"):
                continue
            if not href.endswith(".tif"):
                continue
            for suffix in suffixes:
                if suffix in href and "QA_" not in href:
                    band_urls[suffix] = href
                    break
        return band_urls

    def download_granule_bands(
        self, granule: Dict, product: str
    ) -> Optional[Dict[str, str]]:
        if not self._token:
            self.login()
        self.ensure_dirs()

        band_urls = self._get_band_urls(granule, product)
        if not band_urls:
            return None

        raw_dir = os.path.join(self.data_dir, "aster", "raw")
        downloaded = {}

        with httpx.Client(
            follow_redirects=True,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=300,
        ) as client:
            for band_name, url in band_urls.items():
                filename = os.path.basename(url)
                file_path = os.path.join(raw_dir, filename)

                if os.path.exists(file_path):
                    downloaded[band_name] = file_path
                    continue

                resp = client.get(url)
                resp.raise_for_status()
                with open(file_path, "wb") as out:
                    out.write(resp.content)
                downloaded[band_name] = file_path

        return downloaded

    def download_all_scenes(
        self,
        product: str,
        center_lon: float,
        center_lat: float,
        radius_km: float,
        start_date: str,
        end_date: str,
    ) -> List[Dict[str, str]]:
        bbox = self._get_bbox(center_lon, center_lat, radius_km)
        granules = self.search_granules(product, bbox, start_date, end_date)
        print(f"Encontradas {len(granules)} cenas {product}")

        all_scenes = []
        for i, granule in enumerate(granules):
            title = granule.get("title", f"scene_{i}")
            print(f"  Baixando {i+1}/{len(granules)}: {title[:60]}")
            scene = self.download_granule_bands(granule, product)
            if scene:
                all_scenes.append(scene)
        print(f"Baixadas {len(all_scenes)} cenas com bandas validas")
        return all_scenes

    def has_cached_composite(self, product: str) -> bool:
        composite_dir = os.path.join(self.data_dir, "aster", "composite")
        return os.path.exists(
            os.path.join(composite_dir, f"{product}_composite.tif")
        )

    def get_composite_path(self, product: str) -> str:
        return os.path.join(
            self.data_dir, "aster", "composite", f"{product}_composite.tif"
        )
