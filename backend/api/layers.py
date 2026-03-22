import os

from fastapi import APIRouter, HTTPException

from backend.config import settings, STUDY_AREAS
from backend.services.gee import GEEService, LAYER_CONFIGS as GEE_LAYER_CONFIGS
from backend.services.vectors import VectorService

router = APIRouter(prefix="/api")

try:
    gee_service = GEEService()
except Exception as e:
    print(f"AVISO: GEE nao inicializou: {e}")
    gee_service = None

vector_service = VectorService()

# {area_id: {layer_id: result_dict}}
_generated_tiles = {}
_preload_status = {"running": False, "done": 0, "total": 0}

# Layers vetoriais globais (servidas de data/vectors/, sem area_id)
GLOBAL_VECTOR_LAYERS = {"mining-rights", "mining-available"}

# Layers vetoriais por area (servidas de data/areas/{area_id}/vectors/)
AREA_VECTOR_LAYERS = {"geology-litho", "geology-age", "mineral-occurrences"}

LOCAL_LAYER_CONFIGS = {
    "crosta-feox": {
        "name": "Crosta FeOx",
        "description": "PCA dirigida VNIR — oxidos de ferro (ASTER 2000-2008)",
    },
    "crosta-oh": {
        "name": "Crosta OH/Sericita",
        "description": "PCA dirigida SWIR — sericita/argilas (ASTER 2000-2008)",
    },
    "ninomiya-aloh": {
        "name": "Ninomiya AlOH",
        "description": "B7/(B6*B8) — argilas AlOH (ASTER 2000-2008)",
    },
    "ninomiya-mgoh": {
        "name": "Ninomiya MgOH",
        "description": "B7/(B6+B9) — clorita/talco/serpentina (ASTER 2000-2008)",
    },
    "ninomiya-ferrous": {
        "name": "Ninomiya Fe2+",
        "description": "B5/B4 — ferro ferroso (ASTER 2000-2008)",
    },
    "pca-tir": {
        "name": "PCA TIR",
        "description": "PCA exploratoria B10-B14 — silicificacao (ASTER 2000-2024)",
    },
}

GEOPHYSICS_CONFIGS = {
    "mag-anomaly": {"name": "Campo Magnetico", "description": "Campo magnetico anomalo interpolado (Projeto 1073)"},
    "mag-1dv": {"name": "1a Derivada Vertical", "description": "1a derivada vertical do campo magnetico (FFT)"},
    "mag-asa": {"name": "Sinal Analitico", "description": "Amplitude do sinal analitico magnetico (FFT)"},
    "gamma-k": {"name": "Potassio (K%)", "description": "Potassio percentual — gamaespectrometria"},
    "gamma-th": {"name": "Torio (eTh)", "description": "Torio equivalente (ppm) — gamaespectrometria"},
    "gamma-thk": {"name": "Razao Th/K", "description": "Razao Th/K — indicador de alteracao hidrotermal"},
    "gamma-ternary": {"name": "Ternario K-Th-U", "description": "Composicao RGB: R=K, G=Th, B=U"},
    "em-resist": {"name": "Resistividade EM", "description": "Resistividade eletromagnetica — detalhe Almas/Vale (19.6m)"},
    "em-gradient": {"name": "Gradiente Horiz. EM", "description": "Gradiente horizontal da resistividade EM — detalhe Almas/Vale (19.6m)"},
}

