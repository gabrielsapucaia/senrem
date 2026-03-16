import os
import threading

from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.services.gee import GEEService, LAYER_CONFIGS as GEE_LAYER_CONFIGS

router = APIRouter(prefix="/api")

try:
    gee_service = GEEService()
except Exception as e:
    print(f"AVISO: GEE nao inicializou: {e}")
    gee_service = None

_generated_tiles = {}
_preload_status = {"running": False, "done": 0, "total": 0}

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


def _get_gee_cog_path(layer_id: str) -> str:
    """Caminho do COG para layers GEE."""
    processed_dir = os.path.join(settings.data_dir, "rasters", "processed")
    return os.path.join(processed_dir, f"{layer_id}.tif")


def _check_local_available(layer_id: str, processed_dir: str) -> bool:
    cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
    return os.path.exists(cog_path)


def _register_gee_cog(layer_id: str, cog_path: str):
    """Registra COG GEE no tile_service e atualiza _generated_tiles."""
    from backend.main import tile_service
    is_rgb = gee_service.is_rgb_layer(layer_id) if gee_service else False
    default_range = gee_service.get_rgb_range(layer_id) if (gee_service and is_rgb) else None
    tile_service.register_cog(layer_id, cog_path, is_rgb=is_rgb, default_range=default_range)

    config = GEE_LAYER_CONFIGS[layer_id]
    _generated_tiles[layer_id] = {
        "layer_id": layer_id,
        "name": config["name"],
        "description": config["description"],
        "tile_url": f"/api/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png",
    }


@router.get("/layers")
def list_layers():
    gee_layers = gee_service.get_available_layers() if gee_service else {}
    processed_dir = os.path.join(settings.data_dir, "rasters", "processed")
    has_earthdata = bool(settings.earthdata_username and settings.earthdata_password)
    loading = _preload_status["running"]
    result = []
    for layer in LAYERS:
        if layer["source"] == "gee":
            available = layer["id"] in _generated_tiles
            can_generate = layer["id"] in gee_layers
            supports_colormap = (not gee_service.is_rgb_layer(layer["id"])) if (gee_service and layer["id"] in gee_layers) else (layer["id"] in _generated_tiles)
        elif layer["source"] == "local" and layer["id"] in LOCAL_LAYER_CONFIGS:
            available = layer["id"] in _generated_tiles or _check_local_available(layer["id"], processed_dir)
            can_generate = has_earthdata or available
            supports_colormap = True
        else:
            available = False
            can_generate = False
            supports_colormap = False
        result.append({**layer, "available": available, "can_generate": can_generate, "supports_colormap": supports_colormap})
    return {"layers": result, "loading": loading,
            "loaded": _preload_status["done"], "total": _preload_status["total"]}


@router.post("/layers/{layer_id}/generate")
def generate_layer(layer_id: str):
    # Se ja tem cache, retorna direto
    if layer_id in _generated_tiles:
        return _generated_tiles[layer_id]

    gee_layers = gee_service.get_available_layers() if gee_service else {}

    # Layer GEE: download como COG
    if layer_id in gee_layers:
        cog_path = _get_gee_cog_path(layer_id)

        if not os.path.exists(cog_path):
            try:
                gee_service.download_layer_cog(layer_id, cog_path)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        _register_gee_cog(layer_id, cog_path)
        return _generated_tiles[layer_id]

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
    """Apaga COGs GEE e re-baixa do zero."""
    if _preload_status["running"]:
        return {"status": "already_running", "loaded": _preload_status["done"], "total": _preload_status["total"]}

    # Apagar COGs GEE do disco
    for layer_id in list(_generated_tiles.keys()):
        if layer_id in GEE_LAYER_CONFIGS:
            cog_path = _get_gee_cog_path(layer_id)
            if os.path.exists(cog_path):
                os.remove(cog_path)
            del _generated_tiles[layer_id]

    if not gee_service:
        return {"status": "error", "detail": "GEE nao disponivel"}
    _start_gee_download()
    return {"status": "started", "total": _preload_status["total"]}


def _start_gee_download():
    """Inicia download paralelo de COGs GEE em background.

    Baixa ate 3 layers simultaneamente. Cada layer com grid
    tambem usa paralelismo interno (4 threads por grid).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    gee_ids = [lid for lid in GEE_LAYER_CONFIGS if lid not in _generated_tiles]
    if not gee_ids:
        print("Todas as layers GEE ja tem COGs no disco.")
        return

    _preload_status["total"] = len(gee_ids)
    _preload_status["done"] = 0
    _preload_status["running"] = True

    def _download_one(layer_id):
        cog_path = _get_gee_cog_path(layer_id)
        print(f"  Baixando GEE: {layer_id}...")
        gee_service.download_layer_cog(layer_id, cog_path)
        _register_gee_cog(layer_id, cog_path)
        _preload_status["done"] += 1
        print(f"  GEE downloaded: {layer_id} ({_preload_status['done']}/{_preload_status['total']})")

    def _download_all():
        # Layers simples (sem grid) em paralelo: ate 3 simultaneas
        # Layers com grid: 1 por vez (ja usam 4 threads internamente)
        simple = [lid for lid in gee_ids if gee_service._get_download_config(lid)[1] == 1]
        grid = [lid for lid in gee_ids if gee_service._get_download_config(lid)[1] > 1]

        # Baixar layers simples em paralelo (rapidas, ~10-30s cada)
        if simple:
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(_download_one, lid): lid for lid in simple}
                for future in as_completed(futures):
                    lid = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        _preload_status["done"] += 1
                        print(f"  AVISO: Falha ao baixar {lid}: {e}")

        # Baixar layers com grid (pesadas, ja paralelas internamente)
        for layer_id in grid:
            try:
                _download_one(layer_id)
            except Exception as e:
                _preload_status["done"] += 1
                print(f"  AVISO: Falha ao baixar {layer_id}: {e}")

        _preload_status["running"] = False
        print("Download GEE completo!")

    thread = threading.Thread(target=_download_all, daemon=True)
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

    # 2. Registrar COGs GEE existentes no disco (instantaneo)
    for layer_id in GEE_LAYER_CONFIGS:
        cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
        if os.path.exists(cog_path) and os.path.getsize(cog_path) > 0:
            try:
                is_rgb = gee_service.is_rgb_layer(layer_id) if gee_service else False
                default_range = gee_service.get_rgb_range(layer_id) if (gee_service and is_rgb) else None
                tile_service.register_cog(layer_id, cog_path, is_rgb=is_rgb, default_range=default_range)
                config = GEE_LAYER_CONFIGS[layer_id]
                _generated_tiles[layer_id] = {
                    "layer_id": layer_id,
                    "name": config["name"],
                    "description": config["description"],
                    "tile_url": f"/api/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png",
                }
                print(f"  GEE COG registrada: {layer_id}")
            except Exception as e:
                print(f"  AVISO: COG corrompido {layer_id}: {e}")
                os.remove(cog_path)

    # 3. Se houver COGs GEE faltantes, apenas logar (nao baixa automaticamente)
    missing = [lid for lid in GEE_LAYER_CONFIGS if lid not in _generated_tiles]
    if missing:
        print(f"  {len(missing)} layers GEE sem COG: {', '.join(missing)}")
        print("  Use POST /api/layers/refresh para baixar, ou clique 'Atualizar Layers'.")
