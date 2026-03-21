import json
import os
import zipfile

import geopandas as gpd
import requests
from shapely.geometry import Point

from backend.config import settings

ANM_BASE_URL = "https://app.anm.gov.br/dadosabertos/SIGMINE/PROCESSOS_MINERARIOS"

# Campos a manter no GeoJSON final
KEEP_FIELDS = ["PROCESSO", "NOME", "FASE", "SUBS", "AREA_HA", "UF"]

FASES_CAINDO = ["APTO PARA DISPONIBILIDADE", "DISPONIBILIDADE"]


class VectorService:
    def __init__(self):
        self.data_dir = os.path.join(settings.data_dir, "vectors")
        self._cache = {}

    def _anm_dir(self):
        return os.path.join(self.data_dir, "anm")

    def _geojson_path(self, layer_id: str) -> str:
        return os.path.join(self.data_dir, f"{layer_id}.geojson")

    def download_mining_rights(self) -> str:
        """Baixa shapefile de processos minerarios do Tocantins (ANM/SIGMINE)."""
        anm_dir = self._anm_dir()
        os.makedirs(anm_dir, exist_ok=True)

        zip_path = os.path.join(anm_dir, "TO.zip")
        url = f"{ANM_BASE_URL}/TO.zip"

        print(f"Baixando dados ANM: {url}")
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()

        with open(zip_path, "wb") as f:
            f.write(resp.content)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(anm_dir)

        print(f"ANM extraido em {anm_dir}")
        return anm_dir

    def _find_shapefile(self) -> str:
        """Encontra o .shp dentro do diretorio ANM."""
        anm_dir = self._anm_dir()
        for f in os.listdir(anm_dir):
            if f.endswith(".shp"):
                return os.path.join(anm_dir, f)
        raise FileNotFoundError(f"Nenhum .shp encontrado em {anm_dir}")

    def _build_study_area(self):
        """Cria poligono circular da area de estudo."""
        center = Point(settings.study_area_center_lon, settings.study_area_center_lat)
        study_area = gpd.GeoSeries([center], crs="EPSG:4326")
        study_area_proj = study_area.to_crs("EPSG:32723")
        buffer = study_area_proj.buffer(settings.study_area_radius_km * 1000)
        return buffer.to_crs("EPSG:4326").iloc[0]

    def process_mining_rights(self) -> dict:
        """Processa shapefile ANM: todo o Tocantins + classificacao Aura."""
        shp_path = self._find_shapefile()
        gdf = gpd.read_file(shp_path)

        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs("EPSG:4326")

        if gdf.empty:
            return {"type": "FeatureCollection", "features": []}

        gdf["is_aura"] = gdf["NOME"].str.contains("AURA", case=False, na=False)

        keep = [c for c in KEEP_FIELDS if c in gdf.columns] + ["is_aura", "geometry"]
        gdf = gdf[keep]

        geojson = json.loads(gdf.to_json())

        geojson_path = self._geojson_path("mining-rights")
        os.makedirs(os.path.dirname(geojson_path), exist_ok=True)
        with open(geojson_path, "w") as f:
            json.dump(geojson, f)

        self._cache["mining-rights"] = geojson
        print(f"Direitos minerarios: {len(geojson['features'])} poligonos no Tocantins")
        return geojson

    def process_mining_available(self) -> dict:
        """Processa processos minerarios caindo (Apto p/ Disponib. + Disponibilidade) em todo o TO."""
        shp_path = self._find_shapefile()
        gdf = gpd.read_file(shp_path)

        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs("EPSG:4326")

        gdf = gdf[gdf["FASE"].isin(FASES_CAINDO)].copy()

        if gdf.empty:
            return {"type": "FeatureCollection", "features": []}

        gdf["is_ouro"] = gdf["SUBS"].str.contains("OURO|GOLD", case=False, na=False)

        keep = [c for c in KEEP_FIELDS if c in gdf.columns] + ["is_ouro", "geometry"]
        gdf = gdf[keep]

        geojson = json.loads(gdf.to_json())

        geojson_path = self._geojson_path("mining-available")
        os.makedirs(os.path.dirname(geojson_path), exist_ok=True)
        with open(geojson_path, "w") as f:
            json.dump(geojson, f)

        self._cache["mining-available"] = geojson
        n_ouro = sum(1 for f in geojson["features"] if f["properties"].get("is_ouro"))
        print(f"Processos caindo: {len(geojson['features'])} total, {n_ouro} com ouro")
        return geojson

    def get_geojson(self, layer_id: str) -> dict:
        """Retorna GeoJSON cacheado ou do disco."""
        if layer_id in self._cache:
            return self._cache[layer_id]

        geojson_path = self._geojson_path(layer_id)
        if os.path.exists(geojson_path):
            with open(geojson_path) as f:
                data = json.load(f)
            self._cache[layer_id] = data
            return data

        return None

    def is_available(self, layer_id: str) -> bool:
        return os.path.exists(self._geojson_path(layer_id))

    def generate(self, layer_id: str) -> dict:
        """Download + processamento completo."""
        if layer_id == "mining-rights":
            self.download_mining_rights()
            return self.process_mining_rights()
        if layer_id == "mining-available":
            if not os.path.exists(os.path.join(self._anm_dir(), "TO.zip")):
                self.download_mining_rights()
            return self.process_mining_available()
        if layer_id in ("geology-litho", "geology-age", "mineral-occurrences"):
            return self._generate_cprm(layer_id)
        raise ValueError(f"Layer vetorial desconhecida: {layer_id}")

    def _generate_cprm(self, layer_id: str) -> dict:
        from backend.services.cprm import CPRMService
        bbox = (
            settings.study_area_center_lon - settings.study_area_radius_km / 111.32,
            settings.study_area_center_lat - settings.study_area_radius_km / 111.32,
            settings.study_area_center_lon + settings.study_area_radius_km / 111.32,
            settings.study_area_center_lat + settings.study_area_radius_km / 111.32,
        )
        cprm = CPRMService(vectors_dir=self.data_dir, bbox=bbox)
        if "geology" in layer_id:
            cprm.download_geology()
        else:
            cprm.download_occurrences()
        return cprm.get_layer(layer_id)
