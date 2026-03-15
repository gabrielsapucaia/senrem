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
  - RGB Verdadeira (Sentinel-2, ago-out 2017-2024, <20% nuvens)
  - RGB Falsa-cor (SWIR/NIR/Red, ago-out 2017-2024)
  - Oxidos de Ferro (B4/B2, min=1.65, max=2.45, mascara NDVI<0.4)
  - Argilas/Sericita (B11/B12, min=1.26, max=1.60, mascara NDVI<0.4)
  - Carbonatos (ASTER B13/B14, min=0.94, max=0.98, mascara NDVI)
  - Silica (ASTER B13/B10, min=1.37, max=1.41, mascara NDVI)
  - DEM/Hillshade (SRTM 30m)
- Filtro de vegetacao e janela temporal otimizados:
  - Pico da seca (ago-out 2017-2024, excluindo 2018 outlier chuvoso) — 512 imagens
  - Mascara NDVI < 0.4 nos ratios espectrais — 62% da area = solo exposto
  - ASTER usa mascara NDVI derivada do Sentinel-2 (melhor resolucao espacial)
  - RGB composicoes usam seca mas SEM mascara (para contexto visual)
  - Analise confirmou mascara urbana desnecessaria (0.11% da AOI)
- Toggle de layers via checkbox no frontend (enable/disable com tiles dinamicos)
- Slider de opacidade afeta todas as layers ativas
- Troca de basemap preserva layers ativas
- 13 testes automatizados passando

### Fase 3 — ASTER Local + Processamento Avancado (CONCLUIDA)
- Servico ASTER (`backend/services/aster.py`) — download via CMR API + Earthdata Bearer token (AppEEARS NAO tem AST_07XT)
- Servico de processamento (`backend/services/processing.py`) — PCA, Crosta (PCA dirigida), ratios Ninomiya
- Servico de tiles (`backend/services/tiles.py`) — serve tiles locais via rio-tiler
- Pipeline orquestrador (`backend/services/pipeline.py`) — download -> composite -> processamento -> COG
- 6 novas layers ASTER integradas no layers.py:
  - Crosta FeOx (PCA dirigida VNIR B1-B3, 2000-2008)
  - Crosta OH/Sericita (PCA dirigida SWIR B4-B7, 2000-2008)
  - Ninomiya AlOH B7/(B6*B8) (2000-2008)
  - Ninomiya MgOH B7/(B6+B9) (2000-2008)
  - Ninomiya Fe2+ B5/B4 (2000-2008)
  - PCA TIR B10-B14 CP2 (2000-2024)
- Endpoint de tiles: GET /api/tiles/{layer_id}/{z}/{x}/{y}.png
- Requer conta NASA Earthdata: credenciais em .env (EARTHDATA_USERNAME/PASSWORD)
- config.py com model_config = {"env_file": ".env"} para carregar credenciais
- ASTER SWIR (B4-B9) so existe 2000-2008 (falha do detector)
- TIR (B10-B14) existe 2000-2024
- AST_07XT v004 vem em GeoTIFs separados por banda (nao HDF), UTM, int16
- AST_08 trocado por AST_05 (emissividade) para PCA TIR
- Composite com reprojecao: todas as bandas reprojetadas para grid comum EPSG:4326 ~30m (1699x1664 pixels)
- 49 cenas AST_07XT (2000-2008, ~4GB) + 223 cenas AST_05 (2000-2024) baixadas
- Suffixes reais: AST_07XT=SRF_VNIR_B01..SRF_SWIR_B09, AST_05=SRE_TIR_B10..SRE_TIR_B14
- Pipeline testado end-to-end: 6 COGs processadas em data/rasters/processed/
- 34 testes automatizados passando
- Design: `docs/plans/2026-03-15-fase3-aster-design.md`
- Plano: `docs/plans/2026-03-15-fase3-implementation.md` (7 tasks)

### Fases futuras
- **Fase 4:** Dados CPRM (geologia, ocorrencias, geofisica via WMS/WFS e PGBC)
- **Fase 5:** Modelo de prospectividade (weighted overlay, painel de pesos ajustaveis)
- **Fase 6:** SAR/lineamentos, modelo data-driven (RF/SVM), export de relatorios

## Estrutura do projeto

```
senrem3/
├── backend/
│   ├── main.py              # FastAPI app, monta routers + serve frontend
│   ├── config.py            # Settings: coordenadas, raio, gee_project=c3po-461514
│   ├── api/
│   │   ├── config_routes.py # GET /api/config, GET /api/health
│   │   └── layers.py        # GET /api/layers, POST /api/layers/{id}/generate
│   ├── services/
│   │   ├── gee.py           # GEEService: LAYER_CONFIGS, tiles via getMapId()
│   │   │                    # Filtros: estacao seca + mascara NDVI<0.4
│   │   ├── aster.py         # AsterService: download via AppEEARS API
│   │   ├── processing.py    # ProcessingService: PCA, Crosta, ratios Ninomiya
│   │   ├── tiles.py         # TileService: serve tiles locais via rio-tiler
│   │   └── pipeline.py      # AsterPipeline: orquestra download->processamento->COG
│   └── models/              # (vazio, para Fase 5: prospectivity.py)
├── frontend/
│   ├── index.html           # SPA: header, sidebar, mapa, status bar
│   ├── style.css            # Tema escuro (#1a1a2e, #16213e, #e94560)
│   └── app.js               # MapLibre GL JS, enableLayer/disableLayer, basemaps
├── tests/                   # 13 testes (pytest + FastAPI TestClient)
├── data/                    # rasters/, vectors/, tiles/ (gitignored)
├── docs/plans/              # Design + planos de cada fase
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
| GET | `/api/layers` | Lista 19 layers com campos available/can_generate |
| POST | `/api/layers/{id}/generate` | Gera tiles GEE/locais e retorna tile_url |
| GET | `/api/tiles/{layer_id}/{z}/{x}/{y}.png` | Serve tiles de COGs locais (ASTER) |

## Convencoes

- Python 3.9.6 (versao do sistema no macOS)
- FastAPI com routers em `backend/api/`, prefixo `/api`
- Frontend vanilla (HTML/CSS/JS), sem framework, MapLibre GL JS v4.7.1 via CDN
- Testes com pytest + FastAPI TestClient
- Tema visual escuro (#1a1a2e, #16213e, #e94560)
- `app.mount("/", StaticFiles(...))` DEVE ser a ultima linha apos todos os `include_router`
- Commits em portugues, formato convencional (feat:, chore:, fix:)
- Tiles GEE servidos via `ee.Image.getMapId()` — sem download local
- Vis params dos ratios DEVEM ser calibrados com percentis reais (p2/p98) via GEE reduceRegion
- Ratios espectrais DEVEM usar estacao seca + mascara NDVI<0.4 para minimizar vegetacao

## Decisoes de design

- **Por que FastAPI + vanilla JS?** Controle total, sem overhead de framework frontend, deploy simples
- **Por que MapLibre GL JS?** Open-source, performatico para tiles raster, suporte a layers
- **Por que GEE + download local?** GEE para exploracao rapida, download para analises detalhadas (ASTER/Crosta)
- **Tiles direto do GEE:** `getMapId()` retorna URL template `{z}/{x}/{y}` compativel com MapLibre raster source
- **Janela ago-out 2017-2024:** Otimizada por analise mensal (set e o mes mais seco, jun atrapalha). 2018 excluido (outlier chuvoso). 512 imagens no composite
- **Mascara NDVI < 0.4:** 62% da area = solo exposto. Analise confirmou que qualityMosaic introduz artefatos (sombras). Mascara urbana desnecessaria (0.11% AOI)
- **Modelo de prospectividade:** Knowledge-driven (fuzzy/weighted overlay) como base, data-driven (RF/SVM) como complemento
- **Pesos do modelo:** Ajustaveis pelo usuario no frontend (sao hipoteses geologicas, nao constantes)

## Documentacao detalhada

- Design completo: `docs/plans/2026-03-15-senrem3-architecture-design.md`
- Plano Fase 1: `docs/plans/2026-03-15-fase1-base.md`
- Plano Fase 2: `docs/plans/2026-03-15-fase2-gee.md`
- Design Fase 3: `docs/plans/2026-03-15-fase3-aster-design.md`
- Plano Fase 3: `docs/plans/2026-03-15-fase3-implementation.md`