LAYERS = [
    # Sentinel-2
    {"id": "rgb-true", "name": "RGB Verdadeira", "category": "spectral", "source": "gee", "group": "Sentinel-2"},
    {"id": "rgb-false", "name": "RGB Falsa-cor", "category": "spectral", "source": "gee", "group": "Sentinel-2"},
    {"id": "iron-oxide", "name": "Oxidos de Ferro", "category": "spectral", "source": "gee", "group": "Sentinel-2"},
    {"id": "clay", "name": "Argilas / Sericita", "category": "spectral", "source": "gee", "group": "Sentinel-2"},
    # ASTER (GEE)
    {"id": "carbonate", "name": "Carbonatos", "category": "spectral", "source": "gee", "group": "ASTER (GEE)"},
    {"id": "silica", "name": "Silica", "category": "spectral", "source": "gee", "group": "ASTER (GEE)"},
    {"id": "gee-crosta-feox", "name": "Crosta FeOx", "category": "spectral", "source": "gee", "group": "ASTER (GEE)"},
    {"id": "gee-crosta-oh", "name": "Crosta OH", "category": "spectral", "source": "gee", "group": "ASTER (GEE)"},
    {"id": "gee-ninomiya-aloh", "name": "Ninomiya AlOH", "category": "spectral", "source": "gee", "group": "ASTER (GEE)"},
    {"id": "gee-ninomiya-mgoh", "name": "Ninomiya MgOH", "category": "spectral", "source": "gee", "group": "ASTER (GEE)"},
    {"id": "gee-ninomiya-ferrous", "name": "Ninomiya Fe2+", "category": "spectral", "source": "gee", "group": "ASTER (GEE)"},
    {"id": "gee-pca-tir", "name": "PCA TIR", "category": "spectral", "source": "gee", "group": "ASTER (GEE)"},
    # ASTER (Local)
    {"id": "crosta-feox", "name": "Crosta FeOx", "category": "spectral", "source": "local", "group": "ASTER (Local)"},
    {"id": "crosta-oh", "name": "Crosta OH/Sericita", "category": "spectral", "source": "local", "group": "ASTER (Local)"},
    {"id": "ninomiya-aloh", "name": "Ninomiya AlOH", "category": "spectral", "source": "local", "group": "ASTER (Local)"},
    {"id": "ninomiya-mgoh", "name": "Ninomiya MgOH", "category": "spectral", "source": "local", "group": "ASTER (Local)"},
    {"id": "ninomiya-ferrous", "name": "Ninomiya Fe2+", "category": "spectral", "source": "local", "group": "ASTER (Local)"},
    {"id": "pca-tir", "name": "PCA TIR", "category": "spectral", "source": "local", "group": "ASTER (Local)"},
    # Terreno
    {"id": "dem", "name": "DEM / Hillshade", "category": "terrain", "source": "gee", "group": "Terreno"},
    {"id": "lineaments", "name": "Lineamentos", "category": "terrain", "source": "local", "group": "Terreno"},
    # CPRM
    {"id": "mining-rights", "name": "Direitos Minerarios (ANM)", "category": "cprm", "source": "vector", "group": "CPRM"},
    {"id": "mining-available", "name": "Processos Caindo (TO)", "category": "cprm", "source": "vector", "group": "CPRM"},
    {"id": "geology-litho", "name": "Geologia (Litologia)", "category": "cprm", "source": "vector", "group": "CPRM"},
    {"id": "geology-age", "name": "Geologia (Idade)", "category": "cprm", "source": "vector", "group": "CPRM"},
    {"id": "mineral-occurrences", "name": "Ocorrencias Minerais", "category": "cprm", "source": "vector", "group": "CPRM"},
    # Geofisica
    {"id": "mag-anomaly", "name": "Campo Magnetico", "category": "geophysics", "source": "local", "group": "Geofisica"},
    {"id": "mag-1dv", "name": "1a Derivada Vertical", "category": "geophysics", "source": "local", "group": "Geofisica"},
    {"id": "mag-asa", "name": "Sinal Analitico", "category": "geophysics", "source": "local", "group": "Geofisica"},
    {"id": "gamma-k", "name": "Potassio (K%)", "category": "geophysics", "source": "local", "group": "Geofisica"},
    {"id": "gamma-th", "name": "Torio (eTh)", "category": "geophysics", "source": "local", "group": "Geofisica"},
    {"id": "gamma-thk", "name": "Razao Th/K", "category": "geophysics", "source": "local", "group": "Geofisica"},
    {"id": "gamma-ternary", "name": "Ternario K-Th-U", "category": "geophysics", "source": "local", "group": "Geofisica"},
    {"id": "em-resist", "name": "Resistividade EM", "category": "geophysics", "source": "local", "group": "Geofisica (Detalhe)"},
    {"id": "em-gradient", "name": "Gradiente Horiz. EM", "category": "geophysics", "source": "local", "group": "Geofisica (Detalhe)"},
    # Prospectividade
    {"id": "targets", "name": "Alvos", "category": "prospectivity", "source": "model", "group": "Prospectividade"},
]


