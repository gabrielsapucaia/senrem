import json
import os
import threading

from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.services.gee import GEEService, LAYER_CONFIGS as GEE_LAYER_CONFIGS

router = APIRouter(prefix="/api")

gee_service = GEEService()

_generated_tiles = {}
_preload_status = {"running": False, "done": 0, "total": 0}

CACHE_PATH = os.path.join(settings.data_dir, "gee_tile_cache.json")

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
    {"id": "geology", "name": "Geologia (CPRM)", "category": "cprm", "source": "cprm", "group": "CPRM"},
    {"id": "magnetic", "name": "Magnetico", "category": "cprm", "source": "cprm", "group": "CPRM"},
    {"id": "gamma", "name": "Gamaespectrometrico", "category": "cprm", "source": "cprm", "group": "CPRM"},
    # Prospectividade
    {"id": "targets", "name": "Alvos", "category": "prospectivity", "source": "model", "group": "Prospectividade"},
]


def _load_cache():
    """Carrega cache de tile URLs do disco."""
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {}


def _save_cache():
    """Salva cache de tile URLs GEE no disco."""
    gee_tiles = {k: v for k, v in _generated_tiles.items() if k in GEE_LAYER_CONFIGS}
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(gee_tiles, f, indent=2)


def _check_local_available(layer_id: str, processed_dir: str) -> bool:
    cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
    return os.path.exists(cog_path)


@router.get("/layers")
def list_layers():
    gee_layers = gee_service.get_available_layers()
    processed_dir = os.path.join(settings.data_dir, "rasters", "processed")
    has_earthdata = bool(settings.earthdata_username and settings.earthdata_password)
    loading = _preload_status["running"]
    result = []
    for layer in LAYERS:
        if layer["source"] == "gee":
            available = layer["id"] in _generated_tiles
            can_generate = layer["id"] in gee_layers
        elif layer["source"] == "local" and layer["id"] in LOCAL_LAYER_CONFIGS:
            available = layer["id"] in _generated_tiles or _check_local_available(layer["id"], processed_dir)
            can_generate = has_earthdata or available
        else:
            available = False
            can_generate = False
        result.append({**layer, "available": available, "can_generate": can_generate})
    return {"layers": result, "loading": loading,
            "loaded": _preload_status["done"], "total": _preload_status["total"]}


@router.post("/layers/{layer_id}/generate")
def generate_layer(layer_id: str):
    # Se ja tem cache, retorna direto
    if layer_id in _generated_tiles:
        return _generated_tiles[layer_id]

    gee_layers = gee_service.get_available_layers()

    # Layer GEE
    if layer_id in gee_layers:
        try:
            tile_data = gee_service.get_layer_tiles(layer_id)
            _generated_tiles[layer_id] = tile_data
            _save_cache()
            return tile_data
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # Layer local
    if layer_id in LOCAL_LAYER_CONFIGS:
        processed_dir = os.path.join(settings.data_dir, "rasters", "processed")
        cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
        config = LOCAL_LAYER_CONFIGS[layer_id]

        if not os.path.exists(cog_path):
            if not settings.earthdata_username or not settings.earthdata_password:
                raise HTTPException(
                    status_code=400,
                    detail="Credenciais Earthdata nao configuradas. Defina earthdata_username e earthdata_password.",
                )
            from backend.services.pipeline import AsterPipeline
            pipeline = AsterPipeline(
                data_dir=settings.data_dir,
                earthdata_username=settings.earthdata_username,
                earthdata_password=settings.earthdata_password,
                center_lon=settings.study_area_center_lon,
                center_lat=settings.study_area_center_lat,
                radius_km=settings.study_area_radius_km,
            )
            pipeline.process_layer(layer_id)

        # Registrar no tile service e retornar URL
        from backend.main import tile_service
        tile_service.register_cog(layer_id, cog_path)

        tile_url = f"/api/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png"
        result = {
            "layer_id": layer_id,
            "name": config["name"],
            "description": config["description"],
            "tile_url": tile_url,
        }
        _generated_tiles[layer_id] = result
        return result

    raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' nao disponivel para geracao")


@router.post("/layers/refresh")
def refresh_layers():
    """Limpa cache GEE e regenera todas as layers em background."""
    if _preload_status["running"]:
        return {"status": "already_running", "loaded": _preload_status["done"], "total": _preload_status["total"]}

    # Limpar cache GEE (manter locais)
    for layer_id in list(_generated_tiles.keys()):
        if layer_id in GEE_LAYER_CONFIGS:
            del _generated_tiles[layer_id]

    if os.path.exists(CACHE_PATH):
        os.remove(CACHE_PATH)

    _start_gee_preload()
    return {"status": "started", "total": _preload_status["total"]}


def _start_gee_preload():
    """Inicia pre-carregamento GEE em background thread."""
    gee_ids = list(GEE_LAYER_CONFIGS.keys())
    _preload_status["total"] = len(gee_ids)
    _preload_status["done"] = 0
    _preload_status["running"] = True

    def _preload_gee():
        for layer_id in gee_ids:
            if layer_id in _generated_tiles:
                _preload_status["done"] += 1
                continue
            try:
                tile_data = gee_service.get_layer_tiles(layer_id)
                _generated_tiles[layer_id] = tile_data
                _preload_status["done"] += 1
                print(f"  GEE pre-loaded: {layer_id} ({_preload_status['done']}/{_preload_status['total']})")
            except Exception as e:
                _preload_status["done"] += 1
                print(f"  AVISO: Falha ao pre-carregar {layer_id}: {e}")
        _preload_status["running"] = False
        _save_cache()
        print("Pre-carregamento completo!")

    thread = threading.Thread(target=_preload_gee, daemon=True)
    thread.start()


def preload_layers(tile_service):
    """Pre-carrega todas as layers disponiveis."""
    processed_dir = os.path.join(settings.data_dir, "rasters", "processed")

    # 1. Registrar COGs locais existentes (instantaneo)
    for layer_id in LOCAL_LAYER_CONFIGS:
        cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
        if os.path.exists(cog_path):
            tile_service.register_cog(layer_id, cog_path)
            config = LOCAL_LAYER_CONFIGS[layer_id]
            _generated_tiles[layer_id] = {
                "layer_id": layer_id,
                "name": config["name"],
                "description": config["description"],
                "tile_url": f"/api/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png",
            }
            print(f"  Local registrada: {layer_id}")

    # 2. Carregar cache GEE do disco (se existir)
    cached = _load_cache()
    if cached:
        _generated_tiles.update(cached)
        print(f"  Cache GEE carregado: {len(cached)} layers")
        return

    # 3. Sem cache: pre-gerar layers GEE em background
    _start_gee_preload()
