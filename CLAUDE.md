# SENREM3 — Sensoriamento Remoto para Mineracao

## O que e este projeto

Sistema de sensoriamento remoto voltado a exploracao de ouro em Greenstone Belts.
FastAPI backend + frontend MapLibre GL JS para visualizacao interativa de dados geoespaciais.

**Areas de estudo (multi-area):**
- **Paiol (Almas):** -11.699153, -47.155531, raio 30km (default)
- **Engegold:** -11.618848, -47.749978, raio 30km
- **Principe:** -11.926552, -47.610254, raio 30km
- **Manduca:** -10.815478, -48.331875, raio 30km

Tocantins, Brasil. Skill `/add-study-area` para adicionar novas areas.

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
- Download em grid paralelo para layers pesadas (raio 30km excede memoria GEE):
  - S2 RGB 10m: grid 7x7 (49 partes, 4 threads paralelas)
  - S2 ratios 20m: grid 5x5 (25 partes)
  - ASTER VNIR 15m (crosta-feox, ninomiya-ferrous): grid 8x8 (64 partes)
  - ASTER SWIR 30m: grid 3x3 (9 partes)
  - ASTER TIR 90m: grid 2x2 (4 partes)
  - DEM: download direto (leve)
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

### Deploy na Railway (CONCLUIDO)
- **URL producao:** https://senrem-production.up.railway.app
- **GitHub:** git@github.com:gabrielsapucaia/senrem.git (branch main)
- **Plataforma:** Railway (projeto `respectful-perfection`, regiao us-east4)
- **Dockerfile:** Python 3.11-slim + libgdal-dev, serve via `python -m backend.main`
- **Volume persistente:** montado em `/app/data` para COGs (205MB, 19 layers)
- **GEE Service Account:** `senrem3-gee@c3po-461514.iam.gserviceaccount.com`
  - Roles: `earthengine.admin` + `serviceUsageConsumer`
  - Chave JSON na variavel de ambiente `GEE_SERVICE_ACCOUNT_KEY`
  - Localmente: credenciais via `earthengine authenticate` (sem service account)
- **Variaveis Railway:** `PORT=8000`, `GEE_SERVICE_ACCOUNT_KEY`
- **Deploy automatico:** push no GitHub dispara rebuild na Railway
- **GEE init resiliente:** se GEE falhar no init, app sobe sem GEE (layers existentes no disco funcionam)
- **COGs corrompidos:** startup ignora arquivos vazios/corrompidos (remove e loga aviso)
- **COGs enviados** via endpoint temporario de upload (removido apos popular)
- **Plano trial:** 30 dias ou $5.00, 512MB RAM — download GEE com grid pode crashar por OOM
- **Producao desatualizada:** precisa re-deploy com COGs multi-area (novo endpoint upload ou HF Spaces)
- 61 testes passando

### Fase 4 — Dados CPRM/SGB e Aerogeofísica (CONCLUIDA)
- Servico CPRM (`backend/services/cprm.py`) — download WFS GeoSGB, cache GeoJSON local
  - `geosgb:litoestratigrafia_estados` — 116 poligonos geologicos na area (1:500k)
  - `geosgb:ocorrencias_recursos_minerais` — 8 pontos (3 de ouro: Mina do Paiol, Garimpo Vira Saia, Corrego Paiol)
- Servico geofisica (`backend/services/geophysics.py`) — processamento XYZ bruto Projeto 1073 Tocantins
  - Parser Geosoft XYZ (magnetico e gamaespectrometrico)
  - Recorte por bbox da area de estudo (~5MB de pontos de 6.8GB total)
  - Interpolacao cubic via `scipy.griddata` a 125m (~0.00125°)
  - Derivados magneticos via FFT: 1a derivada vertical, amplitude sinal analitico
  - Ternario K-Th-U: RGB normalizado p2/p98
- EM resistividade (detalhe Almas/Vale): RGB pre-renderizado convertido para single-band via hue extraction
- WFS endpoint: `https://geoservicos.sgb.gov.br/geoserver/wfs`
- 12 novas layers:
  - CPRM: Direitos Minerarios (ANM), Geologia Litologia, Geologia Idade, Ocorrencias Minerais
  - Geofisica: Campo Magnetico, 1DV, Sinal Analitico, K%, eTh, Th/K, Ternario K-Th-U
  - Geofisica Detalhe: Resistividade EM, Gradiente Horizontal EM
- Frontend: rendering generico vetorial (poligonos geologia com cor por sigla/era, pontos ocorrencias com popup)
- Endpoint: GET `/api/vectors/{layer_id}.geojson` retorna GeoJSON
- 59 testes passando
- Design: `docs/plans/2026-03-15-fase4-cprm-design.md`
- Plano: `docs/plans/2026-03-15-fase4-implementation.md`

