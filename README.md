# PlantPulse

<!-- ===================================================================== -->
<!-- INTRO BLOCK (User to write)                                           -->
<!-- Write your one-sentence project definition and 2-sentence rationale   -->
<!-- here. Plain words, no umbrella terms like "backend".                  -->
<!-- ===================================================================== -->

PlantPulse is a telemetry platform for simulated industrial plants. I built it to gain hands-on experience with MQTT, FastAPI, SQLite, WebSockets, Next.js, Docker Compose, pytest, and GitHub Actions. A Python simulator publishes machine data over MQTT, and a FastAPI service stores it and serves it to a Next.js dashboard. It models an 8040 membrane plant with four stages (housing, casting, assembly, and quality control) and extensible multi-plant definitions like municipal water booster stations. The devices are simulated because I don't have access to real industrial equipment.

## Dashboard

### Demo Membrane Manufacturing Facility (Live Streaming)
![Overview Dashboard](docs/overview.png)

### District 9 Water Booster Station (Snapshot Polling & Module Gating)
![Water Plant Overview](docs/water-plant.png)

## What it does

PlantPulse is a multi-plant industrial IoT platform. Plants are declared via JSON schema definitions (`plants/*.json`) that define production areas, machines, expected telemetry signals, and enabled feature modules.

- **8040 Membrane Manufacturing Facility (`plant_demo_membrane`):** An 11-machine production line across four stages (Housing, Membrane Casting, Robotic Assembly, and Quality Testing). Connected clients receive real-time telemetry over WebSockets.
- **District 9 Water Booster Station (`plant_water_district_9`):** A municipal pumping station with three centrifugal pumps. Gated modules automatically hide assembly/QC tabs, and viewer-token authorization falls back to secure 5-second REST snapshot polling.

| Plant | Areas | Assets | Enabled Modules | Access |
|---|---|---|---|---|
| `plant_demo_membrane` | Housing, Casting, Assembly, QC | 11 machines | Core, Alarms, Product Traceability, Quality Inspection | Public Demo (Live Streaming) |
| `plant_water_district_9` | Primary Pump House | 3 intake/booster pumps | Core, Alarms | Token Required (Snapshot Polling) |

## Architecture

```mermaid
flowchart LR
    subgraph Edge Clients
        SIM["Demo Simulator<br/>(demo/simulator/runner.py)"]
        WATCH["Watchdog Timer<br/>(30s auto-idle cap)"]
    end

    subgraph Messaging Layer
        MQTT["Mosquitto Broker :1883<br/>(ACL & Password Auth)"]
    end

    subgraph Platform Backend
        API["FastAPI Backend :8000<br/>(Single Uvicorn Worker)"]
        INGEST["IngestEngine<br/>(Async batch writer)"]
        HEART["Heartbeat Emitter<br/>(5s ping when viewers active)"]
    end

    subgraph Persistence
        DB[("SQLite: platform.db<br/>(WAL + normal sync)")]
    end

    subgraph Client Application
        UI["Next.js Dashboard :3000<br/>(Dynamic Overview + Module Gating)"]
    end

    SIM -->|publishes canonical MQTT topics| MQTT
    API -->|subscribes plants/# & factory/#| MQTT
    API -->|emits control heartbeat| MQTT
    MQTT -->|heartbeat resets watchdog| WATCH
    WATCH -->|runs or pauses line| SIM
    API --> INGEST
    INGEST -->|batched commits off loop| DB
    API -->|REST queries| UI
    API -->|WebSocket rooms /ws/{plant}/telemetry| UI
```

### Key Architectural Characteristics
- **Heartbeat-as-Run Watchdog Protocol:** The simulator only runs while active browser viewers are connected. The API emits heartbeats every 5 seconds when viewers exist; after 30 seconds of silence, the simulator idles to prevent unconstrained SQLite database growth.
- **Broker-Level Topic ACLs:** Edge credentials and topic access are compiled into Mosquitto password and ACL files (`plants/{plant_id}/#`) at boot. Broker port 1883 remains internal to the Docker network.
- **Narrow Telemetry Persistence:** Measurements are committed in batches (`telemetry_values`) with database-enforced idempotency (`UNIQUE(plant_id, message_id, signal_code)`).

---

## Quickstart (Docker Compose)

Run the entire platform (Broker, API, Simulator, and Dashboard) with a single command.

### 1. Prerequisites
- Docker Engine 24+ and Docker Compose v2.

### 2. Configure Environment
Generate your `.env` file from the committed template with a random secure password for the backend service:

```bash
cp .env.example .env && sed -i "s/replace_with_a_secure_random_password/$(openssl rand -hex 16)/" .env
```

### 3. Launch Stack
```bash
docker compose up --build -d
```

