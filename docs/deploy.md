# Hosted Production Deployment Guide (PR H1 / #103)

This guide documents the end-to-end hosted deployment topology for PlantPulse:
- **Backend API & Broker:** Render (Free Web Service running `Dockerfile.hosted`)
- **Frontend Dashboard:** Vercel (Next.js with root directory `frontend`)
- **Serverless PostgreSQL:** Neon (PostgreSQL 16 with daily partition pruning)
- **Authentication:** Clerk (Development Instance)

---

## 1. Secrets Generation & Secret Types

Any credentials that grant administrative access or authorize ingestion must be cryptographically random 128-bit or 256-bit hexadecimal tokens. Generate each secret using standard OpenSSL:

```bash
openssl rand -hex 16
```

> [!IMPORTANT]
> **Password Uniqueness:** `BACKEND_MQTT_PASSWORD`, `MQTT_PASSWORD` (demo membrane plant device), and `WATER_MQTT_PASSWORD` (water district 9 device) must each be separately generated, unique tokens. If any two passwords are identical, the hosted entrypoint script will fail fast with a non-zero exit code.

### Secrets vs Public Configurations

| Environment Variable | Target Platform | Type | Purpose / Rationale | How to Generate |
| :--- | :--- | :--- | :--- | :--- |
| `DATABASE_URL` | Render | **Secret** | Neon pooled PostgreSQL connection URI with SSL mode. | From Neon Dashboard (pooled) |
| `DATABASE_URL_UNPOOLED` | Render | **Secret** | Neon direct PostgreSQL URI for Alembic migrations. | From Neon Dashboard (direct) |
| `BACKEND_MQTT_PASSWORD` | Render | **Secret** | Internal password for FastAPI broker backend client. | `openssl rand -hex 16` |
| `MQTT_PASSWORD` | Render | **Secret** | Ingestion password for `plant_demo_membrane` device. | `openssl rand -hex 16` |
| `WATER_MQTT_PASSWORD` | Render | **Secret** | Ingestion password for `plant_water_district_9` device. | `openssl rand -hex 16` |
| `PLANT_WATER_DISTRICT_9_VIEWER_TOKEN` | Render | **Secret** | Viewer bearer token for gated Water District 9 plant (required). | `openssl rand -hex 16` |
| `ADMIN_TOKEN` / `ADMIN_SECRET_TOKEN` | *None* | **Hardened** | Must stay UNSET on hosted deployment. If set, entrypoint warns and unsets them. | Keep unset |
| `CLERK_PUBLISHABLE_KEY` | Render | **Public** | Clerk frontend publishable API key identifier. | From Clerk Dashboard |
| `CORS_ORIGINS` | Render | **Public** | Allowed browser origin (must match your Vercel URL). | e.g. `https://plantpulse.vercel.app` |
| `ENABLE_SELF_SERVICE` | Render | **Flag** | Disable self-service endpoints on public hosted tier (`false`). | Explicitly set `"false"` |
| `RETENTION_DAYS` | Render | **Flag** | Telemetry retention horizon in days (`2` on free tier). | Explicitly set `"2"` |
| `ENABLE_RETENTION_WORKER` | Render | **Flag** | Scheduled partition pruning retention worker (`true` on hosted). | Explicitly set `"true"` |
| `DEMO_MAX_SECONDS_PER_DAY`| Render | **Flag** | Daily demo budget in distinct seconds (`1800` = 30 min). | Explicitly set `"1800"` |
| `MOUNT_ADMIN_ENDPOINTS` | Render | **Flag** | Prevent administrative API route exposure (`false`). | Explicitly set `"false"` |
| `CLERK_SECRET_KEY` | Vercel | **Secret** | Backend Clerk API secret key for frontend Next.js server actions. | From Clerk Dashboard |
| `NEXT_PUBLIC_ENABLE_SELF_SERVICE` | Vercel | **Build Flag** | Hides "My plants" self-service tabs in frontend UI (`false`). | Explicitly set `"false"` |
| `NEXT_PUBLIC_API_URL` | Vercel | **Build Var** | Base HTTPS URL of Render backend web service. | e.g. `https://plantpulse-api.onrender.com` |
| `NEXT_PUBLIC_WS_URL` | Vercel | **Build Var** | Base WSS URL of Render backend WebSocket endpoint. | e.g. `wss://plantpulse-api.onrender.com` |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Vercel | **Build Var** | Public Clerk client key for frontend auth provider. | From Clerk Dashboard |
| `NEXT_PUBLIC_DEMO_VIDEO_URL` | Vercel | **Build Var** | Optional video walkthrough link on budget exhaustion banner. | e.g. `https://youtu.be/...` |
| `NEXT_PUBLIC_DEMO_HINTS` | Vercel | **Build Flag** | Optional inline hints for demo viewer tokens (`false` or `true`). | Explicitly set `"false"` |


---

## 2. Platform Setup & Configuration

### Step 1: Provision Database on Neon
1. Create a Neon project (`plantpulse`).
2. Obtain the pooled connection string:
   ```text
   postgresql://[user]:[password]@[endpoint]-pooler.[region].aws.neon.tech/[dbname]?sslmode=require&channel_binding=require
   ```