def _get_area_processed_dir(area_id: str) -> str:
    return os.path.join(settings.data_dir, "areas", area_id, "rasters", "processed")


def _get_area_vectors_dir(area_id: str) -> str:
    return os.path.join(settings.data_dir, "areas", area_id, "vectors")


def _get_cog_path(area_id: str, layer_id: str) -> str:
    """Caminho do COG para uma layer numa area."""
    return os.path.join(_get_area_processed_dir(area_id), f"{layer_id}.tif")


def _check_local_available(layer_id: str, processed_dir: str) -> bool:
    cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
    return os.path.exists(cog_path)


def _get_area_generated(area_id: str) -> dict:
    if area_id not in _generated_tiles:
        _generated_tiles[area_id] = {}
    return _generated_tiles[area_id]


def _register_gee_cog(area_id: str, layer_id: str, cog_path: str, tile_service):
    """Registra COG GEE no tile_service e atualiza _generated_tiles."""
    is_rgb = gee_service.is_rgb_layer(layer_id) if gee_service else False
    default_range = gee_service.get_rgb_range(layer_id) if (gee_service and is_rgb) else None
    tile_service.register_cog(layer_id, cog_path, is_rgb=is_rgb, default_range=default_range)

    config = GEE_LAYER_CONFIGS[layer_id]
    area_gen = _get_area_generated(area_id)
    area_gen[layer_id] = {
        "layer_id": layer_id,
        "name": config["name"],
        "description": config["description"],
        "tile_url": f"/api/areas/{area_id}/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png",
    }


def _validate_area(area_id: str):
    if area_id not in STUDY_AREAS:
        raise HTTPException(status_code=404, detail=f"Area '{area_id}' nao encontrada")


@router.get("/areas/{area_id}/layers")
def list_layers(area_id: str):
    _validate_area(area_id)
    gee_layers = gee_service.get_available_layers() if gee_service else {}
    processed_dir = _get_area_processed_dir(area_id)
    vectors_dir = _get_area_vectors_dir(area_id)
    has_earthdata = bool(settings.earthdata_username and settings.earthdata_password)
    loading = _preload_status["running"]
    area_gen = _get_area_generated(area_id)
    result = []
    for layer in LAYERS:
        if layer["source"] == "gee":
            available = layer["id"] in area_gen
            can_generate = layer["id"] in gee_layers
            supports_colormap = (not gee_service.is_rgb_layer(layer["id"])) if (gee_service and layer["id"] in gee_layers) else (layer["id"] in area_gen)
        elif layer["source"] == "local" and layer["id"] in LOCAL_LAYER_CONFIGS:
            available = layer["id"] in area_gen or _check_local_available(layer["id"], processed_dir)
            can_generate = has_earthdata or available
            supports_colormap = True
        elif layer["source"] == "local" and layer["id"] in GEOPHYSICS_CONFIGS:
            available = layer["id"] in area_gen or _check_local_available(layer["id"], processed_dir)
            can_generate = True
            supports_colormap = layer["id"] != "gamma-ternary"
        elif layer["source"] == "vector":
            if layer["id"] in GLOBAL_VECTOR_LAYERS:
                available = vector_service.is_available(layer["id"])
            else:
                geojson_path = os.path.join(vectors_dir, f"{layer['id']}.geojson")
                available = os.path.exists(geojson_path)
            can_generate = True
            supports_colormap = False
        else:
            available = False
            can_generate = False
            supports_colormap = False
        layer_type = "vector" if layer["source"] == "vector" else "raster"
        result.append({**layer, "available": available, "can_generate": can_generate, "supports_colormap": supports_colormap, "type": layer_type})
    return {"layers": result, "loading": loading,
            "loaded": _preload_status["done"], "total": _preload_status["total"]}


@router.post("/areas/{area_id}/layers/{layer_id}/generate")
def generate_layer(area_id: str, layer_id: str):
    _validate_area(area_id)
    area_gen = _get_area_generated(area_id)

    # Se ja tem cache, retorna direto
    if layer_id in area_gen:
        return area_gen[layer_id]

    from backend.main import tile_services
    tile_service = tile_services.get(area_id)
    if not tile_service:
        raise HTTPException(status_code=404, detail=f"TileService nao encontrado para area '{area_id}'")

    gee_layers = gee_service.get_available_layers() if gee_service else {}

    # Layer GEE: download como COG
    if layer_id in gee_layers:
        cog_path = _get_cog_path(area_id, layer_id)

        if not os.path.exists(cog_path):
            try:
                area_config = STUDY_AREAS[area_id]
                gee_service.set_area(area_config["center_lon"], area_config["center_lat"], area_config["radius_km"])
                gee_service.download_layer_cog(layer_id, cog_path)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        _register_gee_cog(area_id, layer_id, cog_path, tile_service)
        return area_gen[layer_id]

    # Layer local
    if layer_id in LOCAL_LAYER_CONFIGS:
        processed_dir = _get_area_processed_dir(area_id)
        cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
        config = LOCAL_LAYER_CONFIGS[layer_id]

        if not os.path.exists(cog_path):
            if not settings.earthdata_username or not settings.earthdata_password:
                raise HTTPException(
                    status_code=400,
                    detail="Credenciais Earthdata nao configuradas. Defina earthdata_username e earthdata_password.",
                )
            area_config = STUDY_AREAS[area_id]
            from backend.services.pipeline import AsterPipeline
            pipeline = AsterPipeline(
                data_dir=settings.data_dir,
                earthdata_username=settings.earthdata_username,
                earthdata_password=settings.earthdata_password,
                center_lon=area_config["center_lon"],
                center_lat=area_config["center_lat"],
                radius_km=area_config["radius_km"],
            )
            pipeline.process_layer(layer_id)

        tile_service.register_cog(layer_id, cog_path)

        tile_url = f"/api/areas/{area_id}/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png"
        result = {
            "layer_id": layer_id,
            "name": config["name"],
            "description": config["description"],
            "tile_url": tile_url,
        }
        area_gen[layer_id] = result
        return result

    # Layer geofisica
    if layer_id in GEOPHYSICS_CONFIGS:
        processed_dir = _get_area_processed_dir(area_id)
        cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
        config = GEOPHYSICS_CONFIGS[layer_id]
        if not os.path.exists(cog_path):
            raise HTTPException(status_code=400, detail="COG geofisico nao encontrado. Processe os dados XYZ primeiro.")
        is_rgb = layer_id == "gamma-ternary"
        tile_service.register_cog(layer_id, cog_path, is_rgb=is_rgb)
        tile_url = f"/api/areas/{area_id}/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png"
        result = {"layer_id": layer_id, "name": config["name"], "description": config["description"], "tile_url": tile_url}
        area_gen[layer_id] = result
        return result

    # Layer vetorial
    layer_def = next((l for l in LAYERS if l["id"] == layer_id and l["source"] == "vector"), None)
    if layer_def:
        try:
            if layer_id in GLOBAL_VECTOR_LAYERS:
                # Vetoriais globais (mining-rights, mining-available)
                geojson = vector_service.get_geojson(layer_id)
                if not geojson:
                    geojson = vector_service.generate(layer_id)
                vector_url = f"/api/vectors/{layer_id}.geojson"
            else:
                # Vetoriais por area (geology-litho, geology-age, mineral-occurrences)
                vectors_dir = _get_area_vectors_dir(area_id)
                geojson_path = os.path.join(vectors_dir, f"{layer_id}.geojson")
                if os.path.exists(geojson_path):
                    import json
                    with open(geojson_path) as f:
                        geojson = json.load(f)
                else:
                    # Gerar usando CPRM service com bbox da area
                    area_config = STUDY_AREAS[area_id]
                    from backend.services.cprm import CPRMService
                    bbox = (
                        area_config["center_lon"] - area_config["radius_km"] / 111.32,
                        area_config["center_lat"] - area_config["radius_km"] / 111.32,
                        area_config["center_lon"] + area_config["radius_km"] / 111.32,
                        area_config["center_lat"] + area_config["radius_km"] / 111.32,
                    )
                    cprm = CPRMService(vectors_dir=vectors_dir, bbox=bbox)
                    if "geology" in layer_id:
                        cprm.download_geology()
                    else:
                        cprm.download_occurrences()
                    geojson = cprm.get_layer(layer_id)
                vector_url = f"/api/areas/{area_id}/vectors/{layer_id}.geojson"

            result = {
                "layer_id": layer_id,
                "name": layer_def["name"],
                "type": "vector",
                "vector_url": vector_url,
            }
            area_gen[layer_id] = result
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' nao disponivel para geracao")