Verify service health:
```bash
docker compose ps
```

All services will show `(healthy)`:
- `plantpulse-broker-1`: Mosquitto broker (internal `1883/tcp`)
- `plantpulse-api-1`: FastAPI backend on `http://localhost:8000`
- `plantpulse-dashboard-1`: Next.js web application on `http://localhost:3000`
- `plantpulse-simulator-1`: Simulator runner client

### 4. Open Dashboard
Visit **`http://localhost:3000`** in your browser. Opening the demo plant will connect the WebSocket, start heartbeat emissions, wake the simulator, and stream live machine telemetry.

### 5. Verify Stack
Run the end-to-end smoke verification script:
```bash
python scripts/smoke_stack.py
```

> [!IMPORTANT]
> **Note on Remote VM Deployments (Build-Time Client URLs):**
> Next.js inlines `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` into client-side JavaScript bundles at build time. When deploying to a remote VM or domain, update `.env` before building:
> ```env
> NEXT_PUBLIC_API_URL=http://<VM_IP_OR_DOMAIN>:8000
> NEXT_PUBLIC_WS_URL=ws://<VM_IP_OR_DOMAIN>:8000
> ```
> Then rebuild the dashboard container: `docker compose build dashboard`.

---

## Running Locally (Without Docker)

Prerequisites: Python 3.12, Node 22+, and a local Mosquitto broker.

```bash
# 1. Start Mosquitto with generated auth
python scripts/generate_mosquitto_auth.py \
  --passwd-path /tmp/mosquitto.passwd \
  --acl-path /tmp/mosquitto.acl \
  --backend-user backend_service \
  --backend-password backend_secret

mosquitto -p 1883 -c docker/mosquitto.conf

# 2. Start FastAPI Backend (venv active)
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
MQTT_USER=backend_service MQTT_PASSWORD=backend_secret uvicorn main:app --port 8000

# 3. Start Simulator Runner
MQTT_USER=device_plant_demo_membrane \
MQTT_PASSWORD=demo_membrane_secure_token_123 \
MQTT_CLIENT_ID=client_demo_membrane_sim \
python -m demo.simulator.runner

# 4. Start Dashboard
cd frontend
npm install
npm run dev
```

---

## Testing & Quality Assurance

```bash
# Backend pytest suite (62 tests)
pytest -v

# Frontend unit tests
cd frontend && npm test

# Linting & code formatting
ruff check .
cd frontend && npm run lint
codespell --skip="*.db*,*.wal,*.shm,./venv,./frontend/node_modules,./frontend/.next,./.git,./docs/*.png"
```

---

## Known Limitations

This is a portfolio and learning project demonstrating distributed industrial IoT telemetry patterns. The following known limitations are intentionally documented:

1. **Public Demo Plant Password in Git:** The MQTT device password for `plant_demo_membrane` (`demo_membrane_secure_token_123`) is stored in `plants/plant_demo_membrane.json` to allow the demo stack to boot and run out-of-the-box with zero setup. In real-world deployments, device tokens are injected via secret stores (e.g. HashiCorp Vault or AWS Secrets Manager) and never committed to source control.
2. **REST Endpoints Not Protected by Viewer Token:** When a plant defines a `viewer_token` (`plant_water_district_9`), streaming WebSocket connections are refused with code 4401 (`token_required`), falling back to 5-second REST snapshot polling. However, `GET /api/plants/{plant_id}/machines/latest` is currently unauthenticated on the backend, exposing snapshot telemetry that the viewer token was intended to gate (cataloged for backend auth extension in issue #23).
3. **SQLite Single-File Storage & No Retention Worker Yet:** Telemetry is persisted in a local SQLite file (`platform.db`) using WAL mode. The scheduled background task for 30-day retention cleanup is planned for a subsequent milestone; unconstrained long-term runs without retention will continuously grow the database file.
4. **Faulted Machines Never Recover:** When a simulated machine's vibration exceeds the safety limit (7.0 mm/s), it transitions to `FAULT` permanently. Automated recovery and work-order clearing are not yet implemented.
5. **No Backpressure in Simulator Queues:** Housing runs continuously with unlimited raw materials, so the queue in front of Membrane Casting grows without bound if upstream throughput exceeds downstream cycle times.
6. **Weather Model is a Placeholder:** Ambient weather bias in defect modeling evaluates to a constant 0.0 until an external weather API integration is built.
7. **Defect Patterns Exist by Construction:** QC defect probabilities are generated from mathematical formulas (shift-change bias + anomaly deviations) rather than real physical defect causes.
8. **Viewer Token Removal:** The Admin API and UI do not support removing or clearing a viewer access token once configured on a plant (a blank token on update preserves the existing token hash). Making a protected plant public requires manual database intervention or recreation.