# SENREM3 — Sensoriamento Remoto para Mineracao

## Contexto

Sistema de sensoriamento remoto voltado a exploracao de ouro em Greenstone Belts.
Area de estudo inicial: raio de 25km em torno de -11.699153, -47.155531 (Greenstone Belt Natividade/Almas, Tocantins, Brasil).

## Arquitetura

```
senrem3/
├── backend/
│   ├── main.py                 # FastAPI app, serve frontend
│   ├── config.py               # coordenadas, raio, paths
│   ├── services/
│   │   ├── gee.py              # Google Earth Engine
│   │   ├── download.py         # download local (Copernicus, EarthExplorer)
│   │   ├── cprm.py             # dados geofisicos SGB/CPRM
│   │   └── processing.py       # band ratios, PCA, Crosta
│   ├── models/
│   │   └── prospectivity.py    # integracao de camadas, scoring
│   └── api/
│       ├── layers.py           # listar/gerar layers
│       ├── analysis.py         # rodar analises sob demanda
│       └── targets.py          # alvos prospectivos
├── frontend/
│   ├── index.html              # SPA com MapLibre GL JS
│   ├── style.css
│   └── app.js                  # controle de layers, painel lateral
├── data/
│   ├── rasters/                # cache de imagens processadas
│   ├── vectors/                # shapefiles, geojson
│   └── tiles/                  # tiles raster gerados
├── requirements.txt
└── README.md
```

## Stack

- **Backend:** FastAPI, rasterio, geopandas, earthengine-api, scikit-learn, rio-tiler
- **Frontend:** MapLibre GL JS, HTML/CSS/JS vanilla
- **Formato de dados:** Cloud-Optimized GeoTIFF (COG), GeoJSON

## Fluxo

1. Usuario abre browser -> mapa centrado na area de estudo
2. Painel lateral lista layers disponiveis
3. Click para gerar/ativar layer -> API processa -> retorna tiles
4. Layers sobrepostas com controle de opacidade e toggle
5. Modulo de prospectividade integra layers e gera mapa de alvos

## Layers Disponiveis

### Via Google Earth Engine

| Layer | Fonte | Processamento |
|-------|-------|---------------|
| RGB verdadeira | Sentinel-2 SR | Mediana temporal, cloud masking |
| RGB falsa-cor | Sentinel-2 SR | SWIR/NIR/Red |
| Oxidos de ferro | Sentinel-2 / Landsat 9 | B4/B2, B11/B12 |
| Argilas / Sericita | ASTER | B5/B6, B7/B6 |
| Carbonatos | ASTER | B13/B14 |
| Silica | ASTER | B13/B10, B12/B13 |
| Alteracao hidrotermal | ASTER | Combinacao multi-ratio |
| DEM | SRTM 30m / Copernicus | Hillshade, slope, aspect |
| Lineamentos | DEM | Slope + edge detection |

### Via CPRM/SGB

- Mapa geologico (WMS/WFS -> GeoJSON)
- Aeromagnetico, gamaespectrometrico (PGBC)
- Ocorrencias minerais (pontos)

### Processamento Local

- Band ratios customizaveis
- PCA (anomalias espectrais)
- Metodo Crosta (ASTER, sericita/oxidos)
- SAR filtering (lineamentos, Sentinel-1)

## Modelo de Prospectividade

### Knowledge-Driven (Fuzzy Logic / Weighted Overlay)

| Evidencia | Peso | Justificativa |
|-----------|------|---------------|
| Proximidade a zonas de cisalhamento | 0.25 | Controle estrutural principal |
| Alteracao sericitica/carbonatica | 0.20 | Alteracao hidrotermal proximal |
| Oxidos de ferro (gossan) | 0.15 | Indicador superficial |
| Litologia favoravel (BIF, metavulcanicas) | 0.15 | Hospedeiras tipicas |
| Anomalia magnetica | 0.10 | BIFs e estruturas |
| Anomalia K/Th (gama) | 0.10 | Alteracao potassica |
| Proximidade a ocorrencias conhecidas | 0.05 | Validacao |

Pesos ajustaveis pelo usuario no frontend.
Output: mapa continuo 0-1 de favorabilidade + clusters de alvos prioritarios.

### Data-Driven (fase 2)

- Random Forest / SVM com ocorrencias como treino
- Comparacao com modelo knowledge-driven

## API REST

```
GET  /api/layers
POST /api/layers/{layer_id}/generate
GET  /api/tiles/{layer_id}/{z}/{x}/{y}.png

GET  /api/analysis/band-ratio
POST /api/analysis/pca
POST /api/analysis/crosta

POST /api/targets/generate
GET  /api/targets
PATCH /api/targets/weights

GET  /api/cprm/geology
GET  /api/cprm/occurrences
GET  /api/cprm/geophysics/{type}

GET  /api/config
```

## Frontend Layout

```
┌──────────────────────────────────────────────────┐
│  SENREM3 — Sensoriamento Remoto para Mineracao   │
├────────────┬─────────────────────────────────────┤
│ LAYERS     │          MAPA INTERATIVO            │
│ ☑ Base     │        (MapLibre GL JS)             │
│ ☐ Fe Ox    │                                     │
│ ☐ Argilas  │     ● centro da area de estudo      │
│ ☐ DEM      │     ○ raio 25km                     │
│ ☐ Mag      │                                     │
│ ☐ Gama     │                                     │
│ ☐ Alvos    │                                     │
│            │                                     │
│ OPACIDADE  │                                     │
│  ━━━━○━━━  │                                     │
│            │                                     │
│ PESOS      │                                     │
│ Estrut 25% │                                     │
│ Alter  20% │                                     │
│ FeOx   15% │                                     │
│            │                                     │
│ [GERAR     │                                     │
│  ALVOS]    │                                     │
├────────────┴─────────────────────────────────────┤
│ Status: Pronto │ Coord: -11.69, -47.15           │
└──────────────────────────────────────────────────┘
```

## Faseamento

| Fase | Escopo | Resultado |
|------|--------|-----------|
| 1 — Base | FastAPI + frontend + mapa + area de estudo | Mapa funcional |
| 2 — GEE | Composicoes RGB, band ratios, DEM via GEE | Primeiras layers |
| 3 — ASTER | Download ASTER, Crosta, PCA | Alteracao hidrotermal |
| 4 — CPRM | Geologia, ocorrencias, geofisica | Contexto regional |
| 5 — Prospectividade | Modelo knowledge-driven, painel pesos, alvos | Mapa favorabilidade |
| 6 — Refinamento | SAR, data-driven model, export relatorios | Sistema completo |

## Dependencias

```
fastapi
uvicorn
rasterio
geopandas
shapely
pyproj
numpy
scikit-learn
earthengine-api
requests
httpx
titiler.core
rio-tiler
pydantic
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
earthengine authenticate
python backend/main.py
```