### Reestruturacao Multi-Area (CONCLUIDA)
- Backend reestruturado: rotas `/api/layers` → `/api/areas/{area_id}/layers`
- 3 areas de estudo: paiol (default), engegold, principe — configuradas em `config.py` STUDY_AREAS
- Frontend com seletor de area (dropdown), troca de area recarrega layers e recentra mapa
- COGs organizados em `data/areas/{area_id}/rasters/processed/`
- Vetoriais globais (mining-rights, mining-available) em `data/vectors/`
- Vetoriais por area (geologia, ocorrencias) em `data/areas/{area_id}/vectors/`
- TileService instanciado por area em `main.py` (`tile_services = {area_id: TileService}`)
- `generate` chama `gee_service.set_area()` antes do download para a area correta
- Grid de download GEE ajustado para raio 30km (excedia memoria com grids antigos):
  - S2 RGB 10m: 7x7 grid (49 partes)
  - S2 ratios 20m: 5x5 grid
  - ASTER VNIR 15m: 8x8 grid (Crosta FeOx/Ninomiya Fe2+)
  - ASTER SWIR 30m: 3x3 grid
  - ASTER TIR 90m: 2x2 grid
  - Crosta FeOx PCA scale=60 (30 excedia memoria GEE em areas com muitas cenas)
- **Estado layers por area:**
  - Paiol: 31/35 (faltam em-resist, em-gradient, lineaments, targets)
  - Engegold: 25/35 (faltam 6 ASTER local + em + futuras)
  - Principe: 25/35 (faltam 6 ASTER local + em + futuras)
  - Manduca: 25/35 (faltam 6 ASTER local + em + futuras)
- ASTER local sao duplicatas das GEE — versoes GEE suficientes
- 61 testes passando

### Fases futuras
- **Fase 5:** Modelo de prospectividade (weighted overlay, painel de pesos ajustaveis)
- **Fase 6:** SAR/lineamentos, modelo data-driven (RF/SVM), export de relatorios

## Estrutura do projeto

```
senrem3/
├── backend/
│   ├── main.py              # FastAPI app, monta routers + serve frontend
│   ├── config.py            # Settings + STUDY_AREAS: 3 areas, raio 30km, gee_project
│   ├── api/
│   │   ├── config_routes.py # GET /api/config, GET /api/health
│   │   └── layers.py        # GET /api/areas/{area_id}/layers, POST generate, preload
│   ├── services/
│   │   ├── gee.py           # GEEService: 13 layers GEE (S2+ASTER L1T+GED)
│   │   │                    # PCA via eigen, ratios, download COG com grid paralelo
│   │   │                    # Suporte a service account via GEE_SERVICE_ACCOUNT_KEY
│   │   ├── aster.py         # AsterService: download via CMR API
│   │   ├── processing.py    # ProcessingService: PCA, Crosta, ratios Ninomiya
│   │   ├── tiles.py         # TileService: serve tiles locais via rio-tiler (RGB + singleband)
│   │   ├── pipeline.py      # AsterPipeline: orquestra download->processamento->COG
│   │   ├── cprm.py          # CPRMService: download WFS GeoSGB (geologia, ocorrencias)
│   │   ├── geophysics.py    # GeophysicsProcessor: parser XYZ, interpolacao, FFT derivados
│   │   └── vectors.py       # VectorService: ANM mining rights + CPRM vetoriais
│   └── models/              # (vazio, para Fase 5: prospectivity.py)
├── frontend/
│   ├── index.html           # SPA: header, sidebar, mapa, status bar
│   ├── style.css            # Tema escuro (#1a1a2e, #16213e, #e94560)
│   └── app.js               # MapLibre GL JS, enableLayer/disableLayer, basemaps
├── tests/                   # 61 testes (pytest + FastAPI TestClient)
├── data/                    # areas/{id}/rasters/processed/, vectors/ (gitignored)
├── docs/plans/              # Design + planos de cada fase
├── Dockerfile               # Deploy: python:3.11-slim + libgdal-dev
├── .dockerignore            # Exclui data/, .env, .git/, docs/, tests/
├── railway.json             # Config Railway (Dockerfile, healthcheck, restart)
├── requirements.txt
└── .gitignore               # Exclui data/, .env, .venv/, .DS_Store, *-service-account-key.json
```

## Como rodar

### Local
```bash
source .venv/bin/activate
python -m backend.main          # servidor em http://localhost:8000
python -m pytest tests/ -v      # 61 testes
```

### Deploy (Railway)
```bash
git push                        # deploy automatico via GitHub integration
railway logs                    # ver logs do servidor
railway variables               # ver/editar variaveis de ambiente
```

