# Phase 1: Project Foundation & Data Layer

## Goal
Backend and frontend scaffolded, historical data importable, candle data queryable.

## Tasks Breakdown

### 1. Flask Project Structure
- Initialize the Python environment and install Flask, SQLAlchemy, and psycopg2.
- Create the core directories (`backend/app`, `blueprints`, `core`, `models`, `utils`).
- Scaffold blueprints for `data.py`, `strategies.py`, `signals.py`, `backtest.py`, and `settings.py`.
- **Deliverable**: A runnable `run.py` that starts the Flask development server on `localhost:5000`.

### 2. Database Setup (PostgreSQL + TimescaleDB)
- Create a `docker-compose.yml` to run the `timescale/timescaledb:latest-pg15` image.
- Configure `.env` with `DATABASE_URL`.
- Set up SQLAlchemy in `models/db.py`.
- Create the initial migration or table creation script for the `candles` table.
- Attach the TimescaleDB hypertable to the `candles` table partitioned by `open_time`.
- **Deliverable**: A connected database with the `candles` hypertable ready for time-series data.

### 3. Data Integration & Import
- Build Binance REST API integration in `utils/binance.py` to fetch paginated OHLCV data.
- Build a CSV parser in `utils/csv_parser.py` validating the specific Binance export format.
- Create endpoints in `blueprints/data.py` to trigger API fetching and handle CSV file uploads.
- **Deliverable**: Ability to populate the database via REST API calls or CSV uploads.

### 4. Basic React Scaffold
- Scaffold the frontend using Vite with React and TypeScript (`npm create vite@latest frontend -- --template react-ts`).
- Set up React Router with placeholders for `SignalFeed`, `Backtest`, `StrategyIDE`, and `HistoricalData`.
- Build the "Historical Data" page UI to interact with the backend data endpoints (Binance fetch form + CSV upload).
- **Deliverable**: A functional React frontend communicating with the Flask backend.

## Final Deliverable
Historical data can be imported from both Binance API and CSV via the web UI. Data is successfully stored in TimescaleDB and queryable.

## Phase 1 Transition Checklist
- [ ] Flask backend starts without errors
- [ ] TimescaleDB hypertable is successfully created
- [ ] Binance OHLCV data can be fetched and persists in DB
- [ ] CSV upload correctly parses and stores data
- [ ] React frontend starts and successfully connects to backend APIs
