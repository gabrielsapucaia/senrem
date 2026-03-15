# Painel de Propriedades de Layer — Design

**Goal:** Adicionar painel lateral de controle de visualizacao por layer, permitindo ajustar opacidade individual, brilho, contraste, saturacao (todas as layers) e colormap/min-max (layers locais).

**Architecture:** Segundo sidebar acoplado ao primeiro, aparece ao clicar no nome de uma layer ativa. Controles universais via MapLibre raster paint properties (client-side, instantaneo). Controles de colormap/rescale via query params no endpoint de tiles (recarrega tiles).

---

## Layout e UI

### Estrutura

- Novo elemento `#properties-panel` entre `#sidebar` e `#map-container`
- Largura fixa ~240px, `display: none` por default, `display: flex` quando ativo
- Mesma estetica do sidebar (fundo `#16213e`, borda `#0f3460`)
- Header: nome da layer + botao X para fechar
- Conteudo: sliders empilhados verticalmente

### Interacao

- Clicar no nome de uma layer **ativa** → abre o painel (ou troca se ja aberto para outra layer)
- Clicar no nome de uma layer **inativa** → nada (checkbox ativa/desativa)
- Botao X → fecha o painel
- Desativar a layer selecionada → fecha o painel

### Controles universais (todas as layers)

| Controle | Propriedade MapLibre | Range | Default |
|----------|---------------------|-------|---------|
| Opacidade | `raster-opacity` | 0-100% | 70% |
| Brilho min | `raster-brightness-min` | 0-1 | 0 |
| Brilho max | `raster-brightness-max` | 0-1 | 1 |
| Contraste | `raster-contrast` | -1 a +1 | 0 |
| Saturacao | `raster-saturation` | -1 a +1 | 0 |

### Controles extras (layers locais, source=local)

| Controle | Mecanismo | Valores |
|----------|-----------|---------|
| Colormap | Query param na tile URL | viridis, magma, plasma, inferno, turbo, cividis, greys |
| Min/Max | Query param na tile URL | Sliders com range dinamico, default p2/p98 |

Mudar colormap ou min/max reconstroi a tile URL → MapLibre refaz fetch.

---

## Backend

### Endpoint de tiles modificado

```
GET /api/tiles/{layer_id}/{z}/{x}/{y}.png?colormap=magma&vmin=-0.5&vmax=2.1
```

- `colormap` — string, default "viridis"
- `vmin`, `vmax` — floats opcionais, default p2/p98 do COG

### Novo endpoint de stats

```
GET /api/tiles/{layer_id}/stats → { "p2": -0.31, "p98": 1.87 }
```

Retorna percentis para popular sliders min/max com range e defaults corretos.

### Data flow

1. Usuario ativa layer → tiles carregam normalmente
2. Usuario clica no nome → painel abre, frontend busca `/stats` se layer local
3. Usuario ajusta colormap ou min/max → frontend reconstroi tile URL com query params → `map.getSource().setTiles([newUrl])`
4. Usuario ajusta brilho/contraste/saturacao → `map.setPaintProperty()` direto (instantaneo)

### Layers GEE

Sem mudanca no backend. Brilho/contraste/saturacao sao 100% client-side. Colormap/min/max nao se aplicam.

---

## Testes

- Endpoint de tiles com query params (colormap, vmin, vmax)
- Endpoint `/api/tiles/{layer_id}/stats`
- Layer nao registrada → 404

## Arquivos modificados

| Arquivo | Mudanca |
|---------|---------|
| `backend/main.py` | Query params no endpoint de tiles + novo endpoint `/stats` |
| `frontend/index.html` | Novo `#properties-panel` |
| `frontend/style.css` | Estilos do painel |
| `frontend/app.js` | Logica painel, sliders, rebuild tile URL |