def preload_layers(tile_service, area_id: str):
    """Pre-carrega todas as layers disponiveis para uma area."""
    processed_dir = _get_area_processed_dir(area_id)
    area_gen = _get_area_generated(area_id)

    print(f"  Preload area '{area_id}' ({processed_dir}):")

    # 1. Registrar COGs locais existentes (instantaneo)
    for layer_id in LOCAL_LAYER_CONFIGS:
        cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
        if os.path.exists(cog_path):
            tile_service.register_cog(layer_id, cog_path)
            config = LOCAL_LAYER_CONFIGS[layer_id]
            area_gen[layer_id] = {
                "layer_id": layer_id,
                "name": config["name"],
                "description": config["description"],
                "tile_url": f"/api/areas/{area_id}/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png",
            }
            print(f"    Local registrada: {layer_id}")

    # 2. Registrar COGs GEE existentes no disco (instantaneo)
    for layer_id in GEE_LAYER_CONFIGS:
        cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
        if os.path.exists(cog_path) and os.path.getsize(cog_path) > 0:
            try:
                is_rgb = gee_service.is_rgb_layer(layer_id) if gee_service else False
                default_range = gee_service.get_rgb_range(layer_id) if (gee_service and is_rgb) else None
                tile_service.register_cog(layer_id, cog_path, is_rgb=is_rgb, default_range=default_range)
                config = GEE_LAYER_CONFIGS[layer_id]
                area_gen[layer_id] = {
                    "layer_id": layer_id,
                    "name": config["name"],
                    "description": config["description"],
                    "tile_url": f"/api/areas/{area_id}/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png",
                }
                print(f"    GEE COG registrada: {layer_id}")
            except Exception as e:
                print(f"    AVISO: COG corrompido {layer_id}: {e}")
                os.remove(cog_path)

    # 3. Registrar COGs geofisicos
    for layer_id, config in GEOPHYSICS_CONFIGS.items():
        cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
        if os.path.exists(cog_path) and os.path.getsize(cog_path) > 0:
            try:
                is_rgb = layer_id == "gamma-ternary"
                default_range = (0, 255) if layer_id in ("em-resist", "em-gradient") else None
                tile_service.register_cog(layer_id, cog_path, is_rgb=is_rgb, default_range=default_range)
                area_gen[layer_id] = {
                    "layer_id": layer_id,
                    "name": config["name"],
                    "description": config["description"],
                    "tile_url": f"/api/areas/{area_id}/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png",
                }
                print(f"    Geofisica registrada: {layer_id}")
            except Exception as e:
                print(f"    AVISO: COG geofisico corrompido {layer_id}: {e}")

    # 4. Se houver COGs GEE faltantes, apenas logar
    missing = [lid for lid in GEE_LAYER_CONFIGS if lid not in area_gen]
    if missing:
        print(f"    {len(missing)} layers GEE sem COG: {', '.join(missing)}")
