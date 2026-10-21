# PlantPulse

<!-- ===================================================================== -->
<!-- INTRO BLOCK (User to write)                                           -->
<!-- Write your one-sentence project definition and 2-sentence rationale   -->
<!-- here. Plain words, no umbrella terms like "backend".                  -->
<!-- ===================================================================== -->

PlantPulse is a telemetry platform for simulated industrial plants. I built it to gain hands-on experience with MQTT, FastAPI, SQLite, WebSockets, Next.js, Docker Compose, pytest, and GitHub Actions. A Python simulator publishes machine data over MQTT, and a FastAPI service stores it and serves it to a Next.js dashboard. It models an 8040 membrane plant with four stages (housing, casting, assembly, and quality control) and extensible multi-plant definitions like municipal water booster stations. The devices are simulated because I don't have access to real industrial equipment.

## Dashboard & System Views

### Demo Membrane Manufacturing Facility (Live Streaming)
![Overview Dashboard](docs/overview.png)

### District 9 Water Booster Station (Snapshot Polling & Module Gating)
![Water Plant Overview](docs/water-plant.png)

### Protected Plant Viewer Token Prompt
![Viewer Token Authentication](docs/token-form.png)

### Downsampled Telemetry Signal History Graph
![Signal History Graph](docs/history-graph.png)

### Admin Facility Management Portal
![Admin Facility Portal](docs/admin-plants.png)

---

## What it does

PlantPulse is a multi-plant industrial IoT platform. Plants are declared via JSON schema definitions (`plants/*.json`) that define production areas, machines, expected telemetry signals, and enabled feature modules.

- **8040 Membrane Manufacturing Facility (`plant_demo_membrane`):** An 11-machine production line across four stages (Housing, Membrane Casting, Robotic Assembly, and Quality Testing). Connected clients receive real-time telemetry over WebSockets.
- **District 9 Water Booster Station (`plant_water_district_9`):** A municipal pumping station with three centrifugal pumps. Gated modules automatically hide assembly/QC tabs, and viewer-token authorization falls back to secure 5-second REST snapshot polling or token-authenticated streaming.

| Plant | Areas | Assets | Enabled Modules | Access Mode |
|---|---|---|---|---|
| `plant_demo_membrane` | Housing, Casting, Assembly, QC | 11 machines | Core, Alarms, Product Traceability, Quality Inspection | Public Demo (Live Streaming) |
| `plant_water_district_9` | Primary Pump House | 3 intake/booster pumps | Core, Alarms | Token Required (Snapshot Polling or Ticketed WebSocket) |

---

## Architecture

```mermaid
flowchart LR
    subgraph Edge Clients
        SIM["Demo Simulator<br/>(demo/simulator/runner.py)"]
        WATCH["Watchdog Timer<br/>(30s auto-idle cap)"]
    end

    subgraph Messaging Layer
        MQTT["Mosquitto Broker :1883<br/>(Topic ACLs & Password Auth)"]
    end

    subgraph Platform Backend
        API["FastAPI Backend :8000<br/>(Uvicorn on 127.0.0.1)"]
        INGEST["IngestEngine<br/>(Async batch writer)"]
        HEART["Heartbeat Emitter<br/>(5s ping when viewers active)"]
        RET["Retention Worker<br/>(30-day batched purge + vacuum)"]
        THROTTLE["Rate Limiters<br/>(Sliding-window IP throttles)"]
    end

    subgraph Persistence
        DB[("SQLite: platform.db<br/>(WAL + normal sync)")]
    end

    subgraph Client Application
        UI["Next.js Dashboard :3000<br/>(Dynamic Overview + Module Gating)"]
        ADMIN["Admin Portal /admin<br/>(Topology & Credential Management)"]
    end

    SIM -->|publishes canonical MQTT topics| MQTT
    API -->|subscribes plants/# & factory/#| MQTT
    API -->|emits control heartbeat| MQTT
    MQTT -->|heartbeat resets watchdog| WATCH
    WATCH -->|runs or pauses line| SIM
    API --> INGEST
    INGEST -->|batched commits off loop| DB
    RET -->|scheduled purge & vacuum| DB
    THROTTLE -->|guards REST & WS tickets| API
    API -->|REST queries & downsampled history| UI
    API -->|WebSocket rooms /ws/{plant}/telemetry| UI
    API -->|Admin CRUD endpoints| ADMIN
```

### Key Architectural Characteristics
- **Heartbeat-as-Run Watchdog Protocol:** The simulator only runs while active browser viewers are connected. The API emits heartbeats every 5 seconds when viewers exist; after 30 seconds of silence, the simulator idles to prevent unconstrained SQLite database growth.
- **Broker-Level Topic ACLs & Password Auth:** Edge credentials and topic access are compiled into Mosquitto password and ACL files (`plants/{plant_id}/#`) at boot. Broker port 1883 remains internal to the Docker network.
- **Narrow Telemetry Persistence:** Measurements are committed in batches (`telemetry_values`) with database-enforced idempotency (`UNIQUE(plant_id, message_id, signal_code)`).
- **Strict Localhost Port Binding:** The API service binds port 8000 strictly to loopback (`127.0.0.1:8000`) in Docker Compose to prevent exposing backend endpoints directly on public network interfaces in VM deployments.

---

## Signal Telemetry History Graph

PlantPulse provides time-series trend analysis for machine sensor readings via an interactive chart modal and downsampled API query:

- **Endpoint:** `GET /api/plants/{plant_id}/signals/{machine_code}/{signal_code}/history`
- **Time Windows:** Supported via query parameter `range` (`1h`, `6h`, `12h`, `24h`, default `1h`).
- **Adaptive Downsampling:** Queries accept `points` (bounded between 10 and 500, default 300) and group timestamps into even time buckets using SQLite integer division, computing `avg_value`, `min_value`, and `max_value`.
- **Gap Detection:** Frontend chart rendering detects gaps exceeding 2x the expected interval and inserts sentinel breaks to prevent misleading straight-line interpolation during simulator idle periods.

---

## Background Telemetry Retention

To prevent unbounded SQLite database growth during extended runs, a scheduled background worker continuously enforces a configurable retention window:

- **Configuration:** Controlled by `RETENTION_DAYS` (default `30` days) and `ENABLE_RETENTION_WORKER` (default `true`, disabled in test environments).
- **Non-Blocking Batched Deletes:** Deletions run off the main event loop in chunks of 50,000 rows (`DELETE ... WHERE timestamp < ? LIMIT 50000`) until all expired telemetry is purged.
- **Space Reclamation:** Periodically executes `PRAGMA incremental_vacuum` in small increments, or runs a full `VACUUM` when database free pages exceed a 20% threshold, ensuring concurrent ingestion writes remain responsive.

---

## Admin API & Management Portal

PlantPulse includes a complete administrative facility management system mounted conditionally via environment variables:

- **Activation:** Set `MOUNT_ADMIN_ENDPOINTS=true` and configure a 32+ character static `ADMIN_TOKEN`. When disabled, all `/api/admin/*` endpoints return 404 Not Found.
- **Admin Portal (`/admin`):** A Next.js management interface providing:
  - Token entry and session management (stored in React memory, never persisted to disk or `localStorage`).
  - Plant facility registry and summary cards.
  - Interactive multi-step form to create new plant topologies or import definitions from JSON.
  - In-place plant topology editor (renaming areas, adding/removing machines and signals).
  - Conflict confirmation flow (HTTP 409) displaying plain-word removal warnings before applying destructive structural changes.
  - Safe plant deletion requiring confirmation by typing the target `plant_id` (system plants are protected with disable badges).
  - One-time MQTT credential rotation modal with copyable passwords.
  - Definition export downloading sanitized JSON (strictly redacting all tokens, passwords, and secret hashes).

---

## Security Model

PlantPulse employs defense-in-depth across the broker, API, database, and client layers:

