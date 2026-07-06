# Trading Lab

Plataforma web local para investigar estrategias de trading en US stocks/ETFs con candles, noticias, sentimiento y backtesting en Python.

## Stack

- Backend: FastAPI, DuckDB, pandas/numpy, proveedores Alpaca/RSS.
- Frontend: React, TypeScript, Vite, Lightweight Charts, Monaco Editor.
- IA local: FinBERT opcional con `pip install -e ".[ai]"`; Ollama opcional para resumen de noticias.
- Backtesting: motor local long-only por señales `entries/exits`, con subprocess y timeout.

## Setup

```bash
cp .env.example .env
conda env create -f environment.yml
conda activate trading-lab
npm install
```

Para FinBERT local:

```bash
conda activate trading-lab
pip install -e ".[ai]"
```

Para Ollama:

```bash
ollama pull gpt-oss:20b
```

## Ejecutar

Recomendado:

```bash
./scripts/start_services.sh
```

Abre `http://127.0.0.1:5173`.

Para detener backend y frontend:

```bash
./scripts/stop_services.sh
```

Los scripts usan por defecto `CONDA_ENV=trading-lab`, backend en `8001` y frontend en `5173`.
Puedes cambiarlo asi:

```bash
BACKEND_PORT=8002 FRONTEND_PORT=5174 ./scripts/start_services.sh
```

Manual, terminal 1:

```bash
conda activate trading-lab
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8001
```

Terminal 2:

```bash
conda activate trading-lab
VITE_API_URL=http://127.0.0.1:8001 VITE_WS_URL=ws://127.0.0.1:8001 npm run dev -- --host 127.0.0.1 --port 5173
```

Si el backend corre en otro puerto:

```bash
VITE_API_URL=http://127.0.0.1:8001 VITE_WS_URL=ws://127.0.0.1:8001 npm run dev
```

La app usa solo datos de Alpaca. Sin `ALPACA_API_KEY` y `ALPACA_SECRET_KEY`, los endpoints de mercado/noticias no generan datos ficticios.

## Contrato De Estrategias

El editor espera una funcion `run(ctx)`:

```python
def run(ctx):
    candles = ctx.candles
    close = candles["close"]
    fast = close.rolling(10).mean()
    slow = close.rolling(25).mean()

    entries = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    exits = (fast < slow) & (fast.shift(1) >= slow.shift(1))

    return {"entries": entries, "exits": exits, "markers": []}
```

`ctx.candles` es un DataFrame con `timestamp`, `open`, `high`, `low`, `close`, `volume`; `ctx.news` es una lista de noticias; `ctx.sentiment` es un DataFrame con scores por articulo.

## Pruebas

```bash
conda activate trading-lab
pytest
npm test
npm run build
```

Para actualizar el entorno despues de cambios en `environment.yml`:

```bash
conda env update -f environment.yml --prune
```
