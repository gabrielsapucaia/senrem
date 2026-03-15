# SENREM3 — Sensoriamento Remoto para Mineracao

## O que e este projeto

Sistema de sensoriamento remoto voltado a exploracao de ouro em Greenstone Belts.
FastAPI backend + frontend MapLibre GL JS para visualizacao interativa de dados geoespaciais.

**Area de estudo:** Raio de 25km em torno de -11.699153, -47.155531 (Greenstone Belt Natividade/Almas, Tocantins, Brasil).

**Objetivo final:** Dashboard web com layers de sensoriamento remoto (espectral, terreno, geofisica) e modelo de prospectividade mineral (knowledge-driven + data-driven) para rankeamento de alvos de ouro.

## Status atual

### Fase 1 — Base (CONCLUIDA)
- FastAPI servindo API + frontend estatico
- MapLibre GL JS com mapa interativo, area de estudo (circulo 25km), 3 basemaps (satelite, topo, escuro)
- Endpoints: `/api/config`, `/api/layers`, `/api/health`
- Painel lateral com 12 layers, slider de opacidade, secao de pesos

### Fase 2 — Google Earth Engine (CONCLUIDA)
- Servico GEE (`backend/services/gee.py`) integrado com projeto `c3po-461514`
- 7 layers funcionais com tiles servidos diretamente pelo GEE (sem download local):
  - RGB Verdadeira (Sentinel-2, mediana 2024, <20% nuvens)
  - RGB Falsa-cor (SWIR/NIR/Red)
  - Oxidos de Ferro (B4/B2, min=1.2, max=2.6)
  - Argilas/Sericita (B11/B12, min=1.3, max=2.3)
  - Carbonatos (ASTER B13/B14, min=0.94, max=0.98)
  - Silica (ASTER B13/B10, min=1.37, max=1.41)
  - DEM/Hillshade (SRTM 30m)
- Toggle de layers via checkbox no frontend (enable/disable com tiles dinamicos)
- Slider de opacidade afeta todas as layers ativas
- Troca de basemap preserva layers ativas
- Endpoint `POST /api/layers/{id}/generate` retorna tile URL do GEE
- Endpoint `GET /api/layers` agora retorna campos `available` e `can_generate`
- 13 testes automatizados passando
- Vis params calibrados com percentis reais (p2/p98) da area de estudo

### Proxima: Fase 3 — ASTER local + processamento avancado
- Download ASTER L1T para processamento local
- Metodo Crosta (PCA dirigida) para mapeamento de alteracao hidrotermal
- PCA para destaque de anomalias espectrais

### Fases futuras
- **Fase 4:** Dados CPRM (geologia, ocorrencias, geofisica via WMS/WFS e PGBC)
- **Fase 5:** Modelo de prospectividade (weighted overlay, painel de pesos ajustaveis)
- **Fase 6:** SAR/lineamentos, modelo data-driven (RF/SVM), export de relatorios

## Estrutura do projeto

```
senrem3/
├── backend/
│   ├── main.py              # FastAPI app, monta routers + serve frontend
│   ├── config.py            # Settings: coordenadas, raio, gee_project, etc.
│   ├── api/
│   │   ├── config_routes.py # GET /api/config, GET /api/health
│   │   └── layers.py        # GET /api/layers, POST /api/layers/{id}/generate
│   ├── services/
│   │   └── gee.py           # GEEService: tiles via getMapId(), LAYER_CONFIGS
│   └── models/              # (vazio, para Fase 5: prospectivity.py)
├── frontend/
│   ├── index.html           # SPA: header, sidebar, mapa, status bar
│   ├── style.css            # Tema escuro (#1a1a2e, #16213e, #e94560)
│   └── app.js               # MapLibre GL JS, enableLayer/disableLayer, basemaps
├── tests/
│   ├── test_config.py       # Testa /api/config e /api/health (2 testes)
│   ├── test_gee.py          # Testa GEEService init, bbox, tile URL (3 testes)
│   ├── test_gee_aster.py    # Testa layers ASTER carbonatos/silica (2 testes)
│   ├── test_layer_tiles.py  # Testa POST /api/layers/{id}/generate (3 testes)
│   └── test_layers.py       # Testa GET /api/layers (3 testes)
├── data/
│   ├── rasters/             # Cache de imagens processadas (gitignored)
│   ├── vectors/             # Shapefiles, GeoJSON (gitignored)
│   └── tiles/               # Tiles raster (gitignored)
├── docs/plans/
│   ├── 2026-03-15-senrem3-architecture-design.md  # Design completo do sistema
│   ├── 2026-03-15-fase1-base.md                   # Plano Fase 1 (executado)
│   └── 2026-03-15-fase2-gee.md                    # Plano Fase 2 (executado)
├── requirements.txt
└── .gitignore
```

## Como rodar

```bash
source .venv/bin/activate
python -m backend.main          # servidor em http://localhost:8000
python -m pytest tests/ -v      # 13 testes
```

## Configuracao GEE

- Projeto Google Cloud: `c3po-461514`
- Autenticacao: `earthengine authenticate` + `earthengine set_project c3po-461514`
- Configurado em `backend/config.py` campo `gee_project`

## API Endpoints

| Metodo | Rota | Descricao |
|--------|------|-----------|
| GET | `/api/health` | Health check |
| GET | `/api/config` | Retorna centro, raio, nome da area de estudo |
| GET | `/api/layers` | Lista 12 layers com campos available/can_generate |
| POST | `/api/layers/{id}/generate` | Gera tiles GEE e retorna tile_url |

## Convencoes

- Python 3.9.6 (versao do sistema no macOS)
- FastAPI com routers em `backend/api/`, prefixo `/api`
- Frontend vanilla (HTML/CSS/JS), sem framework, MapLibre GL JS v4.7.1 via CDN
- Testes com pytest + FastAPI TestClient
- Tema visual escuro (#1a1a2e, #16213e, #e94560)
- `app.mount("/", StaticFiles(...))` DEVE ser a ultima linha apos todos os `include_router`
- Commits em portugues, formato convencional (feat:, chore:, fix:)
- Tiles GEE servidos via `ee.Image.getMapId()` — sem download local na Fase 2
- Vis params dos ratios DEVEM ser calibrados com percentis reais da area (usar reduceRegion com Reducer.percentile)

## Decisoes de design

- **Por que FastAPI + vanilla JS?** Controle total, sem overhead de framework frontend, deploy simples
- **Por que MapLibre GL JS?** Open-source, performatico para tiles raster, suporte a layers
- **Por que GEE + download local?** GEE para exploracao rapida, download para analises detalhadas (ASTER/Crosta)
- **Tiles direto do GEE:** `getMapId()` retorna URL template `{z}/{x}/{y}` compativel com MapLibre raster source
- **Modelo de prospectividade:** Knowledge-driven (fuzzy/weighted overlay) como base, data-driven (RF/SVM) como complemento
- **Pesos do modelo:** Ajustaveis pelo usuario no frontend (sao hipoteses geologicas, nao constantes)

## Documentacao detalhada

- Design completo: `docs/plans/2026-03-15-senrem3-architecture-design.md`
- Plano Fase 1: `docs/plans/2026-03-15-fase1-base.md`
- Plano Fase 2: `docs/plans/2026-03-15-fase2-gee.md`
