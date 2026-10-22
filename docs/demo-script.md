# PlantPulse 2-Minute End-to-End Video Demonstration Script

**Target Document:** `docs/demo-script.md`  
**Branch:** `docs/final-phase`  
**Duration:** Exactly 2 minutes (120 seconds)  
**Prerequisites:** Docker, Docker Compose, modern web browser (Chrome/Firefox/Edge).  

---

## 1. Preparation & Environment Setup

### 1.1 Environment File Configuration (`.env`)
In [`.env.example`](file:///home/critic-coder/project/PlantPulse/.env.example#L33-L36), administrative endpoints are unmounted by default (`MOUNT_ADMIN_ENDPOINTS=false`) and `ADMIN_TOKEN` is blank. Before recording, ensure your `.env` contains:

```bash
# Required for Shot 5 (Admin Portal):
MOUNT_ADMIN_ENDPOINTS=true
ADMIN_TOKEN=demo_admin_secret_token_2026
DEMO_HINTS=true
NEXT_PUBLIC_DEMO_HINTS=true
```

*(Note: When `ADMIN_TOKEN` is retired in favor of Clerk-only RBAC, the admin login step will use Clerk authentication with a `platform_admin` user claim rather than the static token card).*

### 1.2 Start Services
Run the following commands in your terminal:

```bash
cd ~/project/PlantPulse

# 1. Start clean multi-container stack
docker compose down -v
docker compose up -d

# 2. Verify containers are running
docker compose ps
# Expected healthy containers:
#   plantpulse-api-1 (FastAPI on :8000)
#   plantpulse-broker-1 (Mosquitto on :1883)
#   plantpulse-postgres-1 (PostgreSQL 16 on :5432)
#   plantpulse-dashboard-1 (Next.js 16 on :3000)
#   plantpulse-simulator-1 (Simulator runner)
```

Have two windows arranged on screen:
1. **Web Browser** open to `http://localhost:3000`.
2. **Terminal Window** sized for running shell commands.

---

## 2. Timed Shot List & Voiceover

### Shot 1: Startup & Live Telemetry Streaming (0:00 – 0:25)
- **URL:** [`http://localhost:3000`](http://localhost:3000)
- **Visual:** Browser displays the **Live Overview** page for the default plant: `plant_demo_membrane` (*"Membrane Production Facility"*). In the upper right header, point to the green connection pill showing **"Live Telemetry"** and the real-time clock. Point out the machine cards across the stages (*Housing Molder 1*, *Coating Station 1*, *Assembly Machine 1*) updating gauges and cycle counters as telemetry arrives over WebSockets.
- **Action:** Mouse hovers over active telemetry values (mold temperature, hydraulic pressure) updating in real time.
- **Spoken Sentence:**  
  > *"PlantPulse starts up with Docker Compose, immediately connecting to the local Mosquitto MQTT broker and streaming real-time machine telemetry over WebSockets to this live Next.js dashboard."*

---

### Shot 2: Protected Plant Access Control & Token Unlock (0:25 – 0:45)
- **URL:** [`http://localhost:3000`](http://localhost:3000)
- **Action:**
  1. Click the plant selector dropdown in the navigation header (`#plant-selector`).
  2. Select **`District 9 Water Booster Station 🔒`** (the exact registered display name in [`plants/plant_water_district_9.json`](file:///home/critic-coder/project/PlantPulse/plants/plant_water_district_9.json)).
  3. The page transitions to display the `TokenEntryCard` with heading **"Viewer Authentication Required"**.
  4. Point to the demo hint card: `Evaluation Hint: Use demo token district9_read_secret_token_889`.
  5. Click the **"Fill Demo Token"** shortcut button (or paste `district9_read_secret_token_889`).
  6. Click the amber **"Authenticate & View →"** button.
- **Visual:** The token card resolves, the plant status changes to authenticated, and live municipal water pump telemetry begins streaming in real time.
- **Spoken Sentence:**  
  > *"PlantPulse enforces per-plant access control, allowing operators to unlock protected industrial facilities like this water booster station using scoped viewer authentication tokens."*

---

### Shot 3: Downsampled Signal History Graph (0:45 – 1:05)
- **URL:** [`http://localhost:3000`](http://localhost:3000)
- **Action:**
  1. Use the plant selector dropdown to switch back to **`Membrane Production Facility`**.
  2. On the floor overview, click directly on the machine card for **`hm_01`** (*"Housing Molder 1"*).
  3. The `StationInspectorModal` opens.
  4. Point to the signal selection tabs (*"Mold Temperature"*, *"Vibration"*), the time-range preset buttons (**`1h`**, **`6h`**, **`12h`**, **`24h`**), and the Min, Avg, Max statistics.
  5. Hover over data points on the SVG signal history chart.
- **Visual:** High-resolution time-series chart rendering downsampled historical telemetry retrieved from PostgreSQL daily partition tables using SQL `date_bin` interval bucket aggregation.
- **Spoken Sentence:**  
  > *"Clicking any machine opens the station inspector, rendering downsampled historical time-series graphs from PostgreSQL partitioned tables to analyze sensor trends without client-side lag."*

---

### Shot 4: Equipment Fault & Automatic Recovery on `hm_01` (1:05 – 1:35)

#### Fault Execution Choice & Measured Timing Justification
- **Natural Simulation Measurement:** In `demo/simulator/simulator.py`, `hm_01` starts at vibration 6.3 with a fault threshold of 7.0 and a drift scale of 0.1. Running under default parameters, `hm_01` requires **150 ticks (~2.5 minutes)** to naturally drift into a fault, followed by a **90-second repair delay** before recovering (~4 minutes total).
- **Justification for Manual Command:** Because the video demo is strictly constrained to **2 minutes (120 seconds)**, waiting 4 minutes for a natural fault and recovery cycle would exceed the entire video. Therefore, injecting an instant state transition via `mosquitto_pub` is recommended for live demonstration. *(Alternative zero-command option: set `SIMULATOR_DRIFT_SCALE=0.8` or `SIMULATOR_REPAIR_DELAY_SECONDS=10` in `.env` if hands-free natural fault is required).*

- **URL:** [`http://localhost:3000`](http://localhost:3000) (Close inspector modal)
- **Action (Terminal Injection):**
  ```bash
  docker compose exec broker mosquitto_pub \
    -u device_plant_demo_membrane \
    -P membrane_device_secret_token_456 \
    -t "plants/plant_demo_membrane/assets/hm_01/state" \
    -m '{"schema_version":"1.0","message_id":"demo_fault_inject","plant_id":"plant_demo_membrane","asset_id":"hm_01","device_timestamp":"2026-10-22T12:00:00Z","payload_type":"state_change","payload":{"previous_status":"RUNNING","status":"FAULT","sub_status":"HIGH_VIBRATION"}}'
  ```
- **Visual (Browser):** The `hm_01` machine card instantly flashes red with status badge **"FAULT"** and sub-status **"HIGH_VIBRATION"**. The active alarms count increments.
- **Action (Terminal Recovery):**
  ```bash
  docker compose exec broker mosquitto_pub \
    -u device_plant_demo_membrane \
    -P membrane_device_secret_token_456 \
    -t "plants/plant_demo_membrane/assets/hm_01/state" \
    -m '{"schema_version":"1.0","message_id":"demo_recover_inject","plant_id":"plant_demo_membrane","asset_id":"hm_01","device_timestamp":"2026-10-22T12:01:00Z","payload_type":"state_change","payload":{"previous_status":"FAULT","status":"RUNNING","sub_status":null}}'
  ```
- **Visual (Browser):** The card transitions smoothly back to green **"RUNNING"**, clearing the active alarm.
- **Spoken Sentence:**  
  > *"When equipment encounters anomalies—such as an automated vibration spike or injected fault on Housing Molder 1—the platform broadcasts instant state changes over WebSockets and tracks equipment recovery."*

---

### Shot 5: Admin Portal & Dynamic Plant Provisioning (1:35 – 2:00)
- **URL:** Navigate browser to [`http://localhost:3000/admin`](http://localhost:3000/admin)
- **Action:**
  1. In the `AdminTokenEntryCard`, enter the administrative key configured in your `.env` (`demo_admin_secret_token_2026`) and click **"Authenticate as Admin →"**.
  2. The registered plant inventory appears. Click the blue **`+ Register New Plant`** button in the header (navigates to [`/admin/plants/new`](http://localhost:3000/admin/plants/new)).
  3. Fill in basic details:
     - **Plant ID:** `plant_solar_battery`
     - **Plant Name:** `Advanced Battery Pack Facility`
  4. Scroll to the bottom and click **"Create Plant & Generate Credentials →"**.
  5. The `AdminCredentialsModal` appears with title **"One-Time Initial Device Credentials"** showing generated username `device_plant_solar_battery` and secret password.
  6. Click **"Copy All Credentials"** (shows green checkmark) and dismiss with **"I have saved credentials & Close"**.
- **Visual:** The new plant appears in the registered plant list with its generated credentials securely synchronized to Mosquitto ACLs.
- **Spoken Sentence:**  
  > *"Finally, administrators can dynamically provision entirely new multi-machine plants through the admin portal, automatically configuring Mosquitto credentials, topics, and access control lists with fail-closed input validation."*

---

## 3. Quick Reference Card for Presenter

| Timing | Scene & Topic | Exact URL / Route | Key UI Elements & Labels | Terminal Command |
| :--- | :--- | :--- | :--- | :--- |
| **0:00–0:25** | Startup & Live Telemetry | `http://localhost:3000` | Header: `"Live Telemetry"`, Machine Cards: `hm_01`, `cf_01` | `docker compose up -d` |
| **0:25–0:45** | Protected Water Plant Unlock | `http://localhost:3000` | `#plant-selector`: `District 9 Water Booster Station 🔒`<br>Card: `TokenEntryCard`<br>Button: `"Fill Demo Token"` & `"Authenticate & View →"` | *(None)* |
| **0:45–1:05** | Downsampled History Graph | `http://localhost:3000` | Card: `hm_01`<br>Modal: `StationInspectorModal`<br>Buttons: `1h`, `6h`, `12h`, `24h`<br>Algorithm: SQL `date_bin` aggregation | *(None)* |
| **1:05–1:35** | Fault Injection & Recovery | `http://localhost:3000` | Card: `hm_01` flips to red `"FAULT"` badge with `"HIGH_VIBRATION"`, then returns to `"RUNNING"` | `mosquitto_pub` state messages (Shot 4 script; natural fault takes 2.5 min) |
| **1:35–2:00** | Admin Portal Plant Creation | `http://localhost:3000/admin`<br>`/admin/plants/new` | Button: `"+ Register New Plant"`<br>Button: `"Create Plant & Generate Credentials →"`<br>Modal: `"One-Time Initial Device Credentials"` | Pre-req: `MOUNT_ADMIN_ENDPOINTS=true` and `ADMIN_TOKEN` |
