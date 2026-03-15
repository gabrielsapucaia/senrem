# SENREM3 — Sensoriamento Remoto para Mineracao

## O que e este projeto

Sistema de sensoriamento remoto voltado a exploracao de ouro em Greenstone Belts.
FastAPI backend + frontend MapLibre GL JS para visualizacao interativa de dados geoespaciais.

**Area de estudo:** Raio de 25km em torno de -11.699153, -47.155531 (Greenstone Belt Natividade/Almas, Tocantins, Brasil).

**Objetivo final:** Dashboard web com layers de sensoriamento remoto (espectral, terreno, geofisica) e modelo de prospectividade mineral (knowledge-driven + data-driven) para rankeamento de alvos de ouro.

## Status atual

### Fase 1 — Base (CONCLUIDA)
- FastAPI servindo API + frontend estatico
- MapLibre GL JS com mapa interativo, area de estudo (circulo 25km), basemaps
- Endpoints: `/api/config`, `/api/layers`, `/api/health`
- 4 testes automatizados passando
- Painel lateral com 12 layers (desabilitadas, prontas para integracao)

### Proxima: Fase 2 — Google Earth Engine
- Integrar earthengine-api para gerar layers: composicoes RGB, band ratios, DEM
- Servir tiles raster no mapa
- Habilitar toggle de layers no frontend

### Fases futuras
- **Fase 3:** Download ASTER, metodo Crosta, PCA (alteracao hidrotermal)
- **Fase 4:** Dados CPRM (geologia, ocorrencias, geofisica)
- **Fase 5:** Modelo de prospectividade (weighted overlay, painel de pesos)
- **Fase 6:** SAR/lineamentos, modelo data-driven, export de relatorios

## Estrutura do projeto

```
senrem3/
├── backend/
│   ├── main.py              # FastAPI app, monta routers + serve frontend
│   ├── config.py            # Settings (pydantic-settings): coordenadas, raio, etc.
│   ├── api/
│   │   ├── config_routes.py # GET /api/config, GET /api/health
│   │   └── layers.py        # GET /api/layers (lista 12 layers)
│   ├── services/            # (vazio, para Fase 2+: gee.py, download.py, cprm.py, processing.py)
│   └── models/              # (vazio, para Fase 5: prospectivity.py)
├── frontend/
│   ├── index.html           # SPA: header, sidebar, mapa, status bar
│   ├── style.css            # Tema escuro, layout flexbox
│   └── app.js               # MapLibre GL JS, basemaps, layers, area de estudo
├── tests/
│   ├── test_config.py       # Testa /api/config e /api/health
│   └── test_layers.py       # Testa /api/layers
├── data/
│   ├── rasters/             # Cache de imagens processadas (gitignored)
│   ├── vectors/             # Shapefiles, GeoJSON (gitignored)
│   └── tiles/               # Tiles raster (gitignored)
├── docs/plans/
│   ├── 2026-03-15-senrem3-architecture-design.md  # Design completo do sistema
│   └── 2026-03-15-fase1-base.md                   # Plano de implementacao da Fase 1
├── requirements.txt
└── .gitignore
```

## Como rodar

```bash
source .venv/bin/activate
python -m backend.main          # servidor em http://localhost:8000
python -m pytest tests/ -v      # testes
```

## Convencoes

- Python 3.9.6 (versao do sistema no macOS)
- FastAPI com routers em `backend/api/`, prefixo `/api`
- Frontend vanilla (HTML/CSS/JS), sem framework, MapLibre GL JS via CDN
- Testes com pytest + FastAPI TestClient
- Tema visual escuro (#1a1a2e, #16213e, #e94560)
- `app.mount("/", StaticFiles(...))` DEVE ser a ultima linha apos todos os `include_router`
- Commits em portugues, formato convencional (feat:, chore:, fix:)

## Decisoes de design

- **Por que FastAPI + vanilla JS?** Controle total, sem overhead de framework frontend, deploy simples
- **Por que MapLibre GL JS?** Open-source, performatico para tiles raster, suporte a layers
- **Por que GEE + download local?** GEE para exploracao rapida, download para analises detalhadas (ASTER/Crosta)
- **Modelo de prospectividade:** Knowledge-driven (fuzzy/weighted overlay) como base, data-driven (RF/SVM) como complemento
- **Pesos do modelo:** Ajustaveis pelo usuario no frontend (sao hipoteses geologicas, nao constantes)

## Documentacao detalhada

- Design completo: `docs/plans/2026-03-15-senrem3-architecture-design.md`
- Plano Fase 1: `docs/plans/2026-03-15-fase1-base.md`
