# PlantPulse 2-Minute End-to-End Demonstration Script

**Target Document:** `docs/demo-script.md`  
**Duration:** Exactly 2 minutes (120 seconds)  
**Prerequisites:** Docker, Docker Compose, modern web browser, terminal.

---

## 1. Preparation & Environment Setup

### 1.1 Environment File Configuration (`.env`)
Ensure your `.env` contains the required Clerk and demo configuration:

```bash
# Clerk Configuration (required for self-service sign-in & portal):
CLERK_ISSUER=https://<your-subdomain>.clerk.accounts.dev
CLERK_PEM_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
CLERK_AUTHORIZED_PARTIES=http://localhost:3000
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...

# Optional Admin & Demo Hints
MOUNT_ADMIN_ENDPOINTS=true
ADMIN_TOKEN=demo_admin_secret_token_2026_32char_len  # public demo value (32+ chars recommended)
DEMO_HINTS=true
NEXT_PUBLIC_DEMO_HINTS=true
```

### 1.2 Start Services & Natural Fault Pre-Warming
Run the following commands in your terminal:

```bash
cd ~/project/PlantPulse

# 1. Start clean multi-container stack
docker compose down -v
docker compose up -d

# 2. Verify containers are healthy
docker compose ps
# Expected services:
#   plantpulse-api-1 (FastAPI on 127.0.0.1:8000)
#   plantpulse-broker-1 (Mosquitto internal :1883)
#   plantpulse-postgres-1 (PostgreSQL 16 on :5432)
#   plantpulse-dashboard-1 (Next.js 16 on :3000)
#   plantpulse-simulator-1 (Simulator runner)
```

> [!IMPORTANT]
> **Pre-Warming Lead Time & Mandatory Dry-Run:**
> Housing Molder 1 (`hm_01`) on `plant_demo_membrane` accumulates natural vibration drift and faults after an average of **160 seconds** of simulator runtime (measured range: 155–170 s), recovering automatically 45 seconds later (measured range: 200–215 s to `RUNNING`).
> In this 2-minute video, Shot 4 (Fault & Recovery) begins at **video time 1:15 (75 seconds elapsed)**.
> **Start the Docker stack and open `http://localhost:3000` exactly 85 seconds before video recording begins** ($160\text{ s} - 75\text{ s} = 85\text{ s}$). Connecting the browser starts the API heartbeat and wakes the simulator watchdog.
> Because stochastic drift varies slightly, presenters must execute one unrecorded dry-run before recording to verify host timing within $\pm 10$ seconds.

Have two windows arranged on screen:
1. **Web Browser** open to `http://localhost:3000`.
2. **Terminal Window** sized for running shell commands.

---

## 2. Timed Shot List & Voiceover (120 Seconds Total)

### Shot 1: Sign In & Navigate to "My plants" (0:00 – 0:25)
- **URL:** [`http://localhost:3000`](http://localhost:3000) $\to$ [`http://localhost:3000/my-plants`](http://localhost:3000/my-plants)
- **Action:**
  1. In the top navigation header, click the **"Sign In"** button (rendered via Clerk `<SignInButton mode="modal">`).
  2. Complete the authentication modal.
  3. The header updates to show the authenticated user profile and a **"My plants"** navigation link.
  4. Click the **"My plants"** link.
- **Visual:**
  - Browser navigates to `/my-plants`.
  - Top header banner displays **"🌱 My Manufacturing Plants"** with subtitle.
  - Quota indicator pill shows **"0 of 3 plants"** (or current usage bounded by personal quota).
  - Main area displays facility cards or empty state card: **"No facilities registered yet"** with the **"+ Register New Plant"** button.
- **Spoken Sentence:**  
  > *"PlantPulse provides a self-service industrial management portal where authenticated operators can register private manufacturing plants, provision isolated edge credentials, and monitor telemetry."*

---

### Shot 2: Register Personal Plant & Capture Credentials (0:25 – 0:50)
- **URL:** [`http://localhost:3000/my-plants`](http://localhost:3000/my-plants)
- **Action:**
  1. Click the **"+ Register New Plant"** button in the header banner.
  2. The creation form accordion opens with heading **"REGISTER PERSONAL FACILITY"**.
  3. Enter facility metadata:
     - **Plant Name:** `Solar Battery Storage`
     - **Plant ID:** `plant_solar_battery`
     - (Keep default topology: Area `production` / Machine `pack_tester_01` / Signal `cell_voltage_v`, Unit `V`, DataType `float`).
  4. Scroll to bottom and click **"Create Plant & Generate Credentials →"**.
  5. The `AdminCredentialsModal` appears titled **"One-Time Initial Device Credentials & Viewer Token"**.
  6. Point out generated device username `device_plant_solar_battery`, secure random password, and viewer token (`viewer_...`).
  7. Click **"Copy All Credentials"** (button feedback toggles to green **"Copied to Clipboard!"**).
  8. Click **"I have saved credentials & Close"**.
- **Visual:** The new plant appears in the left facility list as an active card labeled **"Solar Battery Storage"** with badge **"OWNER"** and **"🔒 Private"**.
- **Spoken Sentence:**  
  > *"Registering a facility automatically provisions dedicated Mosquitto MQTT credentials and a viewer token, compiling broker access control lists and persisting cryptographic hashes to PostgreSQL with fail-closed validation."*

---

### Shot 3: Connect Device via `mosquitto_pub` & Open Dashboard (0:50 – 1:15)
- **URL:** [`http://localhost:3000/my-plants`](http://localhost:3000/my-plants) $\to$ Terminal $\to$ [`http://localhost:3000`](http://localhost:3000)
- **Action:**
  1. In the right panel of `/my-plants`, inspect the **"CONNECT A DEVICE"** card.
  2. Highlight the **Internal Broker Network Notice**: port 1883 is internal to the Docker network, so external devices cannot connect directly without network ingress.
  3. Point to the Ingest Topic: `plants/plant_solar_battery/assets/pack_tester_01/telemetry`.
  4. Click **"Copy Command"** to copy the pre-formatted CLI publisher command with `<password>` placeholder.
  5. In the terminal window, run the command substituting the copied password:
     ```bash
     docker compose exec broker mosquitto_pub \
       -u device_plant_solar_battery \
       -P '<password>' \
       -t 'plants/plant_solar_battery/assets/pack_tester_01/telemetry' \
       -m '{"schema_version":"1.0","plant_id":"plant_solar_battery","asset_id":"pack_tester_01","device_timestamp":"'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'","message_id":"msg-001","payload":{"status":"RUNNING","metrics":{"cell_voltage_v":3.72}}}'
     ```
  6. Return to the browser and click the blue **"📊 Open dashboard"** button on the plant detail card.
- **Visual:**
  - Browser navigates to `/` with `plant_solar_battery` selected in `#plant-selector`.
  - Because the authenticated user is the plant owner, the backend verifies the Clerk JWT in `verify_plant_viewer` ([`main.py:299-327`](main.py#L299-L327)), seamlessly bypassing the manual viewer token entry modal.
  - The live overview renders machine card `pack_tester_01` in green **"RUNNING"** status showing `cell_voltage_v: 3.72 V`.
- **Spoken Sentence:**  
  > *"Edge devices publish strictly formatted JSON envelopes to the internal broker, which the backend validates and ingests into time-partitioned tables while granting instant, seamless dashboard access to the plant owner."*

---

### Shot 4: Equipment Fault & Automatic Recovery on `hm_01` (1:15 – 1:40)
- **URL:** [`http://localhost:3000`](http://localhost:3000)
- **Action:**
  1. In the header plant selector dropdown (`#plant-selector`), switch to **`Membrane Production Facility`** (`plant_demo_membrane`).
  2. The overview renders the 11-machine manufacturing line. Point your mouse to Housing Molder 1 (**`hm_01`**).
  3. At video time 1:15 (stack elapsed 160s with 85s pre-warm), `hm_01` naturally crosses the 7.0 mm/s vibration threshold.
  4. The card status flips to red with badge **"FAULT"** and sub-status **"HIGH_VIBRATION"**, incrementing the active alarm counter.
  5. The simulator's automated 45-second maintenance cycle executes, resetting vibration to 0.2 and returning `hm_01` to green **"RUNNING"**, automatically clearing the alarm.
- **Visual:** Instantaneous WebSocket state transition and alarm lifecycle without manual page refreshes.
- **Spoken Sentence:**  
  > *"When equipment experiences anomalies—such as this vibration spike on Housing Molder 1—the platform broadcasts live alarm states over WebSockets and tracks equipment through automatic maintenance recovery."*

---

### Shot 5: Station Inspector Downsampled History Graph on `hm_01` (1:40 – 2:00)
- **URL:** [`http://localhost:3000`](http://localhost:3000)
- **Action:**
  1. Click directly on the machine card for **`hm_01`** (*"Housing Molder 1"*).
  2. The `StationInspectorModal` dialog opens.
  3. Point to the signal selector tabs (*"Vibration"*, *"Mold Temperature"*), the time-range preset buttons (**`1h`**, **`6h`**, **`12h`**, **`24h`**), and the Min, Avg, Max statistics.
  4. Hover over data points on the SVG time-series chart.
  5. Explain the API query contract: `GET /api/plants/plant_demo_membrane/machines/hm_01/signals/vibration/history?start=...&end=...&points=300`. The frontend converts range buttons into explicit ISO-8601 UTC timestamps, and PostgreSQL aggregates buckets via `date_bin` with client-side gap detection.
- **Visual:** High-resolution time-series chart rendering downsampled historical telemetry retrieved from PostgreSQL daily partition tables with zero rendering stutter.
- **Spoken Sentence:**  
  > *"The station inspector executes high-performance downsampled SQL queries over daily PostgreSQL partitions, delivering instant trend visualization and gap detection across any historical time window."*

---

## 3. Quick Reference Card for Presenter

| Timing | Scene & Topic | Exact URL / Route | Key UI Elements & Labels | Terminal Command / Action |
| :--- | :--- | :--- | :--- | :--- |
| **0:00–0:25** | Sign In & Access Portal | `http://localhost:3000`<br>$\to$ `/my-plants` | Header button: `"Sign In"`<br>Header link: `"My plants"`<br>Title: `"🌱 My Manufacturing Plants"`<br>Quota: `"0 of 3 plants"` | Pre-req: Start stack 85s early (dry-run verified) |
| **0:25–0:50** | Create Plant & Copy Secrets | `/my-plants` | Button: `"+ Register New Plant"`<br>Heading: `"REGISTER PERSONAL FACILITY"`<br>Button: `"Create Plant & Generate Credentials →"`<br>Modal: `"One-Time Initial Device Credentials & Viewer Token"`<br>Button: `"Copy All Credentials"` | Inputs: Name `Solar Battery Storage`, ID `plant_solar_battery` |
| **0:50–1:15** | Connect Device & Open Dashboard | `/my-plants`<br>$\to$ Terminal<br>$\to$ `/` | Card: `"CONNECT A DEVICE"`<br>Topic: `plants/plant_solar_battery/assets/pack_tester_01/telemetry`<br>Button: `"Copy Command"`<br>Button: `"📊 Open dashboard"` | `docker compose exec broker mosquitto_pub -u device_plant_solar_battery -P '<password>' -t 'plants/plant_solar_battery/assets/pack_tester_01/telemetry' -m '{"schema_version":"1.0",...}'` |
| **1:15–1:40** | Natural Fault & Auto-Recovery | `http://localhost:3000` | Selector: `Membrane Production Facility`<br>Card: `hm_01` flips to red `"FAULT"` badge with `"HIGH_VIBRATION"`, then recovers to green `"RUNNING"` | *(Hands-free; pre-warmed stack drifts naturally across threshold)* |
| **1:40–2:00** | Downsampled History Graph | `http://localhost:3000` | Card: `hm_01`<br>Modal: `StationInspectorModal`<br>Buttons: `1h`, `6h`, `12h`, `24h`<br>Contract: `?start=...&end=...&points=300` | Inspect SVG trend line and Min/Avg/Max stats |
