# Phase 1: Project Foundation & Data Layer

## Goal
Backend and frontend scaffolded, historical data importable, candle data queryable.

## Detailed Implementation Notes (Executed)

### 1. Infrastructure & Environment Setup
- **Docker Setup**: `docker-compose.yml` runs the `timescale/timescaledb:latest-pg15` on port `5432`.
- **Environment Configurations**: `backend/.env` configured tightly to abstract the PostgreSQL URLs, FLASK execution pointers (`run.py`), and standard modes.

### 2. Backend Scaffold & ORM Layer
- **Conda Environment**: Environment managed via `environment.yml` configuring `python=3.10` and dependencies such as `flask`, `sqlalchemy`, `pandas`, `requests` for robust package management.
- **ORM Configuration (`app/models/db.py`)**:
  - Initialized `SQLAlchemy()`.
  - `Candle` model implemented utilizing a composite primary key structure spanning `(symbol, timeframe, open_time)` to satisfy Timescale constraints robustly.
- **TimescaleDB Initialization**:
  - Handled via `app/__init__.py` using raw SQL `create_hypertable` post `create_all()`. Graceful error capture if already initialized.

### 3. Data Ingestion Utilities
- **Binance Client (`app/utils/binance.py`)**:
  - Implements `fetch_klines()` directly linking with Binance REST API `https://api.binance.com/api/v3/klines`.
  - Built-in pagination bypasses Binance’s 1000-candle hard-limit over broad timeframe queries seamlessly.
- **CSV Parser (`app/utils/csv_parser.py`)**:
  - Leverages pandas DataFrame indexing to validate and parse Binance's native CSV export syntax seamlessly resolving both millisecond and string timestamps dynamically.

### 4. Routing & API Endpoints (`app/blueprints/data.py`)
- `POST /import/binance`: Consumes custom payload. Paginates API and runs an overriding upsert via `on_conflict_do_update` using PostgreSQL dialects to handle duplicate overlap reliably.
- `POST /import/csv`: Safely parses multipart file streams mapping via identical upscale conflict resolution.
- `GET /datasets`: Groups SQL aggregates `MIN(open_time)`, `MAX(open_time)` dynamically calculating actual database-scale holdings without expensive scans.

### 5. Frontend React Scaffold
- **Initialization**: Deployed an optimized Vite + React-TS instance utilizing the `axios`, `react-router-dom`, `lucide-react`, and standard Tailwind CSS tools.
- **Historical Data Interface**:
  - Built split-pane tab functionality managing `Binance Fetch` UI side-by-side with dynamic visual `CSV Uploads`.
  - Global `DatasetTable.tsx` handles asynchronous dataset pinging parsing formatting natively with `date-fns`.

## Phase 1 Transition Checklist
- [x] Flask backend structural integration complete
- [x] TimescaleDB dockerization & instantiation tested
- [x] Binance OHLCV active data streams integrated and tested
- [x] CSV localized logic mapped natively
- [x] React frontend successfully communicates across API endpoints visually cleanly
