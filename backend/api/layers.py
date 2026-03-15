from fastapi import APIRouter

router = APIRouter(prefix="/api")

LAYERS = [
    {"id": "rgb-true", "name": "RGB Verdadeira", "category": "spectral", "available": False, "source": "gee"},
    {"id": "rgb-false", "name": "RGB Falsa-cor", "category": "spectral", "available": False, "source": "gee"},
    {"id": "iron-oxide", "name": "Oxidos de Ferro", "category": "spectral", "available": False, "source": "gee"},
    {"id": "clay", "name": "Argilas / Sericita", "category": "spectral", "available": False, "source": "gee"},
    {"id": "carbonate", "name": "Carbonatos", "category": "spectral", "available": False, "source": "gee"},
    {"id": "silica", "name": "Silica", "category": "spectral", "available": False, "source": "gee"},
    {"id": "dem", "name": "DEM / Hillshade", "category": "terrain", "available": False, "source": "gee"},
    {"id": "lineaments", "name": "Lineamentos", "category": "terrain", "available": False, "source": "local"},
    {"id": "geology", "name": "Geologia (CPRM)", "category": "cprm", "available": False, "source": "cprm"},
    {"id": "magnetic", "name": "Magnetico", "category": "cprm", "available": False, "source": "cprm"},
    {"id": "gamma", "name": "Gamaespectrometrico", "category": "cprm", "available": False, "source": "cprm"},
    {"id": "targets", "name": "Alvos", "category": "prospectivity", "available": False, "source": "model"},
]


@router.get("/layers")
def list_layers():
    return LAYERS
