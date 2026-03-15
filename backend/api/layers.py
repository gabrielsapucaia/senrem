from fastapi import APIRouter, HTTPException

from backend.services.gee import GEEService

router = APIRouter(prefix="/api")

gee_service = GEEService()

_generated_tiles = {}

LAYERS = [
    {"id": "rgb-true", "name": "RGB Verdadeira", "category": "spectral", "source": "gee"},
    {"id": "rgb-false", "name": "RGB Falsa-cor", "category": "spectral", "source": "gee"},
    {"id": "iron-oxide", "name": "Oxidos de Ferro", "category": "spectral", "source": "gee"},
    {"id": "clay", "name": "Argilas / Sericita", "category": "spectral", "source": "gee"},
    {"id": "carbonate", "name": "Carbonatos", "category": "spectral", "source": "gee"},
    {"id": "silica", "name": "Silica", "category": "spectral", "source": "gee"},
    {"id": "dem", "name": "DEM / Hillshade", "category": "terrain", "source": "gee"},
    {"id": "lineaments", "name": "Lineamentos", "category": "terrain", "source": "local"},
    {"id": "geology", "name": "Geologia (CPRM)", "category": "cprm", "source": "cprm"},
    {"id": "magnetic", "name": "Magnetico", "category": "cprm", "source": "cprm"},
    {"id": "gamma", "name": "Gamaespectrometrico", "category": "cprm", "source": "cprm"},
    {"id": "targets", "name": "Alvos", "category": "prospectivity", "source": "model"},
]


@router.get("/layers")
def list_layers():
    gee_layers = gee_service.get_available_layers()
    result = []
    for layer in LAYERS:
        available = layer["id"] in _generated_tiles
        can_generate = layer["id"] in gee_layers
        result.append({**layer, "available": available, "can_generate": can_generate})
    return result


@router.post("/layers/{layer_id}/generate")
def generate_layer(layer_id: str):
    gee_layers = gee_service.get_available_layers()
    if layer_id not in gee_layers:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' nao disponivel para geracao")
    try:
        tile_data = gee_service.get_layer_tiles(layer_id)
        _generated_tiles[layer_id] = tile_data
        return tile_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
