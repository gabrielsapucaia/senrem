# Fase 3 — ASTER Local + Processamento Avancado

## Objetivo

Download de dados ASTER L2, processamento local com Metodo Crosta (PCA dirigida), ratios Ninomiya e PCA exploratoria para mapeamento de alteracao hidrotermal na area de estudo (25km, Natividade/Almas Greenstone Belt).

## Arquitetura

### Novos arquivos

```
backend/services/
├── aster.py          # Download ASTER L2 via AppEEARS API (NASA)
├── processing.py     # PCA, Crosta, ratios Ninomiya -> COGs
└── tiles.py          # Serve tiles dos COGs via rio-tiler

data/rasters/
├── aster/raw/        # Cenas brutas baixadas
├── aster/composite/  # Medianas por banda (COG)
└── processed/        # Resultados PCA/Crosta/ratios (COG)
```

### Fluxo de dados

```
POST /api/layers/{id}/generate
  -> layers.py detecta source="local"
  -> AsterService: verifica cache, se nao tem -> AppEEARS download
  -> ProcessingService: composite mediana -> PCA/Crosta/ratios -> COG
  -> TileService: rio-tiler serve tiles do COG
  -> Retorna tile_url = /api/tiles/{layer_id}/{z}/{x}/{y}.png
```

Frontend nao muda — mesmo checkbox -> gerar -> tiles no mapa.

## Download ASTER via AppEEARS

### API AppEEARS (NASA Earthdata)

1. Autenticacao: `POST /login` com credenciais NASA Earthdata
2. Submeter task: `POST /task` com poligono AOI + produtos + periodo
3. Polling: `GET /task/{id}` ate status=done
4. Download: `GET /bundle/{id}/{file}`

### Produtos

| Produto | Conteudo | Periodo | Uso |
|---------|----------|---------|-----|
| AST_07XT | Reflectancia VNIR+SWIR (B1-B9) corrigida atmosfericamente | 2000-2008 | Crosta, Ninomiya |
| AST_08 | Emissividade TIR (B10-B14) | 2000-2024 | PCA TIR |

**IMPORTANTE:** Detector SWIR do ASTER falhou em abril de 2008. Bandas B4-B9 so existem de 2000 a 2008.

### Composicao

Mediana por banda de todas as cenas disponiveis (filtradas por nuvens), maximizando cobertura de solo exposto. Mesmo principio do Sentinel-2 mas com mais anos de historico.

### Configuracao

```python
# config.py
earthdata_username: str = ""
earthdata_password: str = ""
```

Requer conta gratuita em https://urs.earthdata.nasa.gov/

## Processamento

### Metodo Crosta (PCA Dirigida)

**Crosta FeOx (VNIR):**
1. Stack B1, B2, B3
2. PCA -> 3 componentes
3. Selecionar CP com maior peso em B3 (absorcao Fe3+ ~0.87um) e sinal oposto em B1
4. Inverter se loading negativo (valores altos = mais FeOx)

**Crosta OH/Sericita (SWIR):**
1. Stack B4, B5, B6, B7
2. PCA -> 4 componentes
3. Selecionar CP com maior peso em B6 (absorcao AlOH ~2.2um) e sinal oposto em B5/B7
4. Inverter se necessario

### Ratios Ninomiya

- **AlOH index:** B7 / (B6 * B8) — argilas com absorcao AlOH
- **MgOH index:** B7 / (B6 + B9) — clorita, talco, serpentina
- **Ferrous Fe:** B5 / B4 — Fe2+ (magnetita, clorita)

### PCA Exploratoria TIR

1. Stack B10-B14 (emissividade termica)
2. PCA -> 5 componentes
3. Servir CP2 e CP3 como layers (CP1 = albedo, CP2-3 = variacao composicional)
4. Anomalias de silicificacao tipicamente na CP2 ou CP3

### Implementacao (processing.py)

```python
class ProcessingService:
    def build_composite(self, scene_paths, bands) -> np.ndarray
    def crosta_feox(self, composite) -> str  # path do COG
    def crosta_oh(self, composite) -> str
    def ninomiya_aloh(self, composite) -> str
    def ninomiya_mgoh(self, composite) -> str
    def ninomiya_ferrous(self, composite) -> str
    def pca_tir(self, composite) -> list[str]  # CP1, CP2, CP3
```

Usa numpy/sklearn.decomposition.PCA para PCA, rasterio para I/O de COGs.

## Tiles Locais (rio-tiler)

### Endpoint

```
GET /api/tiles/{layer_id}/{z}/{x}/{y}.png
```

- rio-tiler le o COG e retorna tile em web mercator
- Vis params (min, max, colormap) configurados por layer
- tile_url retornado pelo POST /generate aponta para este endpoint

### Novas layers

| Layer ID | Nome | Metodo | Bandas ASTER | Periodo |
|----------|------|--------|-------------|---------|
| crosta-feox | Crosta FeOx | PCA dirigida VNIR | B1,B2,B3 | 2000-2008 |
| crosta-oh | Crosta OH/Sericita | PCA dirigida SWIR | B4,B5,B6,B7 | 2000-2008 |
| ninomiya-aloh | Ninomiya AlOH | Ratio | B6,B7,B8 | 2000-2008 |
| ninomiya-mgoh | Ninomiya MgOH | Ratio | B6,B7,B9 | 2000-2008 |
| ninomiya-ferrous | Ninomiya Fe2+ | Ratio | B4,B5 | 2000-2008 |
| pca-tir | PCA TIR | PCA exploratoria | B10-B14 | 2000-2024 |

Todas com source="local" no layers.py. can_generate=True se credenciais Earthdata configuradas.

## Dependencias novas

```
rio-tiler        # serve tiles de COGs
```

rasterio, numpy e scikit-learn ja estao no requirements.txt.

## Decisoes

- **AppEEARS vs EarthExplorer:** AppEEARS permite recortar por AOI (menos dados para baixar)
- **ASTER L2 vs L1T:** L2 (AST_07XT) ja tem correcao atmosferica, essencial para PCA confiavel
- **Mediana vs best-pixel:** Mediana e mais robusta a outliers (ruido, sombras)
- **rio-tiler vs tiles estaticos:** rio-tiler serve dinamicamente, sem pre-renderizar
- **qualityMosaic rejeitado:** Testado para S2, introduz artefatos de sombra nos ratios
- **Mascara urbana desnecessaria:** Area urbana = 0.11% da AOI (2.14 km2)
- **Frontend sem mudancas:** Mesma UX de checkbox -> gerar -> visualizar
