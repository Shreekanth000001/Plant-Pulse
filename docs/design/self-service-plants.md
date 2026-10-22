# Self-Service Plant Provisioning & Developer Onboarding Architecture

**Author:** PlantPulse Core Team  
**Status:** Proposed Architecture & Housekeeping Revision  
**Date:** 2026-10-22  
**Target Branch:** `docs/final-phase`  
**Related Issues:** Refs #55, Refs #68, Closes #100  

---

## 1. Executive Summary & Goals

PlantPulse was initially engineered around two static manufacturing facilities: a high-speed reverse-osmosis membrane line (`plant_demo_membrane`) and an edge-connected municipal pumping facility (`plant_water_district_9`). Administrative plant registration (`POST /api/admin/plants`) was added in PR #57, but it remains locked behind `platform_admin` privileges and requires static `ADMIN_TOKEN` or manual platform credentials.

The goal of this design is to outline the transition of PlantPulse into a **self-service multi-tenant platform** where authenticated users (signed up via Clerk) can:
1. Define and spin up their own manufacturing plant or IoT facility.
2. Become the owner/manager of their created facility with scoped management rights.
3. Connect edge hardware or simulation clients via standard MQTT topics.
4. Experience an intuitive developer onboarding flow where sample data is clearly labeled.

---

## 2. Current State Analysis (Code Audit)

### 2.1 Plant Creation & Authorization Flow
- **Endpoint:** `POST /api/admin/plants` (defined in [`main.py`](file:///home/critic-coder/project/PlantPulse/main.py#L1769-L1824)).
- **Authorization Barrier:** Gated strictly by `current_user: Annotated[AdminUser, Depends(require_platform_admin)]`. Any user with `plant_manager` or a signed-in user without an administrative role receives **403 Forbidden**.
- **Admin Mount Gate:** Only operational when `MOUNT_ADMIN_ENDPOINTS=true`. If set to `false` (default on production deployments), the entire administrative routing subtree returns **404 Not Found**.
- **Ownership Tracking:** The `plants` relational table in PostgreSQL consists solely of `(id, name, timezone, viewer_token_hash)`. There is **zero record of which user created or owns a plant**.

### 2.2 Input Validation Status & Limits (PR #100 Verification)
Following the merge of PR #100 (Closing Issue #100), the following validation rules and resource caps are active in [`plant_definitions.py`](file:///home/critic-coder/project/PlantPulse/plant_definitions.py) and [`main.py`](file:///home/critic-coder/project/PlantPulse/main.py):
- `PlantDefinition.name`: Length 1–128 characters, strictly rejects newlines (`\n`), carriage returns (`\r`), and control characters.
- `plant_id`: Matches `^[a-z0-9_]{3,57}$` (ensuring auto-generated `device_{plant_id}` fits within the 64-character broker limit).
- `machine_code`: Matches `^[a-z0-9_]{2,64}$`.
- `signal_code`: Matches `^[a-z0-9_]{2,64}$`.
- `MQTTCredential.username`: Validated against `^[a-z0-9_]{3,64}$` (rejects colons, spaces, newlines, and wildcard characters).
- `MQTTCredential.password`: Validated to reject newlines and null bytes (`\x00`).
- **Topology Caps:** Maximum 100 machines per plant, 100 signals per machine, and 500 signals total per plant (HTTP 422 if exceeded).
- **Body Limit:** ASGI middleware (`AdminBodyLimitMiddleware`) enforces a strict 1 MB limit on `POST`/`PUT` requests under `/api/admin` counting raw bytes received (HTTP 413).
- **Corrupt DB Record Handling:** Startup routines in `db.py` and `scripts/generate_mosquitto_auth.py` skip and log corrupt stored plants that violate caps or naming rules, preserving server availability.

### 2.3 Mosquitto Authentication & ACL File Generation (Security Audit)
- **Status: FIXED by PR #100.**
- **Previous Vulnerability:** In earlier drafts, `plant.name` was interpolated directly into ACL comment headers (`# Plant: {pname} ({pid})`), allowing newline injection if `plant.name` contained control characters. Custom MQTT usernames also lacked regex validation, risking ACL rule injection.
- **Current Hardened Implementation:**
  - In [`scripts/generate_mosquitto_auth.py`](file:///home/critic-coder/project/PlantPulse/scripts/generate_mosquitto_auth.py#L210-L245) and [`db.py`](file:///home/critic-coder/project/PlantPulse/db.py), ACL comment headers format strictly as:
    ```text
    # Plant: {pid}
    user {username}
    topic readwrite plants/{pid}/#
    ```
  - Unescaped `pname` is completely omitted from the ACL comments.
  - Usernames and passwords are validated before being written to `/mosquitto/auth/passwd` and `/mosquitto/auth/acl.conf`.
  - Malformed credentials or backend environment variables trigger `ValueError` and fail closed.

### 2.4 Device Provisioning & Ingest Reality
- **Provisioning Today:**
  - Creating a plant provisions an MQTT credential `device_{plant_id}` with a cryptographically generated 32-byte urlsafe token.
  - Plaintext credentials are returned only once in the HTTP 201 response.
  - Backend writes `passwd` and `acl.conf` to disk and signals Mosquitto via `SIGHUP`.
- **Simulator & Publishing Reality:**
  - The built-in simulator ([`demo/simulator/mqtt_publisher.py`](file:///home/critic-coder/project/PlantPulse/demo/simulator/mqtt_publisher.py)) is hardcoded to simulate only `plant_demo_membrane` and `plant_water_district_9`.
  - **Zero automated publishers serve newly created plants.** A newly created plant has no telemetry stream and perpetually renders "No data yet" until an external client publishes to `plants/{plant_id}/assets/{machine_code}/telemetry`.
  - Telemetry ingest is currently 100% exclusive to the MQTT broker subscriber in [`ingest.py`](file:///home/critic-coder/project/PlantPulse/ingest.py).

### 2.5 Frontend App Router & Navigation Audit
Every page under [`frontend/app`](file:///home/critic-coder/project/PlantPulse/frontend/app) was audited:
1. `/` (`app/page.tsx`): Public floor overview. Shows plant switcher; does **not** show create plant.
2. `/analytics` (`app/analytics/page.tsx`): Public quality analytics. Does **not** show create plant.
3. `/units` (`app/units/page.tsx`): Public unit genealogy. Does **not** show create plant.
4. `/units/[unitId]` (`app/units/[unitId]/page.tsx`): Public unit inspection. Does **not** show create plant.
5. `/sign-in/[[...sign-in]]`: Public Clerk sign-in. Does **not** show create plant.
6. `/sign-up/[[...sign-up]]`: Public Clerk sign-up. Does **not** show create plant.
7. `/admin` (`app/admin/page.tsx`): Admin portal. Gated by [`AdminLayout`](file:///home/critic-coder/project/PlantPulse/frontend/app/admin/layout.tsx) checking static `ADMIN_TOKEN`. Signed-in user without role sees `AdminTokenEntryCard` (or `AdminUnmountedScreen`). Does **not** show create plant.
8. `/admin/plants/new` (`app/admin/plants/new/page.tsx`): Plant creation wizard. Gated by `AdminLayout`. A signed-in user without a role sees only the token entry card.
9. `/admin/plants/[plantId]` (`app/admin/plants/[plantId]/page.tsx`): Gated by `AdminLayout`.
10. `/admin/plants/[plantId]/edit` (`app/admin/plants/[plantId]/edit/page.tsx`): Gated by `AdminLayout`.

**Summary:** Currently, **zero** frontend pages allow a signed-in non-admin user to create or view a self-service plant.

---

## 3. Gaps Matrix

| Category | Current State | Required State for Self-Service |
| :--- | :--- | :--- |
| **Authorization** | Creation requires `platform_admin`. | Authenticated Clerk user can create their own plant. |
| **Ownership** | `plants` table has no owner column. | `plants.owner_user_id` tracks creator; user receives scoped permissions. |
| **RBAC Storage** | Roles checked solely via Clerk JWT claims. | PostgreSQL `user_roles` table tracks fine-grained plant roles. |
| **Quota Enforcement** | 100 machines / 500 signals per plant; 1 MB body limit (PR #100). | Proposed default: **1 plant per user** (student decision pending). |
| **Sign-up Model** | Public Clerk sign-up enabled. | Proposed default: **Invite-only sign-up** (student decision pending). |
| **Ingest Protocol** | Mosquitto MQTT broker subscriber only. | **MQTT ingest kept until hosting is decided**; HTTP ingest deferred to later PR. |
| **Developer Onboarding** | Newly created plants remain empty indefinitely. | Simulated sample data supported but **clearly labeled as such** in the UI. |

---

## 4. Options & Architectural Decisions

### 4.1 Proposed Default Quotas (Student Decision Pending)

To protect infrastructure resources and simplify the initial multi-tenant deployment, the following defaults are proposed, subject to final student approval:

1. **Sign-up Model:** **Invite-only sign-up**. New user registrations must be invited or approved by a platform administrator to prevent public bot registrations and resource exhaustion.
2. **User Plant Quota:** **One plant per user** (`max_plants_per_user = 1`). Prevents database partition bloat on free cloud tiers.
3. **Topology Size Quotas (Active from PR #100):**
   - Maximum machines per plant: **100**.
   - Maximum signals per machine: **100**.
   - Maximum total signals per plant: **500**.
   - Maximum admin request body: **1 MB** (enforced by ASGI middleware).
4. **Data Ingest Protocol:** **MQTT ingest retained until hosting is decided**. The existing Mosquitto broker setup handles device credentials and telemetry streams reliably; direct HTTP ingest will be deferred to a later PR.
5. **Sample Telemetry Display:** Any simulated or synthetic sample data shown on the dashboard must be **clearly labeled as simulated** in the UI (e.g. an orange "Simulated Data" status banner).

---

### 4.2 Ownership & Permission Model

#### Option A: PostgreSQL Ownership & Role Storage (`plants.owner_user_id` + `user_roles` table) — *Recommended*
- **Mechanism:**
  - Add `owner_user_id VARCHAR(128) NOT NULL` to the `plants` table.
  - Introduce a dedicated `user_roles` table in PostgreSQL mapping `user_id`, `plant_id`, and `role`.
  - When `POST /api/plants` is called, the backend extracts `current_user.user_id` (Clerk `sub`) and records ownership in `plants` and `user_roles`.
- **Pros:**
  - Instant authorization without waiting for Clerk token refresh.
  - Zero external dependency on Clerk Backend API calls during plant creation.
  - Easily supports multi-plant access without inflating JWT size.
- **Cons:**
  - Requires a database query during authorization checks (mitigated via in-memory caching).

#### Option B: Clerk User `public_metadata` Mutation via Clerk Backend API
- **Mechanism:**
  - Backend calls Clerk Backend API (`PATCH https://api.clerk.com/v1/users/{user_id}/metadata`) to assign roles or append `plant_id` to `public_metadata`.
- **Server Secret Key Requirement:**
  - **Important:** Mutating user metadata from the backend requires `CLERK_SECRET_KEY` on the server environment. Without `CLERK_SECRET_KEY`, the backend cannot authenticate requests to Clerk's Backend API.
- **Pros:**
  - Roles and plant permissions are embedded directly in the JWT claims.
- **Cons:**
  - **Token Refresh Lag:** Clerk session tokens live for **60 seconds** ([Clerk Docs: Session tokens](https://clerk.com/docs/guides/sessions/session-tokens)). A user's browser token will not reflect the newly assigned metadata until refreshed ~50s later, causing immediate subsequent API requests to fail with 403 unless explicitly refreshed.
  - **Cookie Size Limits:** Clerk recommends custom metadata claims stay under **1.2 KB** due to browser 4 KB cookie limits ([Clerk Docs: Session tokens size limitations](https://clerk.com/docs/guides/sessions/session-tokens#size-limitations)).
  - **Rate Limits & Outages:** Adds external HTTP failure modes to plant creation.

---

### 4.3 Ingest Mechanism: MQTT vs Direct HTTP Ingest

- **Current Recommendation:** **Retain MQTT ingest until hosting architecture is decided.**
- **Future HTTP Ingest Route (`POST /api/plants/{plant_id}/telemetry`):**
  - Direct HTTP ingestion is a valuable enhancement for IoT devices that cannot maintain persistent TCP/MQTT sockets.
  - **Security Requirement:** Any HTTP ingest route **requires a dedicated per-plant API key** (or device key) passed via `Authorization: Bearer <plant_ingest_key>` to prevent unauthorized telemetry spoofing.
  - **PR Phasing:** Because HTTP ingest requires authentication tokens, rate limiters, and WebSocket broadcast integration, it is deferred to a **later, dedicated PR** after core self-service provisioning is in place.

---

### 4.4 Sample Data & Onboarding Experience

To prevent the "blank screen" problem when a user provisions their first plant:
- **No Vectorized Historical Seed Data:** In earlier proposals, generating 2 hours of synthetic time-series data via bulk SQL inserts was considered. This proposal is **dropped** because bulk database seeding introduces partition write spikes, risks foreign key errors, and clutters production telemetry storage.
- **Onboarding Experience:**
  1. **Clear UI Guidance:** Newly provisioned plants render an onboarding panel showing MQTT connection instructions: broker endpoint, port, client ID, username, password, and the exact topic structure (`plants/{plant_id}/assets/{machine_code}/telemetry`).
  2. **Sample Telemetry Generator (Client-Side or On-Demand):** If synthetic demonstration data is enabled, it must be **clearly labeled as simulated data** in the user interface (e.g. badge: "Demo Simulation Active") so evaluators and operators never confuse test data with live operational machinery.

---

## 5. PostgreSQL Schema Evolution & Roles Table Design

To support self-service ownership and scoped permissions without Clerk metadata lag, the following PostgreSQL schema changes are required:

### 5.1 Proposed Schema Migration

```sql
-- 1. Add owner column to plants table
ALTER TABLE plants ADD COLUMN owner_user_id VARCHAR(128);
CREATE INDEX idx_plants_owner_user_id ON plants(owner_user_id);

-- 2. Create user_roles table for granular multi-tenant RBAC
CREATE TABLE user_roles (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    plant_id VARCHAR(64) REFERENCES plants(id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL, -- 'owner', 'plant_manager', 'operator', 'viewer'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_user_plant_role UNIQUE (user_id, plant_id, role)
);

CREATE INDEX idx_user_roles_user_id ON user_roles(user_id);
CREATE INDEX idx_user_roles_plant_id ON user_roles(plant_id);

-- 3. Set existing demo plants to platform admin ownership
UPDATE plants SET owner_user_id = 'platform_admin' WHERE owner_user_id IS NULL;
```

### 5.2 Roles Table Integration with `admin_auth.py`
In `admin_auth.py`, `verify_admin_user` will be expanded to evaluate permissions using a tiered model:
1. **Platform Admin:** Verified via Clerk `role == "platform_admin"` or static `ADMIN_TOKEN`. Possesses global superuser access across all plants.
2. **Plant Owner / Manager:** Verified by checking if `(current_user.user_id, plant_id)` exists in `user_roles` with `role IN ('owner', 'plant_manager')`. Grants full configuration and machine management rights for that specific plant.
3. **Viewer:** Granted read-only dashboard access.

---

## 6. Implementation PR Split Plan

- **PR 1: Database Schema Migration & Roles Table**
  - Add `owner_user_id` to `plants` table and create `user_roles` table via Alembic.
  - Implement `RoleRepository` for managing user-plant role associations.
  - Update `admin_auth.py` to evaluate local `user_roles` alongside Clerk JWT claims.
  - *Risk:* Low. Pure database migration with backward compatibility.

- **PR 2: Self-Service Plant Creation API**
  - Add `POST /api/plants` accessible to any authenticated Clerk user.
  - Enforce proposed default quota: 1 plant per user.
  - Auto-generate initial device credentials (`device_{plant_id}`) and update Mosquitto ACLs.
  - *Risk:* Medium. Touches broker auth file synchronization.

- **PR 3: Frontend Self-Service Plant Creation Wizard**
  - Add "New Plant" button in frontend navigation for authenticated users without an existing plant.
  - Multi-step modal for defining areas, machines, and signals.
  - Post-creation modal displaying one-time MQTT credentials and connection code snippets.
  - Clear "Simulated Data" status labeling where synthetic streams are active.
  - *Risk:* Low. Frontend UI addition.

- **PR 4: Direct HTTP Ingest & Per-Plant API Keys (Later Phase)**
  - Implement `POST /api/plants/{plant_id}/telemetry` secured by per-plant API key.
  - Rate limiting and WebSocket push integration.
  - *Risk:* Medium. Introduces alternative ingest pathway.

---

## 7. Verified Sources & Citations

1. **Clerk Session Token Lifetime (60s default) & Refresh Cycle:**  
   - Source: [Clerk Official Documentation: Session Tokens](https://clerk.com/docs/guides/sessions/session-tokens)  
   - Retrieval Date: 2026-10-22  
   - Exact Quote: *"Session tokens are short-lived, with a default lifetime of 60 seconds."*
2. **Clerk Public Metadata Size Guideline (1.2KB / 4KB cookie limit):**  
   - Source: [Clerk Official Documentation: Session Tokens Size Limitations](https://clerk.com/docs/guides/sessions/session-tokens#size-limitations)  
   - Retrieval Date: 2026-10-22  
   - Exact Quote: *"keep custom claims under 1.2KB to avoid issues with browser cookie limits."*
3. **Clerk Backend API Authentication Requirements:**  
   - Source: [Clerk Backend API Reference](https://clerk.com/docs/reference/backend-api)  
   - Retrieval Date: 2026-10-22  
   - Exact Quote: *"All requests to the Backend API must be authenticated with a Secret Key"*
4. **Eclipse Mosquitto Configuration & ACL File Syntax:**  
   - Source: [Mosquitto.conf Manual](https://mosquitto.org/man/mosquitto-conf-5.html)  
   - Retrieval Date: 2026-10-22  
   - Exact Quote: *"Lines beginning with # are treated as comments."*

---

## 8. Unverified List

- None. All architectural constraints, limits, and provider citations cited in this document have been verified directly against the PlantPulse codebase (PR #100) or official documentation.
