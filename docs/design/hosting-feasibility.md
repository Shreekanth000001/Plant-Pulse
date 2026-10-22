# Design Document: Cloud Hosting Feasibility & Free-Tier Architecture for PlantPulse

**Target Document:** `docs/design/hosting-feasibility.md`  
**Branch:** `docs/final-phase`  
**Status:** Feasibility Research & Architectural Analysis  
**Date:** 2026-10-22  

---

## 1. Executive Summary

PlantPulse is packaged as a multi-container Docker Compose application consisting of five interdependent services:
1. `api`: FastAPI backend with an internal async MQTT ingest engine, WebSockets, and in-memory caches.
2. `broker`: Eclipse Mosquitto 2.0 MQTT broker with file-based dynamic credentials (`passwd`) and ACLs (`acl.conf`).
3. `postgres`: PostgreSQL 16 database with transactional migrations (Alembic) and partitioned history storage.
4. `dashboard`: Next.js 16 (App Router) web interface with Turbopack and Clerk authentication.
5. `simulator`: Python factory simulation generating real-time signals (11 machines across 2 plants).

Deploying PlantPulse to cloud hosting requires analyzing whether modern **free tiers** can sustain long-lived stateful protocols (WebSockets, continuous outbound MQTT subscriptions, high-frequency database writes) or whether platform architectural assumptions (shared PID namespaces, in-memory stores, single uvicorn worker) break under distributed or serverless cloud environments.

---

## 2. Official Documentation Sources, Quotes & Retrieval Dates

All provider specifications cited in this document were retrieved directly from official provider documentation on **2026-10-22**. Every claim links directly to its official source URL:

