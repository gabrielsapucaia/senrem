# Adicionar Nova Area de Estudo ao SENREM3

Recebe: nome, latitude, longitude, raio (km)
Argumentos: $ARGUMENTS (formato: "nome lat lon raio_km" ex: "monte-do-carmo -10.76 -48.11 30")

## Pipeline

### 1. Validar e parsear argumentos
Extrair nome, lat, lon, raio_km de $ARGUMENTS. Se faltarem, perguntar ao usuario.

### 2. Adicionar area em config.py
Editar `backend/config.py` STUDY_AREAS — adicionar nova entrada com center_lat, center_lon, radius_km.

### 3. Criar diretorios
```
data/areas/{nome}/rasters/processed/
data/areas/{nome}/vectors/
```

### 4. Gerar COGs GEE (ATENCAO AOS LIMITES DE MEMORIA)

**CRITICO: Serializar downloads — NUNCA rodar 2 areas em paralelo no GEE.**

Chamar `POST /api/areas/{nome}/layers/{layer_id}/generate` para cada layer GEE, na ordem abaixo (mais leves primeiro):

| Ordem | Layer | Scale | Grid | Partes | Tempo estimado |
|-------|-------|-------|------|--------|----------------|
| 1 | dem | 30m | 1x1 | 1 | ~10s |
| 2 | carbonate | 90m | 2x2 | 4 | ~30s |
| 3 | silica | 90m | 2x2 | 4 | ~30s |
| 4 | gee-pca-tir | 90m | 2x2 | 4 | ~1min |
| 5 | gee-crosta-oh | 30m | 3x3 | 9 | ~2min |
| 6 | gee-ninomiya-aloh | 30m | 3x3 | 9 | ~2min |
| 7 | gee-ninomiya-mgoh | 30m | 3x3 | 9 | ~2min |
| 8 | iron-oxide | 20m | 5x5 | 25 | ~3min |
| 9 | clay | 20m | 5x5 | 25 | ~3min |
| 10 | gee-ninomiya-ferrous | 15m | 8x8 | 64 | ~5min |
| 11 | gee-crosta-feox | 15m | 8x8 | 64 | ~5min |
| 12 | rgb-false | 10m | 7x7 | 49 | ~8min |
| 13 | rgb-true | 10m | 7x7 | 49 | ~8min |

**Se "User memory limit exceeded":**
1. Esperar 5 minutos (quota GEE reseta)
2. Verificar que NENHUM outro download GEE esta rodando
3. Re-tentar a layer que falhou
4. Se Crosta FeOx falhar repetidamente: a PCA ja usa scale=60 (nao 30) — se ainda falhar, tentar scale=90

**Layers ASTER local (crosta-feox, crosta-oh, ninomiya-*, pca-tir) sao DUPLICATAS das GEE. NAO gerar — requerem download de ~4GB de cenas NASA por area.**

### 5. Gerar COGs geofisica
A aerogeofisica (Projeto 1073 Tocantins) cobre toda a regiao. Verificar se o bbox da nova area intersecta os dados:
- Dados cobrem aproximadamente lon [-50, -46], lat [-14, -10]
- Se cobrir, processar via `GeophysicsProcessor` com output_dir por area

### 6. Baixar vetoriais WFS
Os vetoriais sao baixados on-demand pelo servidor (geologia, ocorrencias). Basta acessar:
```
GET /api/areas/{nome}/vectors/geology-litho.geojson
GET /api/areas/{nome}/vectors/geology-age.geojson
GET /api/areas/{nome}/vectors/mineral-occurrences.geojson
```
Se o WFS GeoSGB estiver fora, os GeoJSONs nao serao gerados.

### 7. Upload para HF Space
O HF Space (`gabrielsapucaia02-senrem.hf.space`) tem endpoint de upload ativo:
```bash
# COGs
curl -X POST "https://gabrielsapucaia02-senrem.hf.space/api/areas/{nome}/upload/{layer_id}" -F "file=@path.tif"

# Vetoriais por area
curl -X POST "https://gabrielsapucaia02-senrem.hf.space/api/areas/{nome}/vectors/{layer_id}/upload" -H "Content-Type: application/json" --data-binary "@path.geojson"
```
**Enviar um por um, menor para maior.** HF Space tem 2GB RAM — aguenta uploads individuais.

Se o endpoint de upload nao existir (foi removido):
1. Adicionar endpoints temporarios em main.py (ver git log para template)
2. Push para HF via `huggingface_hub.upload_folder`
3. Fazer uploads
4. Remover endpoints e push novamente

### 8. Atualizar documentacao
- `CLAUDE.md`: adicionar area na lista, atualizar contagem de layers
- `MEMORY.md`: atualizar status de implementacao e HF Space

### 9. Verificar
```bash
# Local
curl -s http://localhost:8000/api/areas/{nome}/layers | python3 -c "import sys,json; d=json.load(sys.stdin); avail=[l for l in d['layers'] if l['available']]; print(f'{len(avail)}/{len(d[\"layers\"])} disponíveis')"

# HF Space
curl -s https://gabrielsapucaia02-senrem.hf.space/api/areas/{nome}/layers | python3 -c "import sys,json; d=json.load(sys.stdin); avail=[l for l in d['layers'] if l['available']]; print(f'{len(avail)}/{len(d[\"layers\"])} disponíveis')"
```

### 10. Commitar
```
git add backend/config.py CLAUDE.md
git commit -m "feat: adicionar area de estudo {nome}"
git push origin main
```