## Configuracao GEE

- Projeto Google Cloud: `c3po-461514`
- **Local:** `earthengine authenticate` + `earthengine set_project c3po-461514`
- **Servidor:** Service account `senrem3-gee@c3po-461514.iam.gserviceaccount.com`
  - Variavel `GEE_SERVICE_ACCOUNT_KEY` com JSON da chave
  - Roles: `earthengine.admin`, `serviceUsageConsumer`
- Configurado em `backend/config.py` campos `gee_project` e `gee_service_account_key`
- Se `gee_service_account_key` definida → usa service account; senao → credenciais locais

## API Endpoints

| Metodo | Rota | Descricao |
|--------|------|-----------|
| GET | `/api/health` | Health check |
| GET | `/api/config` | Retorna areas de estudo, centro, raio, default_area |
| GET | `/api/areas/{area_id}/layers` | Lista 35 layers `{layers, loading, loaded, total}` |
| POST | `/api/areas/{area_id}/layers/{id}/generate` | Baixa COG GEE/local e retorna tile_url |
| GET | `/api/areas/{area_id}/tiles/{layer_id}/{z}/{x}/{y}.png` | Serve tiles (aceita ?colormap, ?vmin, ?vmax) |
| GET | `/api/areas/{area_id}/tiles/{layer_id}/stats` | Retorna percentis p2/p98 para sliders |
| GET | `/api/areas/{area_id}/vectors/{layer_id}.geojson` | GeoJSON vetorial por area (geologia, ocorrencias) |
| GET | `/api/vectors/{layer_id}.geojson` | GeoJSON vetorial global (mining-rights, mining-available) |

## Convencoes

- Python 3.9.6 local (macOS), Python 3.11 no Docker/Railway
- FastAPI com routers em `backend/api/`, prefixo `/api`
- Frontend vanilla (HTML/CSS/JS), sem framework, MapLibre GL JS v4.7.1 via CDN
- Testes com pytest + FastAPI TestClient
- Tema visual escuro (#1a1a2e, #16213e, #e94560)
- `app.mount("/", StaticFiles(...))` DEVE ser a ultima linha apos todos os `include_router`
- Commits em portugues, formato convencional (feat:, chore:, fix:)
- Tiles GEE servidos localmente via COGs (download via `getDownloadURL`, nao mais `getMapId`)
- Vis params dos ratios DEVEM ser calibrados com percentis reais (p2/p98) via GEE reduceRegion
- Ratios espectrais DEVEM usar estacao seca + mascara NDVI<0.4 para minimizar vegetacao
- Dados pesados (COGs, cenas ASTER) ficam fora do git — .gitignore exclui data/

## Decisoes de design

- **Por que FastAPI + vanilla JS?** Controle total, sem overhead de framework frontend, deploy simples
- **Por que MapLibre GL JS?** Open-source, performatico para tiles raster, suporte a layers
- **Por que GEE → COG local?** GEE computa (median, PCA, ratios), baixa como GeoTIFF, serve via rio-tiler. Permite colormap/min-max para TODAS as layers.
- **Grid paralelo:** S2 mediana 512 imgs excede memoria do `getDownloadURL`. Solucao: dividir em grid (7x7 S2 RGB, 5x5 ratios, 8x8 VNIR, 3x3 SWIR), 4 threads paralelas, mosaic com rasterio
- **Janela ago-out 2017-2024:** Otimizada por analise mensal (set e o mes mais seco, jun atrapalha). 2018 excluido (outlier chuvoso). 512 imagens no composite
- **Mascara NDVI < 0.4:** 62% da area = solo exposto. Analise confirmou que qualityMosaic introduz artefatos (sombras). Mascara urbana desnecessaria (0.11% AOI)
- **Modelo de prospectividade:** Knowledge-driven (fuzzy/weighted overlay) como base, data-driven (RF/SVM) como complemento
- **Pesos do modelo:** Ajustaveis pelo usuario no frontend (sao hipoteses geologicas, nao constantes)
- **Por que Railway?** Suporta Docker com GDAL/rasterio, volume persistente para COGs, deploy automatico via GitHub. Vercel nao suporta backend Python pesado.
- **GEE Service Account:** Permite autenticacao no servidor sem `earthengine authenticate` interativo. Chave JSON na env var.

## Documentacao detalhada

- Design completo: `docs/plans/2026-03-15-senrem3-architecture-design.md`
- Plano Fase 1: `docs/plans/2026-03-15-fase1-base.md`
- Plano Fase 2: `docs/plans/2026-03-15-fase2-gee.md`
- Design Fase 3: `docs/plans/2026-03-15-fase3-aster-design.md`
- Plano Fase 3: `docs/plans/2026-03-15-fase3-implementation.md`
