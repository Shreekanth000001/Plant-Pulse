# PlantPulse End-to-End User Flows, Data Paths & Access Control Audit

**Document:** `docs/design/user-flows.md`  
**Status:** Audit & Architecture Specification  
**Branch:** `docs/plans-ingest-and-admin-token`  
**Scope:** Read-only system audit, network security boundaries, access matrix, and actor journey specifications (no code changes).  

---

## 1. End-to-End Data Path Architecture & Network Security Boundaries

### 1.1 Mermaid Data Path Diagram

```mermaid
sequenceDiagram
    autonumber
    actor Edge as IoT Edge Gateway / Device<br>(PLC / Sensor Hub)
    participant Broker as Mosquitto MQTT Broker<br>(Port 1883 Internal)
    participant API as FastAPI Backend Service<br>(Uvicorn on :8000)
    participant DB as PostgreSQL 16 DB<br>(Port 5432 Internal)
    actor Browser as Operator / Viewer Web Browser<br>(Next.js on :3000)

    Note over Edge,Broker: Hop 1: Device Ingestion over MQTT
    Edge->>Broker: CONNECT (user: device_{plant_id}, pass: pbkdf2_secret)
    Broker-->>Edge: CONNACK (Authenticated against /mosquitto/auth/passwd)
    Edge->>Broker: PUBLISH plants/{plant_id}/assets/{machine_code}/telemetry
    Broker-->>Broker: Validate Topic against /mosquitto/auth/acl.conf<br>(Rule: topic readwrite plants/{plant_id}/#)

    Note over Broker,API: Hop 2: Backend MQTT Consumer
    API->>Broker: SUBSCRIBE plants/# (user: backend_service)
    Broker-->>API: Forward MQTT Message (telemetry / state / qc_result)
    API-->>API: Validate Envelope in ingest.py (Schema 1.0, timestamp, plant/asset match)

    Note over API,DB: Hop 3: Partitioned Storage
    API->>DB: Batch INSERT into telemetry_values_pYYYY_MM_DD<br>(SQL ON CONFLICT DO NOTHING)
    API->>DB: Upsert machine_states (state, sub_state, last_seen_at)

    Note over API,Browser: Hop 4: Real-Time Browser Streaming & History
    Browser->>API: POST /api/plants/{plant_id}/ws-ticket<br>(Header: Authorization: Bearer <viewer_token>)
    API-->>Browser: Ticket JSON: { ticket: "<uuid>", expires_in: 30 }
    Browser->>API: WS /ws/{plant_id}/telemetry?ticket=<ticket>
    API-->>API: ticket_store.validate_and_consume(ticket)<br>(Single-use validation; consumed immediately)
    API-->>Browser: 101 Switching Protocols -> Live Telemetry Broadcast
    Browser->>API: GET /api/plants/{plant_id}/machines/{machine}/signals/{sig}/history?start=...&end=...
    API->>DB: Query date_bin interval bucket aggregation from daily partitions
    DB-->>API: Aggregated downsampled bucket rows
    API-->>Browser: JSON { bucket_seconds: 12, data: [...] }
```

### 1.2 Network Boundary & Authentication Rule Verification

The data path was audited against [`docker-compose.yml`](file:///home/critic-coder/project/PlantPulse/docker-compose.yml), [`docker/mosquitto.conf`](file:///home/critic-coder/project/PlantPulse/docker/mosquitto.conf), and [`scripts/generate_mosquitto_auth.py`](file:///home/critic-coder/project/PlantPulse/scripts/generate_mosquitto_auth.py):

1. **Published Ports:**
   - **Mosquitto Broker:** Only `expose: - "1883"` inside the docker network. Port 1883 is **not published** to external host interfaces in `docker-compose.yml`.
   - **PostgreSQL Database:** No `ports:` or `expose:` directives published to host; internal to container network.
   - **FastAPI API (`api` service):** Strictly bound to loopback: `127.0.0.1:8000:8000`. Prevents public network exposure on cloud VM deployments while allowing reverse proxies (Nginx/Caddy) and local browsers to connect.
   - **Next.js Dashboard:** Published to host on `3000:3000`.
2. **Mosquitto Password & ACL Enforcement:**
   - Passwords stored in `/mosquitto/auth/passwd` as salted PBKDF2 hashes (`$7$101$...`). Plaintext passwords never exist on disk.
   - `backend_service` credentials: possesses global wildcard read/write access (`topic readwrite plants/#`).
   - Device credentials: strictly generated as `device_{plant_id}` with ACL limited to `topic readwrite plants/{plant_id}/#`. Edge devices cannot subscribe to or publish to topics of other plants.
3. **Browser MQTT Isolation Audit:**
   - Inspection of [`frontend/package.json`](file:///home/critic-coder/project/PlantPulse/frontend/package.json) confirms **no MQTT libraries** (such as `paho-mqtt` or `mqtt.js`) are installed.
   - Inspection of `frontend/context/WebSocketContext.tsx` confirms browser telemetry streaming operates exclusively over standard WebSockets (`ws://localhost:8000/ws/{plant_id}/telemetry`). Browsers never connect to Mosquitto.

---

## 2. Comprehensive Access Control Matrix

The matrix below was populated from **real measured HTTP status codes and WebSocket connection runs** on a live local stack with Clerk RSA keys configured:

### 2.1 Route Status Codes by Actor

| Route / Action | Method | Anonymous | Viewer Token (`plant_water_district_9`) | Signed-In User (No Role) | Plant Manager (`plant_water_district_9`) | Platform Admin (Clerk JWT) | Static `ADMIN_TOKEN` (Legacy) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Service Health** (`/health`) | GET | `200` | `200` | `200` | `200` | `200` | `200` |
| **Plant Catalog** (`/api/plants`) | GET | `200` | `200` | `200` | `200` | `200` | `200` |
| **Public Plant Definition** (`plant_demo_membrane`) | GET | `200` | `200` | `200` | `200` | `200` | `200` |
| **Public Plant WS Ticket** (`plant_demo_membrane`) | POST | `200` | `200` | `200` | `200` | `200` | `200` |
| **Public Latest Machines** (`plant_demo_membrane`) | GET | `200` | `200` | `200` | `200` | `200` | `200` |
| **Public Signal History** (`plant_demo_membrane`) | GET | `200` | `200` | `200` | `200` | `200` | `200` |
| **Public Units Traceability** (`plant_demo_membrane`) | GET | `200` | `200` | `200` | `200` | `200` | `200` |
| **Public Defect Rates** (`plant_demo_membrane`) | GET | `200` | `200` | `200` | `200` | `200` | `200` |
| **Protected Definition** (`plant_water_district_9`) | GET | `401` | `200` | `401` | `401` | `401` | `401` |
| **Protected WS Ticket** (`plant_water_district_9`) | POST | `401` | `200` | `401` | `401` | `401` | `401` |
| **Protected Latest Machines** (`plant_water_district_9`) | GET | `401` | `200` | `401` | `401` | `401` | `401` |
| **Protected Signal History** (`plant_water_district_9`) | GET | `401` | `200` | `401` | `401` | `401` | `401` |
| **Protected Queue Depths** (`plant_water_district_9`) | GET | `401` | `404`*(Unmounted module)* | `401` | `401` | `401` | `401` |
| **Admin Health Check** (`/api/admin/health`) | GET | `401` | `401` | `403` | `200` | `200` | `200` |
| **Admin Plant List** (`/api/admin/plants`) | GET | `401` | `401` | `403` | `200`*(Scoped)* | `200`*(All)* | `200`*(All)* |
| **Admin Plant Detail** (`/api/admin/plants/plant_water_district_9`) | GET | `401` | `401` | `403` | `200` | `200` | `200` |
| **Admin Plant Detail** (`/api/admin/plants/plant_demo_membrane`) | GET | `401` | `401` | `403` | `403`*(Wrong plant)* | `200` | `200` |
| **Admin Create Plant** (`POST /api/admin/plants`) | POST | `401` | `401` | `403` | `403` | `201` | `201` |
| **Admin Edit Plant (Own Plant)** (`PUT /api/admin/plants/{id}`) | PUT | `401` | `401` | `403` | `200`*(Own plant)* | `200` | `200` |
| **Admin Edit Plant (Cross-Plant)** (`PUT /api/admin/plants/plant_demo_membrane`) | PUT | `401` | `401` | `403` | `403`*(Wrong plant)* | `200` | `200` |
| **Admin Edit with Confirm Removals** (`PUT /api/admin/plants/{id}?confirm_removals=true`) | PUT | `401` | `401` | `403` | `403`*(Requires platform_admin)* | `200` | `200` |
| **Admin Rotate Creds** (`/api/admin/plants/{plant_id}/credentials/rotate`) | POST | `401` | `401` | `403` | `403` | `200` | `200` |
| **Admin Delete Plant** (`DELETE /api/admin/plants/{id}`) | DELETE | `401` | `401` | `403` | `403` | `200` | `200` |

### 2.2 WebSocket Ticket Lifecycle & Single-Use Verification

The WebSocket connection security was tested against a live running stack:

| Scenario | URL / Request Tested | Connection Handshake | WebSocket Close Code | Close Reason / Behavior |
| :--- | :--- | :---: | :---: | :--- |
| **Public Plant Anonymous WS** | `/ws/plant_demo_membrane/telemetry` | `101 Switching Protocols` | *(Open)* | Receives live broadcast streaming |
| **Protected Plant No Ticket** | `/ws/plant_water_district_9/telemetry` | `101 Switching Protocols` | `4401` | `"Unauthorized"` (immediately closed) |
| **Protected Plant Valid Ticket** | `/ws/plant_water_district_9/telemetry?ticket=L8R5...` | `101 Switching Protocols` | *(Open)* | Ticket consumed; live broadcast streams |
| **Reusing Consumed Ticket** | `/ws/plant_water_district_9/telemetry?ticket=L8R5...` | `101 Switching Protocols` | `4401` | `"Unauthorized"` (replay rejected) |
| **Invalid / Forged Ticket** | `/ws/plant_water_district_9/telemetry?ticket=fake_xyz` | `101 Switching Protocols` | `4401` | `"Unauthorized"` (rejected) |

### 2.3 View Access for Platform Admins and Plant Managers on Token Plants

A significant architectural dichotomy exists between the **administrative API** and the **public viewer API**:

#### The Behavior & Root Cause
When an authenticated `platform_admin` or `plant_manager` requests telemetry or machine states for a protected plant (such as `plant_water_district_9`, where `has_viewer_token=true`), public endpoints (`/api/plants/{plant_id}/machines/latest`, `/api/plants/{plant_id}/definition`, `/api/plants/{plant_id}/ws-ticket`) return **HTTP 401 Unauthorized**:
```bash
curl -s -H "Authorization: Bearer <clerk_admin_jwt>" http://127.0.0.1:8000/api/plants/plant_water_district_9/machines/latest
# Returns: {"detail":"Unauthorized"} (HTTP 401)
```

**Root Cause ([`main.py#L250-L285`](file:///home/critic-coder/project/PlantPulse/main.py#L250-L285)):**
The dependency `_verify_viewer_access` governs all public viewer endpoints. Its verification path is strictly hardcoded to the pre-shared secret string:
```python
token = authorization[7:].strip()
token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
if not hmac.compare_digest(token_hash, expected_hash):
    viewer_rate_limiter.record_failure(ip)
    raise HTTPException(status_code=401, detail="Unauthorized")
```
It computes `hashlib.sha256(token)` against `plant.viewer_token_hash`. It **does not inspect Clerk JWT claims** or verify whether the caller holds administrative privileges. Consequently, a `platform_admin` possessing global authority to mutate, rotate credentials, or delete `plant_water_district_9` is locked out from viewing its dashboard unless they separately supply the raw viewer token string (`district9_read_secret_token_889` [public demo value]).

#### Planned Unified RBAC Resolution
In Clerk PR 3 / unified RBAC:
1. `_verify_viewer_access` will evaluate authentication in a fallback sequence:
   - Check if caller presents a valid Clerk JWT via `verify_admin_user()`.
   - If user is `platform_admin`: grant immediate viewer access.
   - If user is `plant_manager` and `user.plant_id == requested_plant_id`: grant immediate viewer access.
   - Otherwise, evaluate `Authorization: Bearer <token>` against `plant.viewer_token_hash`.
2. This eliminates the operational paradox where authorized factory owners cannot inspect machine cards without entering a secondary demo passcode.

---

## 3. Actor Journeys & Implementation Status

### 3.1 Comprehensive Journeys Summary Table

| Journey | Actor / Persona | Primary Objective | Entry Point / Protocol | Authentication Mechanism | State Mutated | Implementation Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **J1: Demo Visitor** | Public Evaluator / Auditor | Explore live operational factory data without setup | Web UI (`:3000`) & WS (`/ws/plant_demo_membrane/telemetry`) | None (Anonymous) | In-memory WS connection tracker | **Completed** (Production) |
| **J2: Protected Plant Viewer** | Field Operator / Inspector | Access protected municipal booster telemetry | `#plant-selector` & `TokenEntryCard` | Pre-shared `viewer_token` string | In-memory viewer rate-limiter | **Completed** (Production) |
| **J3: Self-Service User** | Newly Registered User | Explore administrative / management capabilities | Header "Sign In" $\rightarrow$ `/admin` | Clerk JWT (No role claim assigned) | Clerk user directory record | **Partial** (UI pending-role screen needed) |
| **J4: Plant Manager** | Factory Production Lead | Provision factory line to first data ingestion | `/admin/plants/new` | Clerk JWT (`role="plant_manager"`) | Platform DB, Mosquitto ACL, Ingest registry | **Planned** (Gated by platform_admin role) |
| **J5: Platform Admin** | Infrastructure Superuser | Platform-wide plant governance & secret rotation | `/admin` | Clerk JWT (`role="platform_admin"`) | DB, Mosquitto ACL, Ingest Engine | **Completed** (Production) |
| **J6: IoT Edge Gateway** | Physical Hardware (PLC / Gateway) | Stream sensor metrics and state transitions | Mosquitto MQTT (`:1883` / `:8883`) | `device_{plant_id}` & PBKDF2 hash | PostgreSQL partitions, `machine_states` | **Production-Ready Contract** |
| **J7: Dynamic Verification** | Automation / QA Harness | Verify hot-reload, ACL enforcement & filtering | Admin REST API & Mosquitto CLI | Bearer static token & MQTT | DB partitions, Mosquitto ACL reloaded | **Live Stack Verified** |

### Journey 1: Visitor on the Demo Plant
- **Goal:** Explore live real-time factory operation without creating an account or entering tokens.
- **Step 1:** Loads `http://localhost:3000`. Dashboard queries `GET /api/plants` and defaults to `plant_demo_membrane`.  
  *Status:* Exists ([`app/page.tsx`](file:///home/critic-coder/project/PlantPulse/frontend/app/page.tsx)).
- **Step 2:** Calls `POST /api/plants/plant_demo_membrane/ws-ticket` (returns ticket) and opens WebSocket `/ws/plant_demo_membrane/telemetry`.  
  *Status:* Exists ([`context/WebSocketContext.tsx`](file:///home/critic-coder/project/PlantPulse/frontend/context/WebSocketContext.tsx)).
- **Step 3:** Observes live animated machines (Housing Molder 1, Coating Station 1, Assembly Machine 1). Clicks `hm_01` card to open inspector modal; queries history API for downsampled SVG chart.  
  *Status:* Exists ([`components/telemetry/StationInspectorModal.tsx`](file:///home/critic-coder/project/PlantPulse/frontend/components/telemetry/StationInspectorModal.tsx)).
- **Data Created:** None in database; WebSocket connection tracked in memory in `ConnectionManager._rooms`.

### Journey 2: Viewer Unlocking Protected Water Plant
- **Goal:** Access municipal water booster telemetry protected by access control.
- **Step 1:** Selects `District 9 Water Booster Station 🔒` in `#plant-selector`.  
  *Status:* Exists ([`components/layout/Header.tsx`](file:///home/critic-coder/project/PlantPulse/frontend/components/layout/Header.tsx)).
- **Step 2:** Dashboard checks `sessionStorage` for viewer token. None found $\rightarrow$ renders `TokenEntryCard`.  
  *Status:* Exists ([`components/telemetry/TokenEntryCard.tsx`](file:///home/critic-coder/project/PlantPulse/frontend/components/telemetry/TokenEntryCard.tsx)).
- **Step 3:** Operator enters token (`district9_read_secret_token_889` [public demo value]). Card validates token against `POST /api/plants/plant_water_district_9/ws-ticket`. Saves token to `sessionStorage` (`plantpulse_viewer_token_plant_water_district_9`).  
  *Status:* Exists.
- **Step 4:** WebSocket connects using minted ticket. Pump cards (Pumps 01–03) stream live flow rates and discharge pressures.  
  *Status:* Exists.
- **Error State:** Entering wrong token increments `viewer_rate_limiter`. After 5 failed attempts, IP receives `429 Too Many Requests` (60s lockout).

### Journey 3: New Signed-In User (Without an Assigned Role)
- **Goal:** Register an account via Clerk and explore administrative or management capabilities.
- **Step 1:** Clicks **"Sign In"** in header. Completes Clerk authentication (email/password, OAuth). Clerk session created.  
  *Status:* Exists ([`components/layout/Header.tsx`](file:///home/critic-coder/project/PlantPulse/frontend/components/layout/Header.tsx)).
- **Step 2:** Navigates to `/admin`.  
  *Status:* Gaps exist. Currently, [`frontend/app/admin/layout.tsx`](file:///home/critic-coder/project/PlantPulse/frontend/app/admin/layout.tsx) checks for static `ADMIN_TOKEN` instead of presenting a user status card. Calls to `/api/admin/*` return **403 Forbidden**.
- **Missing / Gap:** Needs dedicated "Access Pending: Account awaiting platform_admin role approval" empty state screen.

### Journey 4: Plant Manager Creating a Plant to First Data
- **Goal:** A production manager provisions an industrial plant, configures machine assets, starts the publisher, and verifies live streaming.
- **Step 1:** Authenticates via Clerk with `role="plant_manager"`.
- **Step 2:** Accesses `/admin/plants/new`.  
  *Status:* Gap: In `main.py` line 1819, `POST /api/admin/plants` enforces `require_platform_admin`. Plant managers currently receive 403 Forbidden. Self-service plant creation is specified in `docs/design/self-service-plants.md`.
- **Step 3:** Submits definition: `plant_solar_pack` with 3 machines. Backend generates Mosquitto credentials (`device_plant_solar_pack`) and triggers Mosquitto SIGHUP reload. Displays credentials in `AdminCredentialsModal`.  
  *Status:* Backend logic exists ([`main.py#L1825-L1880`](file:///home/critic-coder/project/PlantPulse/main.py#L1825-L1880)).
- **Step 4 (Empty State):** Navigates to `/` and selects `plant_solar_pack`. Zero telemetry exists in PostgreSQL. Machine cards show status `OFFLINE`, telemetry gauges show `—`. Header displays `"Awaiting Device Connection"`.
- **Step 5 (First Ingestion):** Gateway device connects and emits first telemetry JSON. `IngestEngine` validates envelope, inserts rows into `telemetry_values_pYYYY_MM_DD`, updates `machine_states` to `RUNNING`, and broadcasts via WebSockets. Dashboard updates to green in real time.

### Journey 5: Platform Administrator
- **Goal:** Superuser managing platform-wide tenants, credentials rotation, and broker synchronizations.
- **Step 1:** Authenticates with `role="platform_admin"`.
- **Step 2:** Accesses `/admin`. Sees full catalog of all registered plants.  
  *Status:* Exists ([`components/admin/AdminPlantInventory.tsx`](file:///home/critic-coder/project/PlantPulse/frontend/components/admin/AdminPlantInventory.tsx)).
- **Step 3:** Rotates credentials on compromised plant via `POST /api/admin/plants/{id}/credentials/rotate`. One-time new credentials shown in modal; broker SIGHUP reloaded.  
  *Status:* Exists ([`components/admin/AdminCredentialsModal.tsx`](file:///home/critic-coder/project/PlantPulse/frontend/components/admin/AdminCredentialsModal.tsx)).

### Journey 6: IoT / Edge Device Operator Onboarding Hardware
- **Goal:** Configure physical edge gateways (e.g., Advantech, Siemens IOT2050, Raspberry Pi CM4) to publish industrial metrics into PlantPulse.
- **Exact Connection Requirements for Real Devices:**
  - **MQTT Broker Host:** DNS hostname (e.g., `mqtt.plantpulse.example.com` or private VPC IP).
  - **MQTT Port:** `1883` (plaintext inside private IoT network) or `8883` (MQTTS with TLS 1.3 for internet traversal).
  - **Authentication:** Username `device_{plant_id}` (e.g., `device_plant_solar_pack`) and PBKDF2-hashed password copied from admin creation modal.
  - **MQTT Client ID:** Unique identifier e.g., `edge_{plant_id}_{mac_address}`.
  - **Topic Contract:**
    - Telemetry metrics: `plants/{plant_id}/assets/{machine_code}/telemetry`
    - Machine state updates: `plants/{plant_id}/assets/{machine_code}/state`
  - **Payload Schema (Verified in [`ingest.py#L290-L375`](file:///home/critic-coder/project/PlantPulse/ingest.py#L290-L375)):**
    ```json
    {
      "schema_version": "1.0",
      "message_id": "018d3a12-789a-7c9b-90f1-123456789abc",
      "plant_id": "plant_solar_pack",
      "asset_id": "molding_press_01",
      "device_timestamp": "2026-10-22T14:30:00.000Z",
      "payload_type": "telemetry",
      "payload": {
        "status": "RUNNING",
        "sub_status": "NORMAL_CYCLE",
        "metrics": {
          "hydraulic_pressure_bar": 142.5,
          "oil_temperature_c": 48.2
        }
      }
    }
    ```

### Journey 7: Live Stack Verification: Dynamic Plant Creation, ACL Enforcement & Ingest Hot-Reload
A live end-to-end journey test was executed against the running Docker Compose stack to verify dynamic provisioning, Mosquitto ACL scoping, signal filtering, and zero-downtime schema updates:

1. **Plant Provisioning (`POST /api/admin/plants`):**
   - Created test tenant `plant_test_journey` with 1 machine (`press_01`) and 2 signals (`pressure_bar`, `temp_c`).
   - Admin API returned HTTP `201 Created` with `broker_reloaded: true`.
   - Captured one-time device credentials:
     - Username: `device_plant_test_journey`
     - Password: `<one-time-password>`
   - Broker `/mosquitto/auth/acl.conf` was dynamically written with `user device_plant_test_journey` / `topic readwrite plants/plant_test_journey/#` and reloaded via `SIGHUP`.

2. **Step (a): Valid Telemetry Publication:**
   - Published telemetry conforming to `ingest.py` schema via internal broker CLI:
     ```bash
     docker compose exec broker mosquitto_pub -u device_plant_test_journey -P "..." \
       -t "plants/plant_test_journey/assets/press_01/telemetry" \
       -m '{"schema_version":"1.0","plant_id":"plant_test_journey","asset_id":"press_01","device_timestamp":"2026-10-22T11:17:39Z","message_id":"journey-test-msg-001","payload":{"metrics":{"pressure_bar":15.75,"temp_c":52.3}}}'
     ```
   - **Database Ingestion:** Verified 2 rows inserted in `telemetry_values` (`pressure_bar` = 15.75, `temp_c` = 52.3).
   - **Machine State:** `GET /api/plants/plant_test_journey/machines/latest` returned `press_01` with both signals.
   - **Plant Overview:** `GET /api/plants/plant_test_journey/definition` returned HTTP `200` with the complete plant definition.

3. **Step (b): Undeclared Signal Handling:**
   - Emitted message `journey-test-msg-002-undeclared` containing valid metric `pressure_bar: 18.0` and undeclared metric `vibration: 8.4`.
   - `IngestEngine` evaluated `valid_signal_codes = {'pressure_bar', 'temp_c'}`.
   - Filter check triggered `continue` for `vibration`. Exactly 1 row (`pressure_bar`) was inserted into `telemetry_values`; zero rows were stored for `vibration`.

4. **Step (c): Cross-Plant Topic Publication (ACL Denial):**
   - Attempted publication using `device_plant_test_journey` credentials to another plant's topic: `plants/plant_demo_membrane/assets/hm_01/telemetry`.
   - Mosquitto ACL denied the publish:
     - Standard MQTT v3.1.1: Packet dropped by broker according to spec.
     - MQTT v5 (`-V 5 -q 1`): Broker explicitly returned `Warning: Publish 1 failed: Not authorized.`
   - Database verification confirmed **0 rows inserted** for `plant_demo_membrane`.

5. **Step (d): Schema Update & Ingest Hot-Reload (`PUT /api/admin/plants/{id}`):**
   - Called `PUT /api/admin/plants/plant_test_journey` adding a 3rd signal: `rpm` (Motor Speed, unit `rpm`).
   - Received HTTP `200 OK`. `main.py` invoked `ingest_engine.update_plant(plant)` in memory.
   - Published telemetry message with `rpm: 1450.0`, `pressure_bar: 22.1`, `temp_c: 48.0`.
   - Verified that `IngestEngine` **immediately accepted and stored all 3 signals without restarting the container or worker**. `GET /api/plants/plant_test_journey/machines/latest` reported `rpm` = 1450.0.

6. **Cleanup:**
   - Called `DELETE /api/admin/plants/plant_test_journey`.
   - API returned HTTP `200 OK` (`{"status": "deleted", "broker_reloaded": true}`).
   - Verified database cascade deletion of telemetry and broker ACL reload removing `device_plant_test_journey`. Subsequent queries to `/api/plants/plant_test_journey/definition` return `404 Not Found`.

---

## 4. Architectural Gaps & Trade-off Analysis

### 4.1 View Access for People Other Than the Owner
*Problem:* Today, plant viewing is either globally public (no viewer token) or locked behind a single shared pre-shared secret string (`viewer_token`) shared among all operators.

| Approach | Implementation Mechanics | Security & Operational Trade-offs | Recommendation |
| :--- | :--- | :--- | :--- |
| **1. Shared Viewer Token (Current)** | Single token string stored in DB `viewer_token_hash`. Distributed to viewers via chat/docs. | **Pros:** Zero account required for viewers; rapid evaluation.<br>**Cons:** Zero revocation granularity; token sharing cannot be audited or revoked per-user. | Keep for public evaluation / demo plants only. |
| **2. Clerk Organization Membership** | Map `plant_id` to Clerk Organization. Users join organization as `org:viewer` or `org:admin`. | **Pros:** Individual user identity, revokable per user, enterprise SSO/SAML support.<br>**Cons:** Requires every floor operator to have an email account in Clerk. | **Recommended for Production.** |
| **3. Ephemeral Time-Bound Invite Links** | Backend generates signed HMAC tokens: `/invite?token=...` valid for 24 hours. | **Pros:** No permanent shared password; easy onboarding for third-party auditors.<br>**Cons:** Requires extra database table or stateless HMAC signing service. | Good secondary option for temporary contractor access. |

### 4.2 Real Device Connectivity: Edge to Broker Options

| Architecture Option | Description | Trade-offs | Verdict |
| :--- | :--- | :--- | :--- |
| **Option A: MQTT over TLS (Port 8883)** | Mosquitto listens on port 8883 with Let's Encrypt TLS certificate. Edge devices connect directly over internet. | **Pros:** Standard industrial IoT protocol; persistent keepalive; low bandwidth.<br>**Cons:** Requires cloud host with open public port 8883 and static IP. | **Best Match for Dedicated VM Deployments.** |
| **Option B: Hosted Managed Broker** | Use HiveMQ Cloud Serverless, EMQX Cloud, or AWS IoT Core. | **Pros:** Zero broker maintenance; built-in DDoS defense.<br>**Cons:** HiveMQ Serverless retiring 2026-12-31; connection/message caps; monthly subscription costs. | High risk on free tiers. |
| **Option C: HTTPS Telemetry Ingest API** | Add `POST /api/plants/{id}/ingest` authenticated via per-device API token. Backend enqueues rows directly. | **Pros:** Works over standard HTTPS (port 443); bypasses corporate firewall MQTT blocking; easy curl debugging.<br>**Cons:** Higher HTTP header overhead per reading (500B HTTP vs 2B MQTT header). | **Recommended as Alternative Ingestion Path.** |

### 4.3 New Plant Zero-Data Empty State
*Problem:* When a plant is created, no telemetry exists until physical devices connect. Current UI displays empty graphs with no guidance.

- **Proposed Solution:**
  1. Add an empty state banner on the overview page: `"Plant created successfully. Awaiting first telemetry packet on topic plants/{plant_id}/assets/{machine_code}/telemetry."`
  2. Provide a one-click **"Copy Test mosquitto_pub Command"** pre-filled with the plant's generated device credentials and sample JSON payload so engineers can immediately verify pipeline connectivity before wiring physical PLCs.

---

## 5. Open Questions for Student Discussion

1. **HTTP Ingestion vs Pure MQTT:** Should PlantPulse support an HTTP `POST /api/plants/{plant_id}/telemetry` endpoint alongside MQTT to simplify edge devices that lack native MQTT client libraries?
2. **Viewer Token Deprecation:** Should per-plant `viewer_token` pre-shared strings be retired in favor of Clerk Organization-based viewer roles, or retained for frictionless public demonstration?
3. **Machine State Timeout:** If an edge device stops publishing without emitting an explicit `OFFLINE` state message, how long should the backend wait before automatically transitioning the machine state to `STALE` or `OFFLINE` (e.g., 3x expected publish interval)?
