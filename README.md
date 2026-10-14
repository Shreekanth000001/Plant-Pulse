# PlantPulse

> **TODO (you write this):** One sentence saying what PlantPulse is, then two sentences on *why you built it*
> (what skills it demonstrates, why the devices are simulated). Plain words, no umbrella terms like "backend".

PlantPulse is a telemetry platform for a simulated industrial plant. I built it to gain hands-on experience with MQTT, FastAPI, SQLite, WebSockets, Next.js, pytest, and GitHub Actions. A Python simulator publishes machine data over MQTT, and a FastAPI service stores it and serves it to a Next.js dashboard. It models an 8040 membrane plant with four stages: housing, casting, assembly, and quality control (QC). The devices are simulated because I don’t have access to real industrial equipment.

> **TODO:** Add a screenshot of the dashboard's Overview page here (`docs/overview.png`, then `![Overview](docs/overview.png)`).

## What it does

A simulated membrane-manufacturing plant with four stages and 11 machines. Each machine publishes telemetry over
MQTT. A FastAPI service stores everything in SQLite, pushes live updates over a WebSocket, and answers historical
queries over REST. A Next.js dashboard shows live machine status, the full journey of any individual unit, and
defect-rate analytics.

| Stage | Machines | What it does |
|---|---|---|
| Housing | 4 | Creates new units (unlimited raw material) |
| Membrane Casting | 3 | Takes units from a queue |
| Assembly | 3 | Takes units from a queue |
| QC | 1 | Tests each unit and records pass or fail |

## Architecture

```mermaid
flowchart LR
    SIM["Simulator<br/>line, units, defect model"] -->|publishes JSON| MQTT["MQTT broker<br/>Mosquitto"]
    MQTT -->|subscribes to factory/#| API["FastAPI service"]
    API -->|writes| DB[("SQLite")]
    API -->|REST queries| UI["Next.js dashboard"]
    API -->|WebSocket /ws/telemetry| UI
```

### How the simulation works

- Every machine cycles through phases. It can only leave `IDLE` if it has a unit to work on: Housing creates a new
  unit, and the other stages take one from the queue in front of them. An idle machine with no input is *starved*.
- While running, a machine's vibration drifts upward. Above a threshold it faults.
- When a machine finishes a unit it records an **anomaly score**: how far its readings were from their setpoints, in
  standard deviations, summed across its readings. The score is stored in the unit's history.
- Each unit carries that history through the line. When QC tests it, the defect probability is:
  `base rate (4%) + shift-change bias (+4% at hours 6, 14, 22) + weather bias (placeholder, currently 0) + telemetry bias (sum of the unit's anomaly scores x 0.015)`,
  capped at 95%. A failed unit is attributed to the stage with the worst anomaly score. See `defect_model.py`.

### MQTT topics

| Topic | Published when |
|---|---|
| `factory/{stage}/{machine_id}/telemetry` | every machine, every 2-second tick |
| `factory/{stage}/{machine_id}/stage_event` | a machine finishes a unit's stage (not QC) |
| `factory/qc/{machine_id}/result` | QC finishes testing a unit |
| `factory/queue_depths` | every tick: units waiting in front of each stage |

### REST and WebSocket API

| Endpoint | Returns |
|---|---|
| `GET /health` | service status |
| `GET /api/machines/latest` | most recent reading per machine |
| `GET /api/queue-depths` | units waiting in front of each stage |
| `GET /api/units?limit=20` | most recently created units |
| `GET /api/units/{unit_id}` | a unit's full stage history and QC verdict |
| `GET /api/stats/defect-rate-by-hour` | defect rate grouped by hour of day |
| `GET /api/stats/defect-rate-by-stage` | failures grouped by attributed stage |
| `WS /ws/telemetry` | every MQTT message, wrapped as `{"topic": ..., "payload": ...}` |

## Running it locally

Prerequisites: Python 3.12, Node 20+ (CI uses Node 22), and a Mosquitto broker on `localhost:1883`.

```bash
# 1. Broker (Ubuntu / Debian; other systems differ)
sudo apt install mosquitto mosquitto-clients

# 2. Python environment
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. API service (creates factory.db on first start)
uvicorn main:app --port 8000

# 4. Simulator, in a second terminal (venv active)
python mqtt_publisher.py

# 5. Dashboard, in a third terminal
cd frontend
npm install
# create frontend/.env.local containing:
#   NEXT_PUBLIC_API_URL=http://localhost:8000
#   NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/telemetry
npm run dev                       # http://localhost:3000
```

The first unit needs a few minutes to travel through all four stages, so the QC results and the defect-rate charts
start empty.

| Environment variable | Default | Used by |
|---|---|---|
| `MQTT_HOST` | `localhost` | API service, simulator |
| `MQTT_PORT` | `1883` | API service, simulator |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | API service |

## Project layout

| Path | Purpose |
|---|---|
| `config.py` | facility description: stages, machines, setpoints, cycle times |
| `units.py` | `Unit`: one product, with its journey history |
| `simulator.py` | `MachineSim`, `QCStation`, and `Line`, which wires the queues together |
| `defect_model.py` | QC defect probability |
| `mqtt_publisher.py` | runs the line and publishes every reading |
| `database.py`, `main.py` | SQLAlchemy models; FastAPI service (ingestion, WebSocket, REST) |
| `tests/` | pytest suite |
| `frontend/` | Next.js dashboard |
| `.github/workflows/ci.yml` | CI |

## Design decisions

> **TODO (you write this section, at least four decisions).** For each one use this shape:

1.To limit the sub facilities to 4 so it does has enough complexity and yet not overwhelm with data
2.Use MQTT for publishing and listening so many clients can access the data at the same time.
3.Choose a modern UI/UX design appropriate for engineers
4.


> **Problem** (what needed solving) / **Choice** (what you did) / **Alternative I rejected, and why** / **Tradeoff** (what it costs).
> Candidates: MQTT instead of HTTP polling; queues between stages; units that carry their own history;
> SQLite instead of Postgres; keeping aggregation in the API instead of the dashboard.

## Testing and CI

```bash
pip install pytest
pytest
```

- `tests/test_defect_model.py` covers the probability cap, the shift-change bias, and the anomaly bias.
- `tests/test_simulator.py` checks that each machine's average cycle time matches its configured value within a
  documented tolerance.

On every pull request, CI runs the following. `main` is protected, so both jobs must pass before a merge.

- **Backend:** `ruff`, an import smoke test of every module from a clean checkout, and `pytest`.
- **Frontend:** `npm run lint` and `npm run build`.

## Known limitations

This is a learning and portfolio project, not production software. The data is simulated, and I know about these
problems:

- **A faulted machine never recovers**, and the unit it was working on is stranded: never moved on, never marked scrapped.
- **No backpressure.** Housing is faster than Casting and has unlimited raw material, so queues in front of the slower stages grow without a limit.
- **Simulated cycle times run 5-11% above their configured values.** The simulation advances in 2-second ticks and every phase rounds up to the next tick. The cycle-time test tolerance documents this overhead.
- **The defect patterns exist by construction.** The probability is a formula I wrote, so the analytics "discover" effects I built in. The defect-type attribution is a heuristic (the stage with the worst anomaly score), not a causal claim. The per-machine good and reject counters come from a simple placeholder check and are not the QC verdict.
- **Weather is a placeholder constant** (0). The planned live data source is not built.
- **Clocks.** Stage timestamps use the real wall clock, and QC reads the local hour, so QC results depend on when the simulator runs. The backend also stamps rows with their arrival time, so historical data cannot be backfilled through MQTT.
- **Operational gaps:** no authentication on the API or WebSocket, the MQTT broker allows anonymous connections, and SQLite is a single-file database.
- **Dashboard queue indicators** are estimated from stage events. (Remove this line once `refactor/use-real-queue-depths` is merged.)

## Planned

Bounded queues with backpressure, fault repair, live weather data, an OEE (overall equipment effectiveness) view, and a Docker Compose deployment.