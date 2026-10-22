# PlantPulse

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
        DEVICE["Custom Device / Ingest Script<br/>(docker compose exec broker)"]
    end

    subgraph Messaging Layer
        MQTT["Mosquitto Broker :1883<br/>(Internal Docker Network<br/>Topic ACLs & Password Auth)"]
    end

    subgraph Platform Backend
        API["FastAPI Backend :8000<br/>(Uvicorn on 127.0.0.1)"]
        ME["/api/me Routes<br/>(Ownership & Quota)"]
        INGEST["IngestEngine<br/>(Async batch writer)"]
        HEART["Heartbeat Emitter<br/>(5s ping when viewers active)"]
        RET["Retention Worker<br/>(Partition drop + batched deletes)"]
        THROTTLE["Rate Limiters<br/>(Sliding-window IP throttles)"]
    end

    subgraph Persistence
        DB[("PostgreSQL 16<br/>(Time-partitioned telemetry)")]
        MEMBERS[("plant_members Table<br/>(Clerk user_id ownership)")]
    end

    subgraph Client Application
        UI["Next.js Dashboard :3000<br/>(Dynamic Overview + Module Gating)"]
        MYPLANTS["My Plants Portal /my-plants<br/>(Self-Service Management)"]
        ADMIN["Admin Portal /admin<br/>(Topology & Credential Management)"]
    end

    SIM -->|publishes canonical MQTT topics| MQTT
    DEVICE -->|publishes canonical MQTT topics| MQTT
    API -->|subscribes plants/# & factory/#| MQTT
    API -->|emits control heartbeat| MQTT
    MQTT -->|heartbeat resets watchdog| WATCH
    WATCH -->|runs or pauses line| SIM
    API --> INGEST
    API --> ME
    ME -->|enforces quota & cascades| MEMBERS
    MEMBERS --> DB
    INGEST -->|batched commits off loop| DB
    RET -->|scheduled partition drops & batched purge| DB
    THROTTLE -->|guards REST & WS tickets| API
    API -->|REST queries & downsampled history| UI
    API -->|WebSocket rooms /ws/:plant_id/telemetry| UI
    ME -->|owner CRUD & secret rotation| MYPLANTS
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

## Self-Service Plants & My Plants Portal

PlantPulse enables authenticated users to register and manage personal manufacturing facilities through self-service APIs and the **`/my-plants`** interface:

- **Authentication & Sign-In:** Users authenticate via Clerk through the navigation header controls (`Sign In` / `Sign Up`). When signed in, the header displays a **"My plants"** navigation link alongside account profile controls.
- **Quota Enforced:** Each authenticated user may create up to **3 personal plants** (`canCreatePlant` in [`me-api.ts`](frontend/lib/me-api.ts#L113-L115), HTTP 409 Conflict if exceeded), subject to a platform-wide ceiling of 25 plants.
- **One-Time Secret Issuance:** Upon facility creation (`POST /api/me/plants`), the backend provisions dedicated Mosquitto device credentials (`device_{plant_id}` with a cryptographically secure random password) and a random viewer access token (`viewer_{uuid}`). The response sends `Cache-Control: no-store` and displays secrets once inside the `AdminCredentialsModal` dialog. Plaintext passwords and tokens are never stored in the database; viewer tokens are persisted solely as SHA-256 hashes (`plants.viewer_token_hash`).
- **Private Access & Seamless Ownership:** Newly registered plants are private by default. Plant owners can open the live dashboard and connect to WebSocket telemetry streams directly using their Clerk session JWT without entering a viewer token (`verify_plant_viewer` in [`main.py`](main.py#L299-L327)). External guests require the viewer token to access the facility.
- **Connecting a Device (Internal Broker Notice):**
  - **Network Isolation:** The Mosquitto broker runs internally within the Docker bridge network (port 1883 is not exposed on the host interface). Real external physical devices cannot connect directly today.
  - **Initial Machine State (`OFFLINE`):** By design, machines in newly registered facilities initialize in `OFFLINE` status. The built-in background simulator daemon (`demo.simulator.runner`) exclusively generates synthetic data for the two pre-seeded demo facilities (`plant_demo_membrane` and `plant_water_district_9`). Custom self-service facilities require telemetry published by edge devices, the CLI publisher, or simulation scripts.
  - **Publishing Single Telemetry Readings:** Telemetry can be published directly from within the Docker environment using the container CLI:
    ```bash
    docker compose exec broker mosquitto_pub \
      -u device_<plant_id> \
      -P '<password>' \
      -t 'plants/<plant_id>/assets/<machine_code>/telemetry' \
      -m '{"schema_version":"1.0","plant_id":"<plant_id>","asset_id":"<machine_code>","device_timestamp":"'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'","message_id":"msg-001","payload":{"status":"RUNNING","metrics":{"<signal_code>":42.0}}}'
    ```
  - **Streaming Continuous Telemetry (30-Second Loop):**
    To simulate continuous live sensor streams, update the dashboard, and populate the signal history trend graph:
    ```bash
    for i in $(seq 1 30); do
      ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
      val=$(awk -v i="$i" 'BEGIN{srand(); printf "%.2f", 40.0 + sin(i/3)*5 + (rand()*2)}')
      docker compose exec -T broker mosquitto_pub \
        -u "device_<plant_id>" \
        -P "<password>" \
        -t "plants/<plant_id>/assets/<machine_code>/telemetry" \
        -m "{\"schema_version\":\"1.0\",\"plant_id\":\"<plant_id>\",\"asset_id\":\"<machine_code>\",\"source\":\"simulation\",\"device_timestamp\":\"$ts\",\"message_id\":\"msg-$i\",\"payload\":{\"status\":\"RUNNING\",\"metrics\":{\"<signal_code>\":$val}}}"
      echo "[$i/30] Sent $ts: <signal_code>=$val"
      sleep 1
    done
    ```
  - **Differentiating Simulated vs. Real Hardware Telemetry:**
    In industrial IoT deployments, synthetic testing streams are differentiated from physical device data by attaching a `"source"` attribute to the envelope (`"source": "simulation"` vs `"source": "hardware"`). PlantPulse's ingestion engine preserves all top-level envelope attributes in PostgreSQL (`telemetry_history.raw_payload`), allowing downstream query APIs, alarm rules, and analytics pipelines to isolate or badge synthetic test streams without corrupting production equipment audits.
  - **Topic Pattern:** Validated by `topic_router.py`: `plants/{plant_id}/assets/{machine_code}/telemetry`.
  - **Payload Schema:** Validated by `ingest.py`: requires `schema_version: "1.0"`, matching `plant_id` and `asset_id`, valid ISO 8601 UTC `device_timestamp` (bounded within -2h late and +5m future), non-empty `message_id`, and a `payload` dictionary with `status` and `metrics`.
- **Secret Rotation:** Owners can rotate device credentials (`POST /api/me/plants/{plant_id}/credentials/rotate`) and viewer tokens (`POST /api/me/plants/{plant_id}/viewer-token/rotate`). Rotated secrets send `Cache-Control: no-store`, immediately rewrite Mosquitto auth files, and invalidate previous tokens.
- **Safe Facility Deletion:** Owners can delete their facilities (`DELETE /api/me/plants/{plant_id}`) by confirming the plant ID in a confirmation modal. Deletion purges all plant telemetry values, units, stage events, QC results, members, and credentials, strips the device account from Mosquitto ACLs, and frees the user's plant quota. Built-in system and demo plants (`plant_demo_membrane`, `plant_water_district_9`) cannot be deleted or rotated via self-service endpoints (HTTP 403 / 404).

---

## Clerk Authentication & Local Self-Service Setup

PlantPulse supports Clerk for user identity and role management. To run the self-service flow locally:

### Environment Variables

| Variable | Service | Required / Optional | Description |
|---|---|---|---|
| `CLERK_ISSUER` | Backend (`api`) | Required for Clerk auth | Clerk instance issuer URL (e.g., `https://<instance>.clerk.accounts.dev`) |
| `CLERK_PEM_PUBLIC_KEY` | Backend (`api`) | Required (or `CLERK_JWKS_URL`) | RS256 PEM-formatted public key used to verify session JWT signatures locally |
| `CLERK_JWKS_URL` | Backend (`api`) | Optional | JWKS URL fallback for fetching Clerk public keys dynamically |
| `CLERK_AUTHORIZED_PARTIES` | Backend (`api`) | Optional | Comma-separated list of allowed `azp` authorized party origins (e.g., `http://localhost:3000`) |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Frontend (`dashboard`) | Required for Clerk UI | Clerk publishable API key (`pk_test_...`) |
| `CLERK_SECRET_KEY` | Frontend (`dashboard`) | Required for Clerk SSR | Clerk backend secret key (`sk_test_...`) |
| `NEXT_PUBLIC_CLERK_SIGN_IN_URL` | Frontend (`dashboard`) | Optional (Default: `/sign-in`) | Frontend route for user sign-in |
| `NEXT_PUBLIC_CLERK_SIGN_UP_URL` | Frontend (`dashboard`) | Optional (Default: `/sign-up`) | Frontend route for user registration |
| `NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL` | Frontend (`dashboard`) | Optional (Default: `/`) | Redirect path after successful sign-in |
| `NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL` | Frontend (`dashboard`) | Optional (Default: `/`) | Redirect path after successful sign-up |

### Developer Step-by-Step Walkthrough

1. **Create a Clerk Project:** Sign up at [clerk.com](https://clerk.com), create a new application, and copy your **Publishable Key** and **Secret Key**.
2. **Retrieve PEM Public Key:** In the Clerk Dashboard under **Configure > API Keys > Show JWT public key**, copy the PEM public key.
3. **Configure `.env`:** Add the keys to your `.env` file:
   ```env
   CLERK_ISSUER=https://<your-subdomain>.clerk.accounts.dev
   CLERK_PEM_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
   CLERK_AUTHORIZED_PARTIES=http://localhost:3000
   NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
   CLERK_SECRET_KEY=sk_test_...
   ```
4. **Start Stack:**
   ```bash
   docker compose up -d
   ```
5. **Sign In & Access My Plants:** Open [`http://localhost:3000`](http://localhost:3000) in your browser. Click **Sign In** in the header, complete authentication, and click the **My plants** link.
6. **Register Facility & Test Telemetry:** Click **+ Register New Plant**, submit a new plant topology, save the one-time device credentials, and publish a test telemetry message using the displayed `docker compose exec broker mosquitto_pub` command. Click **Open dashboard** to observe live updates.

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

# 2. Run backend pytest suite (269 passed)
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/plantpulse_test"
pytest -v

# 3. Frontend unit tests (67 passed)
cd frontend && npm test

# 4. Linting & code formatting
ruff check .
cd frontend && npm run lint
codespell --skip="*.db*,*.wal,*.shm,./venv,./frontend/node_modules,./frontend/.next,./.git,./docs/*.png"
```

---

## Known Limitations

This is a portfolio and learning project demonstrating distributed industrial IoT telemetry patterns. The following limitations are intentionally documented:

1. **No HTTP Telemetry Ingest:** Telemetry ingestion is strictly supported via MQTT over the Mosquitto broker. Backend HTTP REST endpoints handle plant management, authentication, and history downsampling, but do not accept device sensor ingest payloads directly.
2. **No Topology Editing for Self-Service Owners:** Plant owners on `/my-plants` can define initial topologies, rotate device credentials and viewer tokens, and delete their plants. In-place topology edits (renaming areas, adding/removing machines, editing signals) are restricted to platform administrators in `/admin`.
3. **No Email-Based Invitations:** Sharing private plants with external viewers is performed out-of-band by distributing the generated viewer token. There is currently no built-in email invitation flow or multi-user access control list for individual private plants.
4. **`ADMIN_TOKEN` Fallback Gated by `MOUNT_ADMIN_ENDPOINTS`:** When `MOUNT_ADMIN_ENDPOINTS=false`, all `/api/admin/*` endpoints return 404 Not Found. The legacy static `ADMIN_TOKEN` fallback only applies to `/api/admin` when mounted. The self-service routes under `/api/me` are always mounted and require a valid Clerk user JWT.
5. **In-Memory Rate Limiter Reset & Proxy IP Sharing:** Rate-limiting attempt histories and lockout state (e.g. 5 failed token attempts in 60s) reside in Python process memory and reset whenever the API process restarts. Because client socket IPs are evaluated directly without trusting `X-Forwarded-For`, clients situated behind a shared reverse proxy or corporate NAT pool share a single rate-limiting bucket.
6. **Public Demo Passwords & Tokens in `.env.example`:** Pre-configured demo credentials (e.g., `MQTT_PASSWORD`, `WATER_MQTT_PASSWORD`, and `PLANT_WATER_DISTRICT_9_VIEWER_TOKEN`) are included in `.env.example` to allow zero-setup out-of-the-box evaluation. In production environments, credentials should be randomly generated and injected through external secret managers.
7. **Partition Key in Deduplication Constraint:** Native PostgreSQL time partitioning requires the partition key (`device_timestamp`) to be included in all unique constraints and primary keys on partitioned tables. As a result, the primary key of `telemetry_values` is `(device_timestamp, plant_id, message_id, signal_code)`. If an edge device retry generates a new timestamp rather than retaining the original sample timestamp, the message will be stored twice. When retried QoS 1 redelivery preserves the original timestamp, duplicates are cleanly dropped via `ON CONFLICT DO NOTHING`.
8. **At-Most-Once Delivery Inside API:** The IngestEngine buffers incoming MQTT telemetry in an asynchronous queue before committing batched inserts. An abrupt server termination or container kill will drop in-flight uncommitted measurements.
9. **Partition-Drop Retention Window:** Measurements older than `RETENTION_DAYS` (default 30) are purged by dropping matching daily leaf partition tables (`DROP TABLE telemetry_values_pYYYY_MM_DD`), immediately reclaiming disk space. Out-of-window timestamps arriving outside managed partition boundaries are rejected by PostgreSQL because no catch-all default partition is configured.
10. **Stored Plants Violating Validation Caps Skipped on Startup:** If historical or manually edited database rows contain plant definitions exceeding validation constraints (e.g. >100 machines, >500 signals, or >57-character `plant_id`), `load_plants_from_db` logs a `WARNING` and skips the invalid plant so the platform continues booting cleanly for valid facilities.

---

## Roadmap

### Planned Features
- **Invite-by-Email & Multi-Member Permissions:** Email-based user invitations and scoped permission tiers (`viewer`, `operator`, `manager`) for self-service plants.
- **HTTP Telemetry Ingest with Per-Plant API Keys:** Direct HTTPS POST ingest endpoints authenticated via per-plant device API keys for edge microcontrollers or third-party webhooks unable to run MQTT clients.
- **Self-Service Owner Topology Editing:** In-place machine, area, and signal reconfiguration for plant owners directly within `/my-plants`.
- **Retire `ADMIN_TOKEN` (Clerk PR 3):** Full retirement of the transitional static `ADMIN_TOKEN` fallback, requiring Clerk authentication with a `platform_admin` role claim for all administrative operations.
- **Cloud Hosting & Serverless Deployment:** Migration to zero-cost cloud infrastructure (OCI Always Free / Koyeb + Supabase + EMQX Cloud) with viewer-gated simulation (see [`docs/design/hosting-feasibility.md`](docs/design/hosting-feasibility.md)).

### Future Exploration (Backlog Ideas)
- **Remote Machine Control (#24):** Bidirectional MQTT command topics to toggle actuators or setpoints.
- **Alerts & Real-Time Notifications (#25):** Event-driven alert rules and webhook/email dispatch on threshold violations.
- **Preventative Maintenance Scheduling (#26):** Asset operating hour tracking and maintenance interval countdowns.
- **Overall Equipment Effectiveness (OEE) Metrics (#27):** Automated calculation of availability, performance, and quality scores.
- **Live Weather Integration (#28):** Ingesting ambient temperature and humidity into the casting defect model.
- **Bounded Simulator Queues with Backpressure (#30):** Flow-control between production stages when downstream buffers fill.
- **Per-Plant Ingest Rate Limits (#32):** Token-bucket rate limiting on edge device MQTT ingestion.