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
        RET["Retention Worker<br/>(Partition drop + batched deletes)"]
        THROTTLE["Rate Limiters<br/>(Sliding-window IP throttles)"]
    end

    subgraph Persistence
        DB[("PostgreSQL 16<br/>(Time-partitioned telemetry)")]
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
    RET -->|scheduled partition drops & batched purge| DB
    THROTTLE -->|guards REST & WS tickets| API
    API -->|REST queries & downsampled history| UI
    API -->|WebSocket rooms /ws/{plant}/telemetry| UI
    API -->|Admin CRUD endpoints| ADMIN
```

### Key Architectural Characteristics
- **Heartbeat-as-Run Watchdog Protocol:** The simulator only runs while active browser viewers are connected. The API emits heartbeats every 5 seconds when viewers exist; after 30 seconds of silence, the simulator idles to prevent unconstrained database growth.
- **Broker-Level Topic ACLs & Password Auth:** Edge credentials and topic access are compiled into Mosquitto password and ACL files (`plants/{plant_id}/#`) at boot. Broker port 1883 remains internal to the Docker network.
- **Native Daily Time Partitioning & Idempotency:** Measurements are committed in batches (`telemetry_values`) partitioned daily by `device_timestamp` with composite primary key `(device_timestamp, plant_id, message_id, signal_code)` and `ON CONFLICT DO NOTHING` deduplication. Partitions are pre-created across `[today-1 .. today+7]`.
- **Partition-Drop Retention (`RETENTION_DAYS`):** Telemetry values are retained for a configurable window (`RETENTION_DAYS`, default 30). The retention worker automatically drops daily leaf partitions (`DROP TABLE telemetry_values_pYYYY_MM_DD`) older than the cutoff, returning physical disk storage to the filesystem immediately with zero fragmentation or VACUUM locking. Product traceability records (`units`, `stage_events`, `qc_results`) are cleaned using composite-key batched deletes.
- **Strict Localhost Port Binding:** The API service binds port 8000 strictly to loopback (`127.0.0.1:8000`) in Docker Compose to prevent exposing backend endpoints directly on public network interfaces in VM deployments.

---

## Signal Telemetry History Graph

PlantPulse provides time-series trend analysis for machine sensor readings via an interactive chart modal and downsampled API query:

- **Endpoint:** `GET /api/plants/{plant_id}/machines/{machine_code}/signals/{signal_code}/history`
- **Time Windows:** Supported via query parameters `start` and `end` (ISO 8601 UTC timestamps; default window is the last 1 hour, maximum window is 24 hours, minimum 10 seconds).
- **Adaptive Downsampling:** Queries accept `points` (bounded between 10 and 500, default 300) and group timestamps into even time buckets using PostgreSQL `date_bin`, computing `avg_value`, `min_value`, and `max_value`.
- **Gap Detection:** Frontend chart rendering detects gaps exceeding 2x the expected interval and inserts sentinel breaks to prevent misleading straight-line interpolation during simulator idle periods.

---

## Background Telemetry Retention

To prevent unbounded database growth during extended runs, a scheduled background worker continuously enforces a configurable retention window:

- **Configuration:** Controlled by `RETENTION_DAYS` (default `30` days) and `ENABLE_RETENTION_WORKER` (default `true`, disabled in test environments). Upcoming partitions are pre-created across range `[today-1 .. today+7]` at startup and daily.
- **Partition Drops & Batched Purges:** Telemetry data is purged by dropping expired daily partitions (`DROP TABLE telemetry_values_pYYYY_MM_DD`) older than `RETENTION_DAYS`, immediately reclaiming physical disk space without vacuum locking. Associated operational data in `units`, `stage_events`, and `qc_results` are cleaned using non-blocking composite-key batched deletes in chunks of 50,000 rows off the main event loop.

---

## Admin API & Management Portal

PlantPulse includes a complete administrative facility management system mounted conditionally via environment variables:

- **Activation:** Set `MOUNT_ADMIN_ENDPOINTS=true`. When disabled, all `/api/admin/*` endpoints return 404 Not Found.
- **Authentication & Roles:** Supports Clerk RS256 JWT user authentication (PRs #97 and #98) with role scoping (`platform_admin` and `plant_manager`), as well as a pre-shared static `ADMIN_TOKEN` (grants `platform_admin`) which remains active as a fallback until deprecated and removed. For `ADMIN_TOKEN`, [`admin_auth.py`](admin_auth.py#L170-L196) requires a **non-empty string** (`if not admin_token: raise HTTPException(503)`), comparing tokens in constant time via `secrets.compare_digest`. A length of **32+ characters** is recommended for production cryptographic entropy (as shown in [`AdminUnmountedScreen.tsx`](frontend/components/admin/AdminUnmountedScreen.tsx#L39)), but is not enforced by code.
  - **Backend (`api`) Clerk Environment Variables:** `CLERK_PEM_PUBLIC_KEY`, `CLERK_JWKS_URL`, `CLERK_ISSUER`, `CLERK_AUTHORIZED_PARTIES`
  - **Frontend (`dashboard`) Clerk Environment Variables:** `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `NEXT_PUBLIC_CLERK_SIGN_IN_URL`, `NEXT_PUBLIC_CLERK_SIGN_UP_URL`, `NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL`, `NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL`
- **Input Validation & Security Caps (PR #100 / #101):**
  - **Plant Name:** Length 1–128 characters; strictly rejects newlines (`\n`, `\r`) and ASCII control characters (< 32, 127–159).
  - **Plant ID:** RegEx `^[a-z0-9_]{3,57}$` (capped at 57 characters so `device_{plant_id}` conforms to the 64-character MQTT username limit).
  - **MQTT Credentials:** Usernames must match `^[a-z0-9_]{3,64}$`; passwords must not contain newlines, carriage returns, or control characters.
  - **Topological Caps:** Maximum 100 machines per plant, maximum 100 signals per machine, maximum 500 signals total per plant (HTTP 422).
  - **Request Body Size Limit:** Strict 1 MB cap (`MAX_ADMIN_BODY_BYTES = 1_048_576`) enforced via pure ASGI middleware on POST/PUT requests under `/api/admin/*`, returning HTTP 413 Payload Too Large without buffering large bodies into memory.
- **Admin Portal (`/admin`):** A Next.js management interface providing:
  - User sign-in via Clerk or static token fallback (tokens stored in React memory, never persisted to disk or `localStorage`).
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
2. **Viewer Access Tokens & Database Ownership:** Plant definition files (`plants/*.json`) contain zero plaintext passwords or viewer tokens. Secrets are seeded into PostgreSQL on first boot (when the `plants` table is empty) via environment variables by `seed_plants_if_empty` and `sync_plant_definitions`, while Alembic manages schema migrations. Viewer tokens are stored exclusively as SHA-256 hashes (`plants.viewer_token_hash`).
3. **Single-Use WebSocket Tickets:** Protected WebSocket streams (`/ws/{plant_id}/telemetry`) require a short-lived ticket (`POST /api/plants/{plant_id}/ws-ticket`) issued with Bearer authorization. Tickets are valid for 30 seconds and consumed on first use to prevent secret leakage in URL query parameters and access logs.
4. **Clerk RS256 JWT Authentication & Scoped Roles:** Admin endpoints verify Clerk session JWTs in memory using `CLERK_PEM_PUBLIC_KEY` (or cached JWKS via `CLERK_JWKS_URL`), validating issuer, expiration, and authorized parties (`azp`). Roles distinguish full platform administrators (`platform_admin`) from plant-scoped managers (`plant_manager`). Static `ADMIN_TOKEN` remains supported as a transitional fallback.
5. **Broker Auth Input Sanitization & Caps:** Admin plant creation and modification endpoints validate all topology names and MQTT credentials at the Pydantic and file-writing layers. Comments in `acl.conf` interpolate only validated `plant_id`, preventing newline injection into Mosquitto configuration.
6. **Sliding-Window Rate Limiting:** Separate in-memory rate limiters protect Admin and Viewer endpoints. After 5 incorrect token guesses within a 60-second window, subsequent requests receive HTTP 429 (`Too Many Requests`) with a `Retry-After` header. Rate limiting checks the lockout status before parsing headers or comparing hashes, and malformed authorization headers count against the attempt budget.
7. **No Reverse-Proxy Header Trust:** Client IP addresses are extracted directly from the underlying socket host without trusting `X-Forwarded-For` headers, preventing header spoofing attacks.

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

Core services will show `(healthy)` (while `simulator` shows `Up`, as it has no healthcheck):
- `plantpulse-broker-1`: Mosquitto broker (internal `1883/tcp`)
- `plantpulse-postgres-1`: PostgreSQL 16 database (internal `5432/tcp`)
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

Prerequisites: Python 3.12, Node 22+, a local Mosquitto broker, and a running PostgreSQL 16 instance.

```bash
# 1. Start local PostgreSQL instance (or use docker):
docker run -d --name plantpulse-postgres -p 5432:5432 \
  -e POSTGRES_USER=plantpulse \
  -e POSTGRES_PASSWORD=plantpulse \
  -e POSTGRES_DB=plantpulse \
  postgres:16-alpine

# 2. Configure environment and start Mosquitto with generated auth
cp .env.example .env && set -a && source .env && set +a

python scripts/generate_mosquitto_auth.py \
  --passwd-path /tmp/mosquitto.passwd \
  --acl-path /tmp/mosquitto.acl \
  --backend-user backend_service \
  --backend-password backend_secret

mosquitto -p 1883 -c docker/mosquitto.conf

# 3. Start FastAPI Backend (venv active)
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql://plantpulse:plantpulse@localhost:5432/plantpulse"
alembic upgrade head

# Optional: Migrate legacy SQLite database (platform.db) to PostgreSQL via streaming COPY
python scripts/migrate_sqlite_to_postgres.py --sqlite-path platform.db --postgres-url "$DATABASE_URL"

MQTT_USER=backend_service MQTT_PASSWORD=backend_secret uvicorn main:app --port 8000

# 4. Start Simulator Runner
MQTT_USER=device_plant_demo_membrane \
MQTT_PASSWORD=demo_membrane_secure_token_123 \
MQTT_CLIENT_ID=client_demo_membrane_sim \
python -m demo.simulator.runner

# 5. Start Dashboard
cd frontend
npm install
npm run dev
```

---

## Testing & Quality Assurance

Tests execute against a PostgreSQL database configured via `DATABASE_URL`. In CI and automated runs, tests fail if PostgreSQL is unreachable.

```bash
# 1. Start test PostgreSQL container:
docker run -d --name plantpulse-test-pg -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16-alpine

# 2. Run backend pytest suite (253 passed)
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/plantpulse_test"
pytest -v

# 3. Frontend unit tests (63 passed)
cd frontend && npm test

# 4. Linting & code formatting
ruff check .
cd frontend && npm run lint
codespell --skip="*.db*,*.wal,*.shm,./venv,./frontend/node_modules,./frontend/.next,./.git,./docs/*.png"
```

---

## Known Limitations

This is a portfolio and learning project demonstrating distributed industrial IoT telemetry patterns. The following limitations are intentionally documented:

1. **Public Demo Passwords & Tokens in `.env.example`:** Pre-configured demo credentials (e.g., `MQTT_PASSWORD`, `WATER_MQTT_PASSWORD`, and `PLANT_WATER_DISTRICT_9_VIEWER_TOKEN`) are included in `.env.example` to allow zero-setup out-of-the-box evaluation. In production environments, credentials should be randomly generated and injected through external secret managers.
2. **In-Memory Rate Limiter Reset & Proxy IP Sharing:** Rate-limiting attempt histories are maintained in memory and reset whenever the API process restarts. Because client socket IPs are evaluated directly without trusting `X-Forwarded-For`, clients situated behind a shared reverse proxy or corporate NAT pool share a single rate-limiting bucket.
3. **Partition Key in Deduplication Constraint:** Native PostgreSQL time partitioning requires the partition key (`device_timestamp`) to be included in all unique constraints and primary keys on partitioned tables. As a result, the primary key of `telemetry_values` is `(device_timestamp, plant_id, message_id, signal_code)`. If an edge device retry generates a new timestamp rather than retaining the original sample timestamp, the message will be stored twice. When retried QoS 1 redelivery preserves the original timestamp, duplicates are cleanly dropped via `ON CONFLICT DO NOTHING`.
4. **At-Most-Once Delivery Inside API:** The IngestEngine buffers incoming MQTT telemetry in an asynchronous queue before committing batched inserts. An abrupt server termination or container kill will drop in-flight uncommitted measurements.
5. **Partition-Drop Retention Window:** Measurements older than `RETENTION_DAYS` (default 30) are purged by dropping matching daily leaf partition tables (`DROP TABLE telemetry_values_pYYYY_MM_DD`), immediately reclaiming disk space. Out-of-window timestamps arriving outside managed partition boundaries are rejected by PostgreSQL because no catch-all default partition is configured.
6. **Clerk Authentication Transition & Static `ADMIN_TOKEN` Fallback:** User authentication via Clerk (PRs #97 and #98) is fully implemented for administrative access and plant scoping (`platform_admin` and `plant_manager`). The legacy static `ADMIN_TOKEN` remains functional alongside Clerk for backward compatibility until explicitly retired. In `admin_auth.py`, a non-empty token is strictly required (`if not admin_token and not clerk_configured: raise HTTPException(503)`), while 32+ characters are recommended for cryptographic security; when valid, it grants full `platform_admin` privileges.
7. **No Viewer Token Removal in Admin UI:** The Admin UI allows rotating or updating existing plant viewer tokens, but clearing a token back to public unauthenticated access is not supported from the interface (preserving the existing token hash on blank submission). Making a protected plant public requires manual database intervention.
8. **Stored Plants Violating Validation Caps Skipped on Startup:** If historical or manually edited database rows contain plant definitions exceeding new validation constraints (e.g. >100 machines, >500 signals, or >57-character `plant_id`), `load_plants_from_db` logs a `WARNING` and skips the invalid plant so the platform continues booting cleanly for valid facilities.

---

## Roadmap

### Planned Features
- **Self-Service Plants & Multi-Tenant Provisioning:** User-driven facility creation, invite-only onboarding, and scoped plant manager assignments (see [`docs/design/self-service-plants.md`](docs/design/self-service-plants.md)).
- **Cloud Hosting & Serverless Deployment:** Migration to zero-cost cloud infrastructure (OCI Always Free / Koyeb + Supabase + EMQX Cloud) with viewer-gated simulation (see [`docs/design/hosting-feasibility.md`](docs/design/hosting-feasibility.md)).

### Future Exploration (Backlog Ideas)
- **Remote Machine Control (#24):** Bidirectional MQTT command topics to toggle actuators or setpoints.
- **Alerts & Real-Time Notifications (#25):** Event-driven alert rules and webhook/email dispatch on threshold violations.
- **Preventative Maintenance Scheduling (#26):** Asset operating hour tracking and maintenance interval countdowns.
- **Overall Equipment Effectiveness (OEE) Metrics (#27):** Automated calculation of availability, performance, and quality scores.
- **Live Weather Integration (#28):** Ingesting ambient temperature and humidity into the casting defect model.
- **Bounded Simulator Queues with Backpressure (#30):** Flow-control between production stages when downstream buffers fill.
- **Per-Plant Ingest Rate Limits (#32):** Token-bucket rate limiting on edge device MQTT ingestion.