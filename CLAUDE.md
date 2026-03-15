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
- Painel lateral com 12 layers, secao de pesos

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
- Composite com reprojecao para grid EPSG:4326 ~30m (1699x1664) + normalizacao por cena (media/std)
- **Mascara NDVI<0.4 em TODAS as layers** (AST_07XT e AST_05), 36.8% vegetacao mascarada / 63.2% solo exposto
- NDVI composite separado (`AST_07XT_ndvi.tif`), computado pre-normalizacao, apenas cenas estacao seca (ago-out)
- Filtro sazonal ago-out (13 cenas de 49) para NDVI — consistente com GEE Fase 2 (62% exposto)
- Sem filtro sazonal, mediana NDVI de todas as 49 cenas mascarava 82.7% (cenas chuvosas inflam NDVI)
- NDVI computado por cena antes da normalizacao mean/std (normalizacao distorce relacoes inter-banda)
- Parsing mes do filename: `filename[12:14]` (formato AST_07XT_004MMDDYYYY...)
- Filtro mediana 3x3 no resultado final para suavizar artefatos residuais
- Tiles com colormap viridis via rio-tiler (rescale p2/p98 por layer)
- 49 cenas AST_07XT (2000-2008, ~4GB) + 223 cenas AST_05 (2000-2024)
- Suffixes: AST_07XT=SRF_VNIR_B01..SRF_SWIR_B09, AST_05=SRE_TIR_B10..SRE_TIR_B14
- Pipeline end-to-end funcionando: 6 COGs em data/rasters/processed/
- 34 testes passando
- Design: `docs/plans/2026-03-15-fase3-aster-design.md`
- Plano: `docs/plans/2026-03-15-fase3-implementation.md` (7 tasks)

### Comparacao GEE vs Local (CONCLUIDA)
- 6 layers ASTER duplicadas via GEE para comparacao visual com processamento local
- Layers GEE: Crosta FeOx/OH (PCA via eigendecomposicao), Ninomiya AlOH/MgOH/Fe2+ (ratios L1T), PCA TIR (ASTER GED emissividade 100m)
- PCA no GEE: `ee.Array.eigen()` + `matrixMultiply` + selecao Crosta automatica via `getInfo()` dos eigenvectors
- ASTER GED (`NASA/ASTER_GED/AG100_003`) para PCA TIR em vez de download AST_05
- Vis params GEE: paleta viridis hex + percentil stretch p2/p98 via `reduceRegion`
- **Pipeline GEE melhorado** (replica o pipeline local):
  1. Filtro sazonal ago-out (`calendarRange(8, 10, 'month')`) — estacao seca, consistente com local
  2. Normalizacao por cena (`.map()` com `mean/std` + `.toFloat()`) antes do `median()` — remove artefatos inter-cena
  3. Mascara NDVI<0.4 (Sentinel-2 dry season)
  4. Processamento (PCA/Crosta/ratios)
  5. Filtro mediana 3x3 (`focalMedian(1.5, 'square', 'pixels')`) — suaviza artefatos residuais
  6. `bestEffort=True` no `reduceRegion` para PCA — auto-ajusta escala se exceder memoria
- Scale PCA: 30m VNIR (FeOx), 60m SWIR (OH), 100m TIR — `bestEffort=True` permite tentar nativa
- Normalizacao: `normalize=True` para PCA/Crosta, `normalize=False` para ratios Ninomiya (auto-normalizantes)
- Tipo homogeneo: `.toFloat()` obrigatorio apos normalizacao (GEE rejeita `Float<range>` heterogeneo no `median()`)
- **Resultado:** layers GEE mais suaves e coerentes, mas locais continuam superiores (cobertura continua vs gaps GEE)
- Gaps de cobertura sao inerentes ao catalogo ASTER L1T no GEE (menos cenas validas, especialmente na seca)
- **Layers GEE servidas localmente como COGs** (nao usa mais getMapId)
- Download via `ee.Image.getDownloadURL()` → salva como GeoTIFF em `data/rasters/processed/`
- Download em grid paralelo para layers pesadas (S2 mediana 512 imgs excede memoria GEE):
  - S2 RGB: 20m, grid 4x4 (16 partes, 4 threads paralelas)
  - S2 ratios: 20m, grid 3x3 (9 partes)
  - ASTER VNIR (crosta-feox, ninomiya-ferrous): 30m, grid 2x2 (4 partes)
  - ASTER SWIR/TIR/DEM: download direto sem grid (60-100m)
- Mosaic local com `rasterio.merge` apos download em grid
- TileService com suporte a COGs RGB (3 bandas) e single-band (colormap)
- TileOutsideBounds retorna tile transparente (nao 500)
- Startup NAO baixa automaticamente — apenas registra COGs existentes do disco
- Botao "Atualizar Layers" apaga COGs GEE e re-baixa do zero (POST /api/layers/refresh)
- GET `/api/layers` retorna `{layers: [...], loading, loaded, total}` + campo `supports_colormap`
- Frontend usa `supports_colormap` para mostrar controles de colormap/min-max
- Sidebar organizado em grupos: Sentinel-2, ASTER (GEE), ASTER (Local), Terreno, CPRM, Prospectividade
- 13 layers GEE + 6 locais + 6 futuras = 25 layers no sidebar
- 38 testes passando

### Painel de Propriedades de Layer (CONCLUIDO)
- Segundo sidebar acoplado ao primeiro, aparece ao clicar no nome de uma layer ativa
- Controles universais (todas as layers, client-side via MapLibre paint properties):
  - Opacidade individual (0-100%, default 70%)
  - Brilho min/max (0-1, default 0/1)
  - Contraste (-1 a +1, default 0)
  - Saturacao (-1 a +1, default 0)
- Controles extras (layers single-band, via query params no tile endpoint):
  - Colormap (viridis, magma, plasma, inferno, turbo, cividis, greys)
  - Min/Max rescale (sliders com range dinamico baseado em p2/p98)
- Controles extras disponíveis para TODAS as layers single-band (GEE e locais) gracas ao COG local
- Layers RGB (rgb-true, rgb-false): apenas controles universais (colormap nao se aplica)
- Frontend usa campo `supports_colormap` da API (nao mais `source === "local"`)
- Endpoint de tiles aceita query params: `?colormap=X&vmin=Y&vmax=Z`
- Endpoint: GET `/api/tiles/{layer_id}/stats` retorna `{p2, p98}`
- 38 testes passando

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
│   │   ├── gee.py           # GEEService: 13 layers GEE (S2+ASTER L1T+GED)
│   │   │                    # PCA via eigen, ratios, download COG com grid paralelo
│   │   ├── aster.py         # AsterService: download via CMR API
│   │   ├── processing.py    # ProcessingService: PCA, Crosta, ratios Ninomiya
│   │   ├── tiles.py         # TileService: serve tiles locais via rio-tiler (RGB + singleband)
│   │   └── pipeline.py      # AsterPipeline: orquestra download->processamento->COG
│   └── models/              # (vazio, para Fase 5: prospectivity.py)
├── frontend/
│   ├── index.html           # SPA: header, sidebar, mapa, status bar
│   ├── style.css            # Tema escuro (#1a1a2e, #16213e, #e94560)
│   └── app.js               # MapLibre GL JS, enableLayer/disableLayer, basemaps
├── tests/                   # 38 testes (pytest + FastAPI TestClient)
├── data/                    # rasters/, vectors/, tiles/ (gitignored)
├── docs/plans/              # Design + planos de cada fase
├── requirements.txt
└── .gitignore
```

## Como rodar

```bash
source .venv/bin/activate
python -m backend.main          # servidor em http://localhost:8000
python -m pytest tests/ -v      # 38 testes
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
| GET | `/api/layers` | Lista 25 layers `{layers, loading, loaded, total}` |
| POST | `/api/layers/{id}/generate` | Baixa COG GEE/local e retorna tile_url local |
| POST | `/api/layers/refresh` | Apaga COGs GEE e re-baixa do zero em background |
| GET | `/api/tiles/{layer_id}/{z}/{x}/{y}.png` | Serve tiles de COGs locais (aceita ?colormap, ?vmin, ?vmax) |
| GET | `/api/tiles/{layer_id}/stats` | Retorna percentis p2/p98 da layer para sliders min/max |

## Convencoes

- Python 3.9.6 (versao do sistema no macOS)
- FastAPI com routers em `backend/api/`, prefixo `/api`
- Frontend vanilla (HTML/CSS/JS), sem framework, MapLibre GL JS v4.7.1 via CDN
- Testes com pytest + FastAPI TestClient
- Tema visual escuro (#1a1a2e, #16213e, #e94560)
- `app.mount("/", StaticFiles(...))` DEVE ser a ultima linha apos todos os `include_router`
- Commits em portugues, formato convencional (feat:, chore:, fix:)
- Tiles GEE servidos localmente via COGs (download via `getDownloadURL`, nao mais `getMapId`)
- Vis params dos ratios DEVEM ser calibrados com percentis reais (p2/p98) via GEE reduceRegion
- Ratios espectrais DEVEM usar estacao seca + mascara NDVI<0.4 para minimizar vegetacao

## Decisoes de design

- **Por que FastAPI + vanilla JS?** Controle total, sem overhead de framework frontend, deploy simples
- **Por que MapLibre GL JS?** Open-source, performatico para tiles raster, suporte a layers
- **Por que GEE → COG local?** GEE computa (median, PCA, ratios), baixa como GeoTIFF, serve via rio-tiler. Permite colormap/min-max para TODAS as layers.
- **Grid paralelo:** S2 mediana 512 imgs excede memoria do `getDownloadURL`. Solucao: dividir em grid (3x3 ou 4x4), baixar 4 threads paralelas, mosaic com rasterio
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