1. **Broker Isolation & Topic ACLs:** Each simulated device authenticates with Mosquitto using dedicated credentials. ACL rules enforce read/write access strictly to `plants/{plant_id}/#`. The broker port (`1883`) is never exposed outside the Docker bridge network.
2. **Viewer Access Tokens & Database Ownership:** Plant definition files (`plants/*.json`) contain zero plaintext passwords or viewer tokens. Secrets are seeded into SQLite (`platform.db`) on first boot via environment variables. Viewer tokens are stored exclusively as SHA-256 hashes (`plants.viewer_token_hash`).
3. **Single-Use WebSocket Tickets:** Protected WebSocket streams (`/ws/{plant_id}/telemetry`) require a short-lived ticket (`POST /api/plants/{plant_id}/ws-ticket`) issued with Bearer authorization. Tickets are valid for 30 seconds and consumed on first use to prevent secret leakage in URL query parameters and access logs.
4. **Sliding-Window Rate Limiting:** Separate in-memory rate limiters protect Admin and Viewer endpoints. After 5 incorrect token guesses within a 60-second window, subsequent requests receive HTTP 429 (`Too Many Requests`) with a `Retry-After` header. Rate limiting checks the lockout status before parsing headers or comparing hashes, and malformed authorization headers count against the attempt budget.
5. **No Reverse-Proxy Header Trust:** Client IP addresses are extracted directly from the underlying socket host without trusting `X-Forwarded-For` headers, preventing header spoofing attacks.

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
- `plantpulse-api-1`: FastAPI backend on `http://127.0.0.1:8000`
- `plantpulse-dashboard-1`: Next.js web application on `http://localhost:3000`
- `plantpulse-simulator-1`: Simulator runner client

### 4. Open Dashboard
Visit **`http://localhost:3000`** in your browser. Opening the demo plant will connect the WebSocket, start heartbeat emissions, wake the simulator, and stream live machine telemetry.

### 5. Verify Stack
Run the end-to-end smoke verification script:
```bash
python scripts/smoke_stack.py
```

> [!NOTE]
> `smoke_stack.py` requires the `websockets` client package. Run it with an activated virtual environment (`source venv/bin/activate`) or install it directly via `pip install websockets`.

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
# 1. Configure environment and start Mosquitto with generated auth
cp .env.example .env && set -a && source .env && set +a

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
# Backend pytest suite (171 passed)
pytest -v

# Frontend unit tests (59 passed)
cd frontend && npm test

# Linting & code formatting
ruff check .
cd frontend && npm run lint
codespell --skip="*.db*,*.wal,*.shm,./venv,./frontend/node_modules,./frontend/.next,./.git,./docs/*.png"
```

---

## Known Limitations

This is a portfolio and learning project demonstrating distributed industrial IoT telemetry patterns. The following limitations are intentionally documented:

1. **Public Demo Passwords & Tokens in `.env.example`:** Pre-configured demo credentials (e.g., `MQTT_PASSWORD`, `WATER_MQTT_PASSWORD`, and `PLANT_WATER_DISTRICT_9_VIEWER_TOKEN`) are included in `.env.example` to allow zero-setup out-of-the-box evaluation. In production environments, credentials should be randomly generated and injected through external secret managers.
2. **In-Memory Rate Limiter Reset & Proxy IP Sharing:** Rate-limiting attempt histories are maintained in memory and reset whenever the API process restarts. Because client socket IPs are evaluated directly without trusting `X-Forwarded-For`, clients situated behind a shared reverse proxy or corporate NAT pool share a single rate-limiting bucket.
3. **Legacy `/api` Endpoints Unauthenticated:** Legacy endpoints retained for backwards compatibility (`/api/units`, `/api/summary`) are unauthenticated. Production deployments should disable or deprecate legacy routes.
4. **SQLite Single-File Persistence:** The platform persists telemetry in a single local SQLite file (`platform.db`) using WAL mode. While efficient for single-node deployments, it lacks distributed clustering, high availability, and horizontal multi-writer scaling.
5. **At-Most-Once Delivery Inside API:** The IngestEngine buffers incoming MQTT telemetry in an asynchronous queue before committing batched inserts. An abrupt server termination or container kill will drop in-flight uncommitted measurements.
6. **Retention VACUUM Requires Free Disk Space:** SQLite full `VACUUM` operations duplicate the database file during compaction. Running a full vacuum on large databases requires free disk capacity equal to or greater than the current size of `platform.db`.
7. **Static Admin Token Until Login Session (#55):** Admin authentication currently uses a static pre-shared Bearer secret (`ADMIN_TOKEN`). Interactive user accounts, database-backed roles, and session token rotation are cataloged for a subsequent milestone.
8. **No Viewer Token Removal in Admin UI:** The Admin UI allows rotating or updating existing plant viewer tokens, but clearing a token back to public unauthenticated access is not supported from the interface (preserving the existing token hash on blank submission). Making a protected plant public requires manual database intervention.