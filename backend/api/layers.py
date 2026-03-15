import os

from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.services.gee import GEEService

router = APIRouter(prefix="/api")

gee_service = GEEService()

_generated_tiles = {}

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
    {"id": "rgb-true", "name": "RGB Verdadeira", "category": "spectral", "source": "gee"},
    {"id": "rgb-false", "name": "RGB Falsa-cor", "category": "spectral", "source": "gee"},
    {"id": "iron-oxide", "name": "Oxidos de Ferro", "category": "spectral", "source": "gee"},
    {"id": "clay", "name": "Argilas / Sericita", "category": "spectral", "source": "gee"},
    {"id": "carbonate", "name": "Carbonatos", "category": "spectral", "source": "gee"},
    {"id": "silica", "name": "Silica", "category": "spectral", "source": "gee"},
    {"id": "dem", "name": "DEM / Hillshade", "category": "terrain", "source": "gee"},
    {"id": "crosta-feox", "name": "Crosta FeOx", "category": "spectral", "source": "local"},
    {"id": "crosta-oh", "name": "Crosta OH/Sericita", "category": "spectral", "source": "local"},
    {"id": "ninomiya-aloh", "name": "Ninomiya AlOH", "category": "spectral", "source": "local"},
    {"id": "ninomiya-mgoh", "name": "Ninomiya MgOH", "category": "spectral", "source": "local"},
    {"id": "ninomiya-ferrous", "name": "Ninomiya Fe2+", "category": "spectral", "source": "local"},
    {"id": "pca-tir", "name": "PCA TIR", "category": "spectral", "source": "local"},
    {"id": "lineaments", "name": "Lineamentos", "category": "terrain", "source": "local"},
    {"id": "geology", "name": "Geologia (CPRM)", "category": "cprm", "source": "cprm"},
    {"id": "magnetic", "name": "Magnetico", "category": "cprm", "source": "cprm"},
    {"id": "gamma", "name": "Gamaespectrometrico", "category": "cprm", "source": "cprm"},
    {"id": "targets", "name": "Alvos", "category": "prospectivity", "source": "model"},
]


def _check_local_available(layer_id: str, processed_dir: str) -> bool:
    cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
    return os.path.exists(cog_path)


@router.get("/layers")
def list_layers():
    gee_layers = gee_service.get_available_layers()
    processed_dir = os.path.join(settings.data_dir, "rasters", "processed")
    has_earthdata = bool(settings.earthdata_username and settings.earthdata_password)
    result = []
    for layer in LAYERS:
        if layer["source"] == "gee":
            available = layer["id"] in _generated_tiles
            can_generate = layer["id"] in gee_layers
        elif layer["source"] == "local" and layer["id"] in LOCAL_LAYER_CONFIGS:
            available = _check_local_available(layer["id"], processed_dir)
            can_generate = has_earthdata or available
        else:
            available = False
            can_generate = False
        result.append({**layer, "available": available, "can_generate": can_generate})
    return result


@router.post("/layers/{layer_id}/generate")
def generate_layer(layer_id: str):
    gee_layers = gee_service.get_available_layers()

    # Layer GEE
    if layer_id in gee_layers:
        try:
            tile_data = gee_service.get_layer_tiles(layer_id)
            _generated_tiles[layer_id] = tile_data
            return tile_data
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # Layer local
    if layer_id in LOCAL_LAYER_CONFIGS:
        processed_dir = os.path.join(settings.data_dir, "rasters", "processed")
        cog_path = os.path.join(processed_dir, f"{layer_id}.tif")
        config = LOCAL_LAYER_CONFIGS[layer_id]

        if not os.path.exists(cog_path):
            raise HTTPException(
                status_code=404,
                detail=f"COG para '{layer_id}' nao encontrado. Execute o download ASTER primeiro.",
            )

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
