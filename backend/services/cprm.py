"""Servico CPRM — download de dados geologicos via WFS GeoSGB."""

import json
import os
from typing import Optional

import requests

WFS_BASE_URL = "https://geoservicos.sgb.gov.br/geoserver/wfs"

# Layers WFS disponíveis
GEOLOGY_LAYER = "geosgb:litoestratigrafia_estados"
OCCURRENCES_LAYER = "geosgb:ocorrencias_recursos_minerais"

# Paleta categórica (~25 cores) para siglas litoestratigráficas
SIGLA_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
    "#c49c94", "#f7b6d2", "#c7c7c7", "#dbdb8d", "#9edae5",
    "#393b79", "#637939", "#8c6d31", "#843c39", "#7b4173",
]

# Cores por era geológica (era_max)
ERA_COLORS = {
    "Paleoproterozóico": "#2ca02c",
    "Paleoproterozoico": "#2ca02c",
    "Neoproterozóico": "#1f77b4",
    "Neoproterozoico": "#1f77b4",
    "Mesoproterozóico": "#ff7f0e",
    "Mesoproterozoico": "#ff7f0e",
    "Mesozóico": "#d62728",
    "Mesozoico": "#d62728",
    "Cenozóico": "#9467bd",
    "Cenozoico": "#9467bd",
    "Paleozóico": "#8c564b",
    "Paleozoico": "#8c564b",
    "Arqueano": "#e377c2",
    "Fanerozoico": "#bcbd22",
    "Fanerozoico Indiviso": "#bcbd22",
}
DEFAULT_ERA_COLOR = "#7f7f7f"


class CPRMService:
    """Serviço para download de dados geológicos do GeoSGB (CPRM/SGB)."""

    def __init__(self, vectors_dir: str, bbox: tuple):
        """
        Args:
            vectors_dir: Diretório para salvar os GeoJSONs.
            bbox: Bounding box (lon_min, lat_min, lon_max, lat_max).
        """
        self.vectors_dir = vectors_dir
        self.bbox = bbox
        self._cache = {}

    def _geojson_path(self, layer_id: str) -> str:
        return os.path.join(self.vectors_dir, f"{layer_id}.geojson")

    def _wfs_get_features(self, layer_name: str, max_features: int = 5000) -> dict:
        """Baixa features de uma layer WFS como GeoJSON."""
        bbox_str = f"{self.bbox[1]},{self.bbox[0]},{self.bbox[3]},{self.bbox[2]}"
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": layer_name,
            "outputFormat": "application/json",
            "bbox": bbox_str,
            "srsName": "EPSG:4326",
            "count": max_features,
        }
        print(f"WFS request: {layer_name} bbox={self.bbox}")
        resp = requests.get(WFS_BASE_URL, params=params, timeout=120)
        resp.raise_for_status()
        return resp.json()

    def _save_geojson(self, layer_id: str, geojson: dict) -> str:
        """Salva GeoJSON no disco e no cache."""
        os.makedirs(self.vectors_dir, exist_ok=True)
        path = self._geojson_path(layer_id)
        with open(path, "w") as f:
            json.dump(geojson, f)
        self._cache[layer_id] = geojson
        print(f"Salvo {layer_id}: {len(geojson['features'])} features em {path}")
        return path

    def download_geology(self) -> dict:
        """Baixa litoestratigrafia e gera 2 GeoJSONs (por sigla e por era)."""
        data = self._wfs_get_features(GEOLOGY_LAYER)
        features = data.get("features", [])
        print(f"Geologia: {len(features)} poligonos baixados")

        # Coletar siglas únicas para mapear cores
        siglas = sorted(set(
            f.get("properties", {}).get("sigla", "?") or "?"
            for f in features
        ))
        sigla_color_map = {
            sigla: SIGLA_COLORS[i % len(SIGLA_COLORS)]
            for i, sigla in enumerate(siglas)
        }

        # GeoJSON por sigla (litho)
        litho_features = []
        for f in features:
            props = dict(f.get("properties", {}))
            sigla = props.get("sigla") or "?"
            props["color"] = sigla_color_map[sigla]
            litho_features.append({
                "type": "Feature",
                "geometry": f["geometry"],
                "properties": props,
            })
        litho_geojson = {"type": "FeatureCollection", "features": litho_features}
        self._save_geojson("geology-litho", litho_geojson)

        # GeoJSON por era (age)
        age_features = []
        for f in features:
            props = dict(f.get("properties", {}))
            era = props.get("era_max") or ""
            props["color"] = ERA_COLORS.get(era, DEFAULT_ERA_COLOR)
            age_features.append({
                "type": "Feature",
                "geometry": f["geometry"],
                "properties": props,
            })
        age_geojson = {"type": "FeatureCollection", "features": age_features}
        self._save_geojson("geology-age", age_geojson)

        return {"geology-litho": litho_geojson, "geology-age": age_geojson}

    def download_occurrences(self) -> dict:
        """Baixa ocorrências de recursos minerais e salva como GeoJSON."""
        data = self._wfs_get_features(OCCURRENCES_LAYER)
        features = data.get("features", [])
        print(f"Ocorrencias: {len(features)} pontos baixados")

        occ_features = []
        for f in features:
            props = dict(f.get("properties", {}))
            substancia = (props.get("substancia") or "").lower()
            is_gold = "ouro" in substancia or "au" == substancia
            props["color"] = "#ffd700" if is_gold else "#aaaaaa"
            props["radius"] = 8 if is_gold else 5
            occ_features.append({
                "type": "Feature",
                "geometry": f["geometry"],
                "properties": props,
            })
        occ_geojson = {"type": "FeatureCollection", "features": occ_features}
        self._save_geojson("mineral-occurrences", occ_geojson)
        return occ_geojson

    def download_all(self) -> dict:
        """Baixa todos os dados CPRM."""
        result = {}
        result.update(self.download_geology())
        result["mineral-occurrences"] = self.download_occurrences()
        return result

    def get_layer(self, layer_id: str) -> Optional[dict]:
        """Retorna GeoJSON do cache ou do disco."""
        if layer_id in self._cache:
            return self._cache[layer_id]

        path = self._geojson_path(layer_id)
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            self._cache[layer_id] = data
            return data

        return None

    def has_cache(self, layer_id: str) -> bool:
        """Verifica se existe cache no disco."""
        return os.path.exists(self._geojson_path(layer_id))