3. Obtain the unpooled (direct) connection string for Alembic schema migrations:
   ```text
   postgresql://[user]:[password]@[endpoint].[region].aws.neon.tech/[dbname]?sslmode=require
   ```

### Step 2: Configure Clerk Authentication
1. Create a free Clerk application at [dashboard.clerk.com](https://dashboard.clerk.com).
2. Set application environment to **Development**.
3. Under **Configure > API Keys**, copy:
   - `Publishable key`: `pk_test_...`
   - `Secret key`: `sk_test_...`
4. Under **Configure > Paths**, set redirect URLs:
   - Sign in: `/`
   - Sign up: `/`

### Step 3: Deploy Backend on Render
1. In Render, select **New > Blueprint** and link your Git repository containing `render.yaml`.
2. When prompted for environment secrets (marked `sync: false`):
   - `DATABASE_URL`: Your pooled Neon connection string.
   - `DATABASE_URL_UNPOOLED`: Your direct Neon connection string.
   - `BACKEND_MQTT_PASSWORD`: Generated token (`openssl rand -hex 16`).
   - `MQTT_PASSWORD`: Generated token (`openssl rand -hex 16`).
   - `WATER_MQTT_PASSWORD`: Generated token (`openssl rand -hex 16`).
   - `PLANT_WATER_DISTRICT_9_VIEWER_TOKEN`: Generated token (`openssl rand -hex 16`, required).
   - `CLERK_PUBLISHABLE_KEY`: `pk_test_...`
   - `CORS_ORIGINS`: `https://[your-app-name].vercel.app` (or temporary `*` during initial bootstrap, then lock down to Vercel domain).
   *(Note: `ADMIN_TOKEN` and `ADMIN_SECRET_TOKEN` stay UNSET on hosted deployment. If set, the entrypoint warns and unsets them).*
3. Confirm fixed flags:
   - `ENABLE_SELF_SERVICE="false"`
   - `RETENTION_DAYS="2"`
   - `ENABLE_RETENTION_WORKER="true"`
   - `DEMO_MAX_SECONDS_PER_DAY="1800"`
   - `MOUNT_ADMIN_ENDPOINTS="false"`
4. Deploy the service. Verify the `/health` check turns green.

### Step 4: Deploy Frontend on Vercel
1. In Vercel, select **Add New > Project** and import the PlantPulse repository.
2. In Project Settings, set **Root Directory** to `frontend`.
3. Configure Environment Variables for Production & Preview:
   - `NEXT_PUBLIC_ENABLE_SELF_SERVICE="false"`
   - `NEXT_PUBLIC_API_URL="https://[your-render-service].onrender.com"`
   - `NEXT_PUBLIC_WS_URL="wss://[your-render-service].onrender.com"`
   - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY="pk_test_..."`
   - `CLERK_SECRET_KEY="sk_test_..."`
4. Trigger the deployment (`npm run build`).

### Step 5: Finalize CORS Configuration
Once your Vercel deployment URL is live (e.g., `https://plantpulse.vercel.app`):
1. In Render Dashboard, update `CORS_ORIGINS` to `https://plantpulse.vercel.app`.
2. Save changes (triggers zero-downtime rolling restart).

---

## 3. Post-Deployment Verification Checklist

Once both services are deployed, perform the following verification steps:

- [ ] **1. Health & Budget Check**:
  Navigate to `https://[your-render-service].onrender.com/health`.
  Verify response status is `200 OK` with JSON envelope:
  ```json
  {
    "status": "ok",
    "demo_budget": {
      "max_seconds_per_day": 1800,
      "used_seconds": 0,
      "remaining_seconds": 1800,
      "resets_at": "...",
      "exhausted": false
    }
  }
  ```
- [ ] **2. Live Demo WebSocket**:
  Open the frontend URL `https://[your-vercel-domain].vercel.app`.
  Confirm the demo membrane plant connects via WebSocket (`wss://.../ws/plant_demo_membrane/telemetry`) and live telemetry metrics update every second.
- [ ] **3. Wake-Up Banner Resilience**:
  Allow the Render instance to idle for 15+ minutes until spun down.
  Refresh the Vercel dashboard. Verify the amber banner **"Waking up the demo, this can take about a minute"** appears with exponential retry countdown until the backend wakes.
- [ ] **4. Water Plant Viewer Token**:
  Select the gated **Water District 9** plant in the plant picker.
  Verify the token prompt modal appears. Enter `PLANT_WATER_DISTRICT_9_VIEWER_TOKEN` and confirm access unlocks live telemetry.
- [ ] **5. Historical Telemetry Graph**:
  Click on any machine on the demo plant (e.g. `RO_UNIT_01`) and inspect the signal history graph. Verify data points load seamlessly via the partition-pruned REST endpoint.
- [ ] **6. Self-Service Gating**:
  Confirm the navigation bar does NOT show the "My plants" link when `NEXT_PUBLIC_ENABLE_SELF_SERVICE=false`.
  Verify direct browser navigation to `/api/me/plants` on the backend returns `404 Not Found`.
- [ ] **7. Daily Demo Budget Limit**:
  When 1,800 distinct seconds of telemetry are accumulated for the day, confirm the rose banner **"Daily demo limit reached, resets at 00:00 UTC"** appears and the simulator heartbeat is cleanly paused.
