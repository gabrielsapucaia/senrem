import math
import os
import time
from typing import Dict, List, Optional

import httpx


APPEEARS_BASE = "https://appeears.earthdatacloud.nasa.gov/api"


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

    def build_task_payload(
        self,
        task_name: str,
        product: str,
        aoi: Dict,
        start_date: str,
        end_date: str,
    ) -> Dict:
        layer_map = {
            "AST_07XT": [
                f"AST_07XT.003_ImageData{i}" for i in range(1, 10)
            ],
            "AST_08": [
                f"AST_08.003_Emissivity_Mean_Band{i}" for i in range(10, 15)
            ],
        }
        layers = []
        for layer_name in layer_map.get(product, []):
            layers.append({"product": f"{product}.003", "layer": layer_name})

        return {
            "task_name": task_name,
            "task_type": "area",
            "params": {
                "dates": [{"startDate": start_date, "endDate": end_date}],
                "layers": layers,
                "geo": aoi,
                "output": {"format": {"type": "geotiff"}, "projection": "geographic"},
            },
        }

    def login(self) -> str:
        resp = httpx.post(
            f"{APPEEARS_BASE}/login",
            auth=(self.username, self.password),
            timeout=30,
        )
        resp.raise_for_status()
        self._token = resp.json()["token"]
        return self._token

    def submit_task(self, payload: Dict) -> str:
        if not self._token:
            self.login()
        resp = httpx.post(
            f"{APPEEARS_BASE}/task",
            json=payload,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["task_id"]

    def wait_for_task(
        self, task_id: str, poll_interval: int = 30, timeout: int = 3600
    ) -> bool:
        if not self._token:
            self.login()
        elapsed = 0
        while elapsed < timeout:
            resp = httpx.get(
                f"{APPEEARS_BASE}/task/{task_id}",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=30,
            )
            resp.raise_for_status()
            status = resp.json()["status"]
            if status == "done":
                return True
            if status == "error":
                raise RuntimeError(f"AppEEARS task {task_id} failed")
            time.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(f"AppEEARS task {task_id} timed out after {timeout}s")

    def download_files(self, task_id: str) -> List[str]:
        if not self._token:
            self.login()
        self.ensure_dirs()

        resp = httpx.get(
            f"{APPEEARS_BASE}/bundle/{task_id}",
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30,
        )
        resp.raise_for_status()
        files = resp.json()["files"]

        downloaded = []
        raw_dir = os.path.join(self.data_dir, "aster", "raw")
        for f in files:
            if not f["file_name"].endswith(".tif"):
                continue
            file_path = os.path.join(raw_dir, os.path.basename(f["file_name"]))
            if os.path.exists(file_path):
                downloaded.append(file_path)
                continue
            resp = httpx.get(
                f"{APPEEARS_BASE}/bundle/{task_id}/{f['file_id']}",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=300,
            )
            resp.raise_for_status()
            with open(file_path, "wb") as out:
                out.write(resp.content)
            downloaded.append(file_path)
        return downloaded

    def has_cached_composite(self, product: str) -> bool:
        composite_dir = os.path.join(self.data_dir, "aster", "composite")
        return os.path.exists(
            os.path.join(composite_dir, f"{product}_composite.tif")
        )

    def get_composite_path(self, product: str) -> str:
        return os.path.join(
            self.data_dir, "aster", "composite", f"{product}_composite.tif"
        )
