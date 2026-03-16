# Fase 4: Dados CPRM/SGB — Design

## Objetivo

Integrar dados geológicos, ocorrências minerais e aerogeofísica ao dashboard SENREM3 para fornecer contexto geológico e geofísico à exploração aurífera no Greenstone Belt Natividade/Almas.

## Dados disponíveis

### WFS GeoSGB (https://geoservicos.sgb.gov.br/geoserver/wfs)
- `geosgb:litoestratigrafia_estados` — 116 polígonos na área (escala 1:500k)
  - Campos: sigla, litotipos, nome, idade_max/min, era_max, ambiente_tectonico, legenda
- `geosgb:ocorrencias_recursos_minerais` — 8 pontos na área (3 de ouro)
  - Campos: substancias, status_economico, importancia, toponimia, lat/lon

### Aerogeofísica (Projeto 1073 Tocantins — local)
- XYZ brutos em `data/aerogeofisica/1073_tocantins/1073-XYZ.zip` (1.4GB comprimido, 6.8GB descomprimido)
- Magnético: `1073_MAGLINE_SA1.XYZ` / `1073_MAGLINE_SA2.XYZ` — colunas X, Y (UTM), MAGCOR, MAGNIV, RESIDUO
- Gamma: `1073_GAMALINE.XYZ` — colunas X, Y, KPERC, eU, eTH, CTCOR, razões, LONGITUDE, LATITUDE
- Espaçamento de linhas: ~500m N-S
- CRS: UTM (provavelmente zona 23S, EPSG:31983)

## Arquitetura

Três pipelines:

1. **Vetoriais (geologia + ocorrências)** — download WFS → GeoJSON local → MapLibre geojson source
2. **Aerogeofísica raster** — recorte XYZ bbox → interpolação minimum curvature 125m → COGs → rio-tiler
3. **Derivados magnéticos** — FFT do grid magnético → 1DV e ASA → COGs

## Layers novas (10 total)

| ID | Nome | Tipo | Grupo | Fonte |
|----|------|------|-------|-------|
| `geology-litho` | Geologia (Litologia) | vetor fill | CPRM | WFS |
| `geology-age` | Geologia (Idade) | vetor fill | CPRM | WFS |
| `mineral-occurrences` | Ocorrências Minerais | vetor circle | CPRM | WFS |
| `mag-anomaly` | Campo Magnético Anômalo | raster | Geofísica | XYZ 1073 |
| `mag-1dv` | 1a Derivada Vertical | raster | Geofísica | derivado mag |
| `mag-asa` | Sinal Analítico | raster | Geofísica | derivado mag |
| `gamma-k` | Potássio (K%) | raster | Geofísica | XYZ 1073 |
| `gamma-th` | Tório (eTh) | raster | Geofísica | XYZ 1073 |
| `gamma-thk` | Razão Th/K | raster | Geofísica | XYZ 1073 |
| `gamma-ternary` | Ternário K-Th-U | raster RGB | Geofísica | XYZ 1073 |

## Processamento geofísico

### Recorte XYZ
- Extrair ZIP, ler XYZ (skip headers, parse colunas)
- Filtrar pontos dentro do bbox da área de estudo (-47.38, -11.93, -46.93, -11.47)
- Gamma XYZ já tem LONGITUDE/LATITUDE; magnético tem UTM (reprojetar)

### Interpolação
- Método: minimum curvature via `scipy.interpolate.griddata(method='cubic')`
- Resolução: ~125m (metade do espaçamento de linhas)
- Grid regular em EPSG:4326

### Derivados magnéticos (FFT)
- 1a Derivada Vertical: multiplicar espectro por |k| (número de onda)
- Amplitude do Sinal Analítico: sqrt(dx² + dy² + dz²) onde dx, dy = derivadas horizontais via FFT

### Ternário K-Th-U
- Normalizar cada canal (K, Th, U) para 0-255 via percentis p2/p98
- Combinar em RGB: R=K, G=Th, B=U
- Salvar como COG 3 bandas

### Output
- COGs em `data/rasters/processed/` (mesma pasta das layers existentes)
- GeoJSONs em `data/vectors/`

## Vetoriais (geologia + ocorrências)

### Download WFS
- Request com bbox da área de estudo, outputFormat=application/json
- Cache local como GeoJSON em `data/vectors/`
- Re-download via botão ou endpoint POST

### Renderização frontend
- **Geologia litologia:** polígonos fill semi-transparentes, cor por sigla, borda fina
- **Geologia idade:** polígonos fill, cor por era (Paleoproterozóico=verde, Neoproterozóico=azul, etc.)
- **Ocorrências:** círculos, ouro=amarelo, outros=cinza, popup com detalhes ao clicar

### Servindo ao frontend
- Endpoint GET `/api/vectors/{layer_id}` retorna GeoJSON
- Frontend adiciona como MapLibre `geojson` source + `fill`/`line`/`circle` layers

## Endpoints novos

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/vectors/{layer_id}` | Retorna GeoJSON de layer vetorial |
| POST | `/api/vectors/refresh` | Re-baixa dados WFS do GeoSGB |

## Tratamento de erros

- WFS offline: usa cache GeoJSON local se disponível
- XYZ não extraído: erro claro pedindo para rodar pipeline
- Dados fora da área: retorna vazio

## Arquivos novos

```
backend/services/
  cprm.py          # Download WFS, cache GeoJSON
  geophysics.py    # Recorte XYZ, interpolação, derivados FFT, COGs

data/vectors/
  geology-litho.geojson
  geology-age.geojson
  mineral-occurrences.geojson

data/rasters/processed/
  mag-anomaly.tif
  mag-1dv.tif
  mag-asa.tif
  gamma-k.tif
  gamma-th.tif
  gamma-thk.tif
  gamma-ternary.tif
```