| Category | Provider & Tier | Official Source & URL | Retrieval Date | Exact Quote (< 15 words) |
| :--- | :--- | :--- | :--- | :--- |
| **Python Host** | Oracle Cloud (OCI Always Free) | [OCI Free Tier Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) | 2026-10-22 (page dated 2026-06-12) | *"All tenancies get the first 1,500 OCPU hours and 9,000 GB hours"* <br> *"Idle Always Free compute instances may be reclaimed by Oracle."* |
| **Python Host** | Koyeb (Free Instance) | [Koyeb Pricing](https://www.koyeb.com/pricing) <br> [Koyeb Scale to Zero](https://www.koyeb.com/docs/run-and-scale/scale-to-zero) | 2026-10-22 | *"The Koyeb Free Instance automatically scales down to zero"* <br> *"held connection (e.g. websocket or HTTP/2 stream) from the Internet"* |
| **Python Host** | Render (Free Web Service) | [Render Free Plans](https://render.com/docs/free) | 2026-10-22 | *"spin down after 15 minutes of inactivity"* |
| **Python Host** | PythonAnywhere (Beginner) | [PythonAnywhere Account Types](https://help.pythonanywhere.com/pages/AccountTypes/) <br> [PythonAnywhere Allowlist](https://help.pythonanywhere.com/pages/API-allowlist/) | 2026-10-22 | *"Free accounts have restricted outbound internet access"* |
| **Hosted MQTT** | HiveMQ Cloud (Serverless) | [HiveMQ Cloud Serverless End of Life](https://docs.hivemq.com/hivemq-cloud/serverless-end-of-life.html) | 2026-10-22 | *"HiveMQ retires the HiveMQ Cloud Serverless plan on 2026-12-31."* |
| **Hosted MQTT** | EMQX Cloud (Serverless) | [EMQX Serverless Quotas](https://docs.emqx.com/en/cloud/latest/deployments/serverless.html) | 2026-10-22 | *"up to 1,000 concurrent connections, 1 GB data transfer per month"* |
| **Hosted Postgres** | Supabase (Free Plan) | [Supabase Free Plan & Billing](https://supabase.com/docs/guides/platform/org-based-billing#free-plan) <br> [Supabase Pausing](https://supabase.com/docs/guides/platform/pausing) | 2026-10-22 | *"500 MB database size limit per project"* <br> *"Projects are paused after 7 days of inactivity"* |
| **Hosted Postgres** | Neon (Free Plan) | [Neon Free Plan Documentation](https://neon.tech/docs/introduction/plans) | 2026-10-22 | *"Free plan users get 1 GB of Postgres storage per project"* <br> *"100 CU-hours/project/month"* |

---

## 3. Provider Reconciliations & Analysis

### 3.1 Neon Storage Limit Reconciliation (0.5 GiB vs Official 1 GB)
- **Current Official Documentation (retrieved 2026-10-22):** The official Neon documentation ([Neon Plans](https://neon.tech/docs/introduction/plans)) specifies: *"Free plan users get 1 GB of Postgres storage per project, up to 20 GB total across all projects"*, with compute allowances of *"100 CU-hours/project/month"* and compute scale-down after *"5 min inactivity; cannot disable"*.
- **Legacy / Conservative Context:** Earlier documentation and community benchmarks cited a 0.5 GiB (512 MiB) cap. Because some free projects or previous tiers operated under 0.5 GiB, calculations in this document evaluate both the conservative 0.5 GiB threshold and the official 1 GB quota.

### 3.2 Oracle Cloud Always Free Reconciliation (Official Entitlement vs Conflicting Evidence & Idle Reclamation)
- **Official Specification (retrieved 2026-10-22, page updated 2026-06-12):** The official OCI documentation ([OCI Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)) entitles users to:
  - *"All tenancies get the first 1,500 OCPU hours and 9,000 GB hours per month for free for VM instances using the VM.Standard.A1.Flex shape (Arm processor). For Always Free tenancies, this is equivalent to 2 OCPUs and 12 GB of memory."*
  - 2 AMD-based Compute VMs (1 GB RAM each).
  - 200 GB total Block Volume storage.
- **Conflicting Evidence & Reported Cuts:** In 2026, widespread developer reports cited a reduction from the historical 4 OCPUs and 24 GB of RAM. The official documentation dated 2026-06-12 provides conflicting evidence against those older 4 OCPU / 24 GB claims, confirming the current free entitlement is officially 1,500 OCPU-hours and 9,000 GB-hours (2 OCPUs and 12 GB of memory).
- **Operational Constraints & Reclamation:**
  1. **Regional Capacity Exhaustion:** Popular data centers frequently encounter `Out of capacity for shape VM.Standard.A1.Flex` during VM provisioning.
  2. **Idle Instance Reclamation:** Oracle enforces an automated reclamation policy: *"Idle Always Free compute instances may be reclaimed by Oracle."* If over a 7-day window, the 95th percentile CPU utilization is $<20\%$, memory utilization is $<20\%$, and network transfer is $<20\%$, the VM is automatically reclaimed.
- **Verdict:** Oracle does **not** sleep on short idles, but requires active utilization or an upgraded Pay-As-You-Go account ($0 charged if staying within free tier allowances) to prevent 7-day idle reclamation.

### 3.3 HiveMQ Cloud Serverless Retirement
- **Official Source:** [HiveMQ Cloud Serverless End of Life Documentation](https://docs.hivemq.com/hivemq-cloud/serverless-end-of-life.html) (retrieved 2026-10-22).
- **Exact Quotation:** *"HiveMQ retires the HiveMQ Cloud Serverless plan on 2026-12-31."*
- **Operational Impact:** *"You can no longer create a Serverless cluster or upgrade a Serverless cluster to Pay As You Go."* In addition, *"After 2026-12-31, MQTT clients can no longer connect to your Serverless clusters."* and *"After the end-of-life date, HiveMQ permanently deletes all Serverless clusters and the data on the clusters."* Therefore, HiveMQ Serverless is excluded from PlantPulse's future hosting roadmap.

---

## 4. Comprehensive Hosting Options Comparison

### 4.1 Python Application Hosting

| Provider & Tier | RAM / CPU | Sleep & Idle Rules | Inbound WebSockets | Outbound MQTT Client | Bandwidth & Request Limits | Official Documentation URL | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Oracle Cloud**<br>*(OCI Always Free)* | 2 Arm OCPUs<br>12 GB RAM | Reclaims if 95th percentile CPU/RAM/net < 20% over 7 days. Does NOT sleep on short idle. | Supported natively. Standard Linux socket handling. | Supported. Full unrestricted outbound TCP networking. | 10 TB egress/mo.<br>200 GB block storage. | [OCI Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) | **Best Match.** Runs full Docker Compose stack unchanged. |
| **Koyeb**<br>*(Free Instance)* | 512 MB RAM<br>0.1 vCPU<br>2 GB SSD | Scales to zero after **1 hour** of inactivity. Active WebSocket held connection prevents scale-down. | Supported. Persistent WebSocket prevents scale-to-zero while browser is open. | Allowed on standard ports (1883/8883). Drops on sleep. | 100 GB outbound egress/mo.<br>No request caps. | [Koyeb Pricing](https://www.koyeb.com/pricing) <br> [Koyeb Scale to Zero](https://www.koyeb.com/docs/run-and-scale/scale-to-zero) | **Viable for Web/API.** Free Instance automatically scales down to zero after 1h idle. |
| **Render**<br>*(Free Web Service)* | 512 MB RAM<br>0.1 vCPU | Spins down after **15 minutes** of no inbound traffic. Cold start ~50s. | Supported while active, but idle drops all connections. | Allowed while running; drops on spin down. | 750 free instance hours/month total across workspace.<br>5 GB egress/mo. | [Render Free Plans](https://render.com/docs/free) | **Fragile.** Sleep drops MQTT subscriber and resets in-memory caches. 1 continuous service max. |
| **PythonAnywhere**<br>*(Beginner Free)* | 512 MB RAM<br>100s CPU/day | Does not sleep during day; apps expire if not renewed every 3 mos. | **Unsupported.** Only WSGI apps supported natively on free tier. | **Blocked.** Raw TCP sockets blocked. Only HTTP/HTTPS to whitelisted domains allowed. | 100 CPU-seconds/day (tarpitted afterwards). | [PythonAnywhere Accounts](https://help.pythonanywhere.com/pages/AccountTypes/) <br> [PythonAnywhere Allowlist](https://help.pythonanywhere.com/pages/API-allowlist/) | **Incompatible.** Cannot connect to MQTT broker and cannot serve ASGI WebSockets. |

### 4.2 Hosted MQTT Broker Free Tiers

| Broker Provider | Free Connection Limit | Free Bandwidth / Message Quota | TLS / Protocol Requirements | Dynamic Authentication & ACLs | Official Documentation URL | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Self-Hosted Mosquitto**<br>*(on VM)* | OS file descriptor limit (~65k) | Unlimited (bounded by VM bandwidth). | Configurable (TLS 8883, cleartext 1883, local socket). | Native `passwd` file and `acl.conf` reloaded via SIGHUP. | [Mosquitto.conf Manual](https://mosquitto.org/man/mosquitto-conf-5.html) | **Exact Match.** Matches existing PlantPulse production codebase identically. |
| **EMQX Cloud**<br>*(Serverless)* | Up to **1,000** concurrent connections | 1M session-minutes/mo.<br>1 GB egress/mo.<br>1M rule actions/mo. | **Strict TLS Mandatory.** Port 8883 (MQTTS) or 8084 (WSS). Cleartext 1883 blocked. SNI required. | Up to 2,000 auth users & 2,000 ACL rules. Managed via REST API. | [EMQX Serverless Quotas](https://docs.emqx.com/en/cloud/latest/deployments/serverless.html) | **Best Cloud Broker.** Reliable if Spend Limit set to $0 and TLS certificates configured. |
| **HiveMQ Cloud**<br>*(Serverless)* | 100 devices | 10 GB data traffic/mo.<br>3-day data retention. | Port 8883 (TLS), WebSockets. | Console credential management. | [HiveMQ End of Life](https://docs.hivemq.com/hivemq-cloud/serverless-end-of-life.html) | **Do Not Use.** Scheduled for total retirement on Dec 31, 2026; new cluster creation disabled. |

### 4.3 Hosted PostgreSQL Free Tiers

| Database Provider | Storage Limit | Compute & Inactivity Rules | Connection Limits | Network Egress | Official Documentation URL | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Self-Hosted PostgreSQL**<br>*(on VM)* | Bounded only by disk (e.g. 50–200 GB) | Continuous 24/7 compute. Never scales to zero or pauses. | Configurable `max_connections` (e.g. 100–500). | Unlimited local network transfer between containers. | [PostgreSQL 16 Docs](https://www.postgresql.org/docs/16/) | **Best Match.** Zero risk of monthly quota cutoff or table-size read-only locks. |
| **Supabase**<br>*(Free Plan)* | **500 MB** table & index data (read-only mode if exceeded) | Nano compute.<br>Pauses after **7 days of inactivity** (lack of database queries). | Direct: **60**.<br>Supavisor Pooler: **200** clients (port 6543 / 5432). | 5 GB uncached + 5 GB cached (10 GB/mo). | [Supabase Free Plan](https://supabase.com/docs/guides/platform/org-based-billing#free-plan) <br> [Supabase Pausing](https://supabase.com/docs/guides/platform/pausing) | **Viable.** Regular telemetry queries prevent pause. Aggressive retention needed for 500 MB. |
| **Neon**<br>*(Free Tier)* | **1 GB** (up to 20 GB across 100 projects; 0.5 GiB conservative) | 100 Compute Unit (CU)-hours/mo.<br>Scales to zero after **5 min** of inactivity. | Pooled & direct connections. Suspends when 100 CU-hrs expire. | 5 GB egress/mo. | [Neon Plans](https://neon.tech/docs/introduction/plans) | **High Risk.** 100 CU-hours equals only ~4.1 days of continuous execution. Hard suspends. |

---

## 5. Local Measurement Benchmarks & Storage Calculations

### 5.1 Real Database Ingestion Benchmark (60.0 Seconds)
A 60.0-second local benchmark was conducted measuring the exact `SELECT count(*) FROM telemetry_values` delta while running the simulator for both active plants with an active viewer connected:
1. `plant_demo_membrane`: 11 machines/stations ticking every 1.0 second (60 ticks = 660 telemetry messages).
2. `plant_water_district_9`: 3 pumps ticking every 5.0 seconds (12 ticks = 36 telemetry messages).

- **Benchmark Duration:** 60.0 seconds
- **Total Telemetry Messages Processed:** 696 messages (~11.6 msgs/s)
- **Total MQTT Messages Published (including state changes and queues):** 726 messages (**12.10 msgs/s**)
- **Initial `telemetry_values` Row Count:** 214
- **Final `telemetry_values` Row Count:** 3,322
- **Delta `telemetry_values` Rows Inserted:** **3,108 rows**
- **Measured Database Telemetry Rate:** **51.80 rows/second**

#### Machine Telemetry Breakdown (`SELECT plant_id, machine_code, count(*)`)

| Plant ID | Machine Code | Metrics Emitted / Tick | 60s Ticks | 60s Total Rows |
| :--- | :--- | :--- | :--- | :--- |
| `plant_demo_membrane` | `am_01` (Assembly 1) | 6 | 60 | 360 |
| `plant_demo_membrane` | `am_02` (Assembly 2) | 6 | 60 | 360 |
| `plant_demo_membrane` | `am_03` (Assembly 3) | 6 | 60 | 360 |
| `plant_demo_membrane` | `am_04` (Assembly 4) | 6 | 60 | 360 |
| `plant_demo_membrane` | `cs_01` (Casting 1) | 6 | 60 | 360 |
| `plant_demo_membrane` | `cs_02` (Casting 2) | 6 | 60 | 360 |
| `plant_demo_membrane` | `hm_01` (Housing 1) | 4 | 60 | 240 |
| `plant_demo_membrane` | `hm_02` (Housing 2) | 4 | 60 | 240 |
| `plant_demo_membrane` | `qc_01` (QC Test 1) | 2 | 60 | 120 |
| `plant_demo_membrane` | `qc_02` (QC Test 2) | 2 | 60 | 120 |
| `plant_demo_membrane` | `qc_03` (QC Test 3) | 2 | 60 | 120 |
| `plant_water_district_9` | `pump_01` (Intake P-101) | 5 | 12 | 60 |
| `plant_water_district_9` | `pump_02` (Booster P-102) | 2 | 12 | 24 |
| `plant_water_district_9` | `pump_03` (Standby P-103) | 2 | 12 | 24 |
| **Total** | **14 machines** | **59 metrics** | — | **3,108 rows** |

#### Explanation: 3,108 Rows vs ~2,030 Expected
In the plant definition JSON files:
- `plants/plant_demo_membrane.json` defines **32 signals** across 11 machines.
- `plants/plant_water_district_9.json` defines **9 signals** across 3 machines.

If only strictly defined signals were generated over the 60-second window (60 ticks for demo, 12 ticks for water):
$$(32\text{ signals} \times 60\text{ ticks}) + (9\text{ signals} \times 12\text{ ticks}) = 1{,}920 + 108 = \mathbf{2{,}028\text{ rows}}\quad (\sim 2{,}030\text{ expected})$$

However, `demo/simulator/simulator.py` generates **18 unmodeled metrics per tick** beyond the schema definitions:
1. **Assembly stations (`am_01`–`am_04`):** The simulator generates unconfigured `torque_setpoint`, `seal_pressure_setpoint`, and duplicate `vibration` alongside `vibration_mms` (3 extra metrics $\times$ 4 machines = **12 extra metrics/tick**).
2. **Casting machines (`cs_01`–`cs_02`):** The simulator generates unconfigured `viscosity_setpoint` and duplicate `vibration` (2 extra metrics $\times$ 2 machines = **4 extra metrics/tick**).
3. **Housing molders (`hm_01`–`hm_02`):** The simulator generates duplicate `vibration` alongside `vibration_mms` (1 extra metric $\times$ 2 machines = **2 extra metrics/tick**).

Total unmodeled metrics: $12 + 4 + 2 = 18\text{ metrics/tick}$.  
Total metrics emitted per tick for `plant_demo_membrane`: $32 + 18 = 50\text{ metrics/tick}$.  
- `plant_demo_membrane` rows: $50\text{ metrics/tick} \times 60\text{ ticks} = 3{,}000\text{ rows}$.
- `plant_water_district_9` rows: $9\text{ metrics/tick} \times 12\text{ ticks} = 108\text{ rows}$.
- **Reconciled Total:** $3{,}000 + 108 = \mathbf{3{,}108\text{ rows}}$.

#### Duplicate Publisher Verification
An audit was conducted to confirm that duplicate publishers were not inflating message rates. Inspection of running processes via `ps aux | grep -i -E "simulator|publisher"` confirmed that exactly one simulator process was active with zero duplicate background publishers.

### 5.2 Measured PostgreSQL Telemetry Row Footprint (500,000 Row Benchmark)
Measured on PostgreSQL 16 on leaf partition `telemetry_values_p2026_10_22` containing the primary key `(device_timestamp, plant_id, message_id, signal_code)` and secondary composite indexes:
- **Benchmark Scale:** 500,000 synthetic telemetry rows generated via `generate_series`.
- **Initial Partition Total Size:** 4,497,408 bytes
- **Final Partition Total Size:** 218,324,992 bytes
- **Delta Bytes:** 213,827,584 bytes
- **Total Size per Row:** **427.66 bytes/row**
  - **Heap Table Data:** 116.87 bytes/row
  - **B-Tree Indexes (3 composite indexes):** 310.77 bytes/row
- **What this Figure Excludes:**
  - This figure measures strictly the `telemetry_values` partitioned leaf table and its 3 B-Tree indexes.
  - It **excludes** other database tables: `units`, `stage_events`, `qc_results`, `active_alarms`, `alarm_rules`, `machine_states`, `signals`, `machines`, `areas`, `plants`, `plant_credentials`.
  - It **excludes** PostgreSQL Write-Ahead Log (WAL) generation.
  - It **excludes** catalog tables, free space map (FSM) pages, and dead tuple MVCC bloat before autovacuum reclamation.

### 5.3 Days to Fill Free Database Quotas (0.5 GiB, 500 MB & 1 GB)

Using the measured 500k-row footprint (**427.66 bytes/row**) and measured ingestion rate (**51.80 rows/sec**):

#### Scenario A: Continuous 24/7 Simulator (Unthrottled)
- Daily rows inserted: $51.80\text{ rows/s} \times 86{,}400\text{ s/day} = 4{,}475{,}520\text{ rows/day}$.
- Daily storage consumption: $4{,}475{,}520 \times 427.66\text{ bytes} \approx 1{,}914{,}001{,}075\text{ bytes/day}$ (**1.914 GB/day** or 1.783 GiB/day).
- **Supabase (500 MB = 500,000,000 bytes):**
  $$\frac{500{,}000{,}000\text{ bytes}}{1{,}914{,}001{,}075\text{ bytes/day}} \approx \mathbf{0.261\text{ days}}\quad (\sim 6.3\text{ hours})$$
  *(The database exceeds quota and locks into read-only mode in ~6.3 hours).*
- **Neon (0.5 GiB = 536,870,912 bytes):**
  $$\frac{536{,}870{,}912\text{ bytes}}{1{,}914{,}001{,}075\text{ bytes/day}} \approx \mathbf{0.280\text{ days}}\quad (\sim 6.7\text{ hours})$$
- **Neon Official / 1 GB (1,000,000,000 bytes):**
  $$\frac{1{,}000{,}000{,}000\text{ bytes}}{1{,}914{,}001{,}075\text{ bytes/day}} \approx \mathbf{0.522\text{ days}}\quad (\sim 12.5\text{ hours})$$

#### Scenario B: Viewer-Gated Simulation (Watchdog Active)
- **Assumption:** Evaluators interact with the live dashboard for **1 hour per day** total ($3{,}600\text{ seconds}$), while the existing heartbeat watchdog pauses publishing for the remaining 23 hours.
- Active daily ingestion: $51.80\text{ rows/s} \times 3{,}600\text{ s} = 186{,}480\text{ rows/day}$.
- Daily storage consumption: $186{,}480 \times 427.66\text{ bytes} \approx 79{,}750{,}037\text{ bytes/day}$ (**79.75 MB/day** or 76.06 MiB/day).
- **Days to fill without partition dropping:**
  - **Supabase (500 MB):** $\frac{500{,}000{,}000\text{ bytes}}{79{,}750{,}037\text{ bytes/day}} \approx \mathbf{6.27\text{ days}}$
  - **Neon (0.5 GiB = 536,870,912 bytes):** $\frac{536{,}870{,}912\text{ bytes}}{79{,}750{,}037\text{ bytes/day}} \approx \mathbf{6.73\text{ days}}$
  - **Neon Official 1 GB (1,000,000,000 bytes):** $\frac{1{,}000{,}000{,}000\text{ bytes}}{79{,}750{,}037\text{ bytes/day}} \approx \mathbf{12.54\text{ days}}$

#### Scenario B.1: Viewer-Gated Steady-State Storage (2 Daily Partitions + Other Tables)
- **Partition Retention Assumption:** Under `RETENTION_DAYS = 1`, the retention worker maintains up to **2 active daily partitions** at steady state (the current day's active partition plus yesterday's partition awaiting the daily cleanup run).
- **Telemetry Partitions Footprint:**
  $$2 \times 79.75\text{ MB/day} = \mathbf{159.50\text{ MB}}\quad (152.1\text{ MiB})$$
- **Other Tables Footprint (Measured Baseline & Operational Estimate):**
  - **Measured public tables baseline:** Exactly **0.78 MB** (819,200 bytes across `signals`, `machines`, `qc_results`, `plant_credentials`, `stage_events`, `areas`, `plants`, `units`, `machine_states`, `alembic_version`, `active_alarms`, and `alarm_rules`).
  - **2-day operational accumulation estimate:** Accounting for ~72 completed units (36 units/h $\times$ 2 h), ~300 stage events, and ~70 QC test rows over 2 active viewing hours, non-telemetry tables grow by ~0.7 MB to an estimated **~1.5 MB**.
- **Total Steady-State Database Size (Estimated):**
  $$\text{Total Steady-State Storage} \approx 159.50\text{ MB} + 1.50\text{ MB} = \mathbf{\sim 161.0\text{ MB}}\quad (\textbf{Estimated Range: } 155\text{--}170\text{ MB})$$
- **Free Tier Headroom & Quota Feasibility:**
  - **Supabase (500 MB limit):** Consumes $\frac{161.0\text{ MB}}{500\text{ MB}} \approx \mathbf{32.2\%}$, leaving **~339 MB of safety headroom** (67.8% buffer).
  - **Neon (0.5 GiB / 536.87 MB limit):** Consumes $\frac{161.0\text{ MB}}{536.87\text{ MB}} \approx \mathbf{30.0\%}$, leaving **~375 MB of safety headroom** (70.0% buffer).
  - **Neon Official (1 GB / 1,000 MB limit):** Consumes $\frac{161.0\text{ MB}}{1{,}000\text{ MB}} \approx \mathbf{16.1\%}$, leaving **~839 MB of safety headroom** (83.9% buffer).
- **Conclusion:** Under viewer gating with a 24-hour daily partition drop policy, steady-state storage permanently hovers around ~161 MB, remaining safely within free tier limits without risk of read-only quota locks.

---

## 6. Daily Partitions vs RETENTION_HOURS Analysis

In `db.py`, telemetry data is stored in partitioned tables created by day: `telemetry_values_pYYYY_MM_DD`. Dropping data via partition DDL (`DROP TABLE telemetry_values_p...`) is an atomic metadata operation that immediately frees disk space without vacuum overhead.

However, supporting fine-grained sub-day retention (e.g. `RETENTION_HOURS = 6` to avoid exceeding 500 MB) conflicts with whole-day partitions:

1. **Option 1: Hourly Partitions (`_pYYYY_MM_DD_HH`)**
   - *Mechanism:* Change partition generation in `db.ensure_partitions` to partition by hour instead of day. The retention worker (`retention.py`) drops partitions older than `RETENTION_HOURS` via `DROP TABLE`.
   - *Pros:* Instant zero-cost disk reclamation; zero MVCC dead-tuple bloat; no autovacuum pressure.
   - *Cons:* Heavy catalog overhead: 24 partition tables per day (168 per week). Query planning over wide time ranges must prune dozens of sub-tables.
2. **Option 2: Row-Level Deletes (`DELETE ... WHERE device_timestamp < NOW() - INTERVAL 'X hours'`)**
   - *Mechanism:* Maintain daily partitions, but execute periodic `DELETE` queries matching the sub-day window.
   - *Pros:* Exact hourly control with no changes to the daily partition schema.
   - *Cons:* Triggers PostgreSQL MVCC write amplification; deleted rows remain as dead tuples until autovacuum runs; does not immediately release physical disk space back to the operating system without `VACUUM FULL`.
3. **Option 3: Keep Daily Partitions and Cap Rows / Days (Recommended)**
   - *Mechanism:* Keep daily partitions, but reduce retention to 1 day max (`RETENTION_DAYS = 1`). In addition, enforce an application-level cap on maximum telemetry rows stored per plant.
   - *Pros:* Zero architectural complexity; retains DDL partition dropping; works reliably within 500 MB when paired with viewer gating.
   - *Cons:* Resolution is bounded to 24-hour boundaries.

---

## 7. What Breaks in Our Codebase & Required Architecture Changes

### 7.1 SIGHUP Broker Reload via Shared PID Namespace
- **Current Code:** In `docker-compose.yml`, `api` has `pid: "service:broker"`. In [`scripts/generate_mosquitto_auth.py`](file:///home/critic-coder/project/PlantPulse/scripts/generate_mosquitto_auth.py#L380-L400) and [`main.py`](file:///home/critic-coder/project/PlantPulse/main.py#L84), `sync_broker_auth_from_db()` writes credentials to `/mosquitto/auth/passwd` and topics to `/mosquitto/auth/acl.conf`, locates Mosquitto's PID via `/proc` or `pgrep`, and calls `os.kill(broker_pid, signal.SIGHUP)`.
- **Why it breaks in distributed cloud:** In separate cloud services (Render, Koyeb, Fly.io, or hosted EMQX), the backend runs in an isolated container without access to the broker's process table or filesystem. Hosted brokers do not read local Mosquitto config files or listen to Linux OS signals.
- **Required Fix:** Introduce an abstract reloader interface (`MQTTReloader`): `LocalMosquittoReloader` for Docker/VM, `EmqxRestReloader` (REST API over HTTPS) for cloud brokers, and `NullReloader` for testing.

### 7.2 Single Uvicorn Worker & In-Memory State
- **Current Code:** State is held in Python process memory:
  - `ConnectionManager._rooms`: active WebSocket clients per plant.
  - `TicketStore._tickets`: 30-second single-use tickets for WebSocket auth.
  - `ViewerTracker._last_poll_at`: REST polling timestamps for rate limiting and simulator heartbeat.
- **Why it breaks:**
  - **Horizontal Scaling:** If scaled to $>1$ worker (e.g. `gunicorn -w 4` or multiple container replicas), tickets issued by Worker 1 are rejected as invalid (4401) by Worker 2, and WebSocket broadcasts are partitioned across workers.
  - **Cold Starts:** When containers spin down on idle, in-memory state is wiped.
- **Required Fix:** Restrict free deployment strictly to **1 replica and 1 uvicorn worker**.

### 7.3 Viewer Watchdog Status
- **Current Code Reality:** Inspection of `main.py` ([lines 867–884](file:///home/critic-coder/project/PlantPulse/main.py#L867-L884)) and `demo/simulator/mqtt_publisher.py` ([lines 125–152 & 320–375](file:///home/critic-coder/project/PlantPulse/demo/simulator/mqtt_publisher.py#L125-L152)) confirms that **the viewer-gated simulator and heartbeat watchdog ALREADY EXIST in the codebase**. The API periodically broadcasts heartbeats to `plants/{plant_id}/control/heartbeat` when `viewer_tracker.has_recent_poll()` is true, and the simulator's `Watchdog` pauses publication after 30 seconds of heartbeat silence.
- **Impact on Roadmap:** There is no need to build the viewer-gated simulator from scratch. PR planning focuses only on configuring simulator tick intervals (`SIMULATOR_INTERVAL_SECONDS`) and verifying cross-service watchdog messaging over TLS.

### 7.4 Plaintext MQTT (Port 1883) vs Enforced TLS (Port 8883)
- **Current Code:** In `main.py`, `aiomqtt.Client(hostname=MQTT_HOST, port=MQTT_PORT)` connects over unencrypted TCP on port 1883.
- **Why it breaks:** EMQX Cloud Serverless and other hosted brokers strictly prohibit unencrypted port 1883. They enforce TLS on port 8883 with Server Name Indication (SNI).
- **Required Fix:** Add `MQTT_USE_TLS=true` and `MQTT_TLS_CA_CERTS` support to the FastAPI `aiomqtt` connection manager.

---

## 8. Account Requirements, Billing Risk & Security Hardening

### 8.1 Account & Credit Card Requirements
- **Oracle Cloud (OCI):** Requires a valid credit card during sign-up for identity verification. Places a $1 temporary hold. Does not bill for Always Free resources. ([OCI Free Tier](https://www.oracle.com/cloud/free/))
- **Koyeb:** Requires a credit card during sign-up to prevent fraud ([Koyeb Pricing](https://www.koyeb.com/pricing)). (Note: Community reports of a specific $29 temporary pre-authorization hold are unverified in official documentation).
- **Supabase & Neon:** Free tiers do NOT require a credit card for initial registration. ([Supabase Pricing](https://supabase.com/pricing), [Neon Pricing](https://neon.tech/pricing))
- **Render:** Free tier does not require a credit card, but free hours are limited to 750 hours/month shared across all services. ([Render Free Plans](https://render.com/docs/free))

### 8.2 Billing Risk & Spend Limits
- **EMQX Cloud Serverless:** Must configure the account **Spend Limit to exactly $0** to prevent unexpected overage billing if device traffic or session-minutes spike. ([EMQX Serverless Quotas](https://docs.emqx.com/en/cloud/latest/deployments/serverless.html))
- **Supabase:** Free projects automatically pause after 7 days of inactivity; if database exceeds 500 MB, it enters read-only mode rather than auto-charging. ([Supabase Billing](https://supabase.com/docs/guides/platform/org-based-billing#free-plan))
- **Neon:** Suspends compute automatically when 100 CU-hours are exhausted rather than billing overages on the Free plan. ([Neon Plans](https://neon.tech/docs/introduction/plans))

### 8.3 Public VM Security Hardening (for OCI / VPS Deployment)
If deploying to a public VM:
1. **Firewall & Ports:** Expose only port 80/443 (reverse proxy with Let's Encrypt TLS) and port 8883 (MQTTS with TLS). **Never expose port 5432 (Postgres) or unauthenticated port 1883 (MQTT)** to the public internet; bind them to `127.0.0.1` or the internal Docker bridge network.
2. **SSH Hardening:** Disable SSH password authentication; require SSH ed25519 keys only. Disable root login (`PermitRootLogin no`). Install `fail2ban`.
3. **Internal Process Isolation:** Mosquitto and Postgres should run as non-root container users.

### 8.4 Security Policy for Admin Endpoints: `MOUNT_ADMIN_ENDPOINTS=false`
In `admin_auth.py`, the backend maintains fallback authentication via a static `ADMIN_TOKEN`. In any public hosting environment, **`MOUNT_ADMIN_ENDPOINTS` must remain `false`** (or admin routes disabled) until the static token fallback is completely retired and replaced exclusively by Clerk cryptographic JWT verification and RBAC roles. Exposing a static admin bearer token on a public IP creates brute-force and credential exposure risks.

---

## 9. Implementation PR Split Plan

### PR 1: Broker Reloader & Transport Abstraction
- Abstract `sync_broker_auth_from_db()` behind an `MQTTReloader` interface (`LocalMosquittoReloader`, `EmqxRestReloader`, `NullReloader`).
- Add TLS connection configuration (`MQTT_USE_TLS`, `MQTT_TLS_CA_CERTS`) to FastAPI `aiomqtt` connection logic.
- *Risk:* Low. Defaults to existing Mosquitto SIGHUP behavior unless configured via environment.

### PR 2: Configurable Simulation Rate & Cloud Tick Interval
- Note: Viewer-gating and heartbeat watchdog are **already implemented**.
- Add environment variable `SIMULATOR_INTERVAL_SECONDS` (default 1.0, configurable up to 5.0 for cloud hosting) to reduce message throughput on bandwidth-constrained free brokers.
- *Risk:* Low. Pure configuration addition.

### PR 3: Database Retention Worker Configuration & Connection Pooling
- Update `retention.py` to support aggressive daily retention (`RETENTION_DAYS = 1`) and verify partition dropping under Supabase connection poolers (Supavisor port 6543 vs direct port 5432).
- Add row-count monitoring alert if partition size approaches 400 MB.
- *Risk:* Low.

### PR 4: Cloud Deployment Manifests & Public Hardening Guide
- Provide sample `docker-compose.prod.yml` configured with `MOUNT_ADMIN_ENDPOINTS=false`, TLS reverse proxy (Caddy/Traefik), and loopback port bindings.
- Add deployment guide for OCI Always Free Arm instance.
- *Risk:* Low. Documentation and configuration only.

---

## 10. Open Questions & Architectural Decisions

1. **Portfolio Demo vs Industrial Testbed:** Is the hosted instance intended as an interactive web portfolio demo (where viewer-gated simulation and short idle pauses are acceptable), or an edge testbed requiring continuous telemetry ingestion?
2. **Single VM vs Multi-Service Serverless:** Given that an OCI Always Free VM or a $4/month VPS runs the entire tested Docker Compose stack without code modifications, does adapting to multi-provider serverless limits (EMQX + Supabase + Koyeb + Vercel) justify the ongoing maintenance overhead?
3. **Admin Token Deprecation:** What is the timeline for removing `ADMIN_TOKEN` entirely from `admin_auth.py` so that admin endpoints can safely be mounted in cloud deployments?
 
---

## 11. Unverified Claims List

1. **Koyeb $29 Pre-Authorization Hold:** Third-party community reports state that Koyeb charges a temporary $29 pre-authorization hold upon adding a payment card. Official documentation at `https://www.koyeb.com/pricing` confirms payment card verification to prevent fraud, but does not state the specific $29 amount. This claim is categorized as **Unverified**.
2. **Neon 0.5 GiB Quota:** Historical developer posts and earlier tier benchmarks cited a 0.5 GiB (512 MiB) project quota. Official documentation at `https://neon.tech/docs/introduction/plans` explicitly documents 1 GB per project (up to 20 GB across 100 projects). The 0.5 GiB figure is retained strictly as an unverified legacy threshold or conservative baseline scenario.
