# Design Plan: Clerk Authentication & Scoped Roles for PlantPulse

**Target Issues:** [#55](https://github.com/Shreekanth000001/Plant-Pulse/issues/55) (User login and plant manager roles), [#35](https://github.com/Shreekanth000001/Plant-Pulse/issues/35) (User login via Clerk)  
**Status:** Architecture & Implementation Plan  
**Target File:** `docs/design/clerk-login.md`  

---

## 1. Goal & Executive Summary

PlantPulse currently secures administrative endpoints (`/api/admin/*`) with a static master token (`ADMIN_TOKEN`) passed as a Bearer secret and stored in React memory. This plan details replacing `ADMIN_TOKEN` with **Clerk Authentication**, introducing:
1. **Platform Administrator (`platform_admin`)**: Full platform management across all plants.
2. **Plant Manager (`plant_manager`)**: Scoped access restricted strictly to a designated plant (`plant_id`).
3. **Public Demo & Viewer-Token Isolation**: Existing public demo (`plant_demo_membrane`) and viewer-token protected demo (`plant_water_district_9`) remain completely independent and unchanged.

---

## 2. Official Documentation Sources & Retrieval Dates

| Topic | Official Source & URL | Retrieval Date |
| :--- | :--- | :--- |
| Manual JWT Verification | [Clerk Docs: Manual JWT verification](https://clerk.com/docs/guides/sessions/manual-jwt-verification) | 2026-10-22 |
| Session Token Default Claims & Limits | [Clerk Docs: Session tokens](https://clerk.com/docs/guides/sessions/session-tokens) | 2026-10-22 |
| Session Token Lifetime (60s) | [Clerk Docs: Session tokens](https://clerk.com/docs/guides/sessions/session-tokens) | 2026-10-22 |
| Next.js 16 Proxy Convention (`proxy.ts`) | [Clerk Docs: clerkMiddleware() Reference](https://clerk.com/docs/references/nextjs/clerk-middleware) | 2026-10-22 |
| Next.js 16 File Routing | [Next.js Docs: Proxy File Convention](https://nextjs.org/docs/app/api-reference/file-conventions/proxy) | 2026-10-22 |
| Basic RBAC with Metadata | [Clerk Docs: Basic RBAC with metadata](https://clerk.com/docs/guides/secure/basic-rbac) | 2026-10-22 |
| Clerk Free Plan Limits | [Clerk Pricing](https://clerk.com/pricing) | 2026-10-22 |
| Python JWT RS256 & JWKS Verification | [PyJWT Docs: Retrieve keys from a JWKS](https://pyjwt.readthedocs.io/en/stable/usage.html#retrieve-keys-from-a-jwks) | 2026-10-22 |

---

## 3. Roles, Storage & Scoping

### 3.1 Roles & Hierarchy
- **`platform_admin`**: Full CRUD across all facilities, JSON definition import/export, device credentials rotation, and plant deletion.
- **`plant_manager`**: Scoped strictly to one plant (`plant_id`). Can view, update topology, and rotate device credentials for their assigned plant only. Cannot create or delete plants. If a token carries `role: "plant_manager"` but the `plant_id` claim is missing, empty (`""`), or not a string (wrong type), the request receives **403 Forbidden** (fail-closed enforcement).

### 3.2 Where Roles & Plant Assignments Live, and Why
- **Location:** In Clerk's `user.public_metadata`:
  ```json
  // Platform Admin
  { "role": "platform_admin" }

  // Plant Manager
  { "role": "plant_manager", "plant_id": "plant_water_district_9" }
  ```
- **Session Claim Mapping:** Mapped into the session JWT via Clerk Dashboard (**Sessions -> Customize session token**):
  ```json
  { "metadata": "{{user.public_metadata}}" }
  ```
- **Why:**
  1. **Clerk Free Plan Compatibility:** Free plan includes up to 50,000 Monthly Active Users (MAUs). Organizations on the free plan are capped at 20 members per Organization and require the paid B2B Add-on (~$100/mo) for custom rolesets.
  2. **Stateless Verification:** Roles and plant assignments are cryptographically signed within the session JWT, allowing FastAPI to authorize requests in memory without querying an external database or Clerk API on every request.
  3. **Client Read-Only:** `public_metadata` can be read by frontend code, but can only be mutated server-side via Clerk Dashboard or Clerk Backend API using `CLERK_SECRET_KEY`.

### 3.3 Bootstrap of First `platform_admin` & Role Administration
1. **First Admin Bootstrap (Step-by-Step):**
   - The user creates an account via Clerk sign-up on the frontend or directly via invitation.
   - The student logs into the Clerk Dashboard ([https://dashboard.clerk.com](https://dashboard.clerk.com)).
   - Navigates to **Users** -> selects the account.
   - Under **User metadata** -> **Public**, clicks **Edit**.
   - Enters `{"role": "platform_admin"}` and saves.
   - On the next token refresh (within 60s) or next login, the user's session token carries the `platform_admin` role.
2. **Subsequent Role Changes:**
   - Handled exclusively by platform administrators via the Clerk Dashboard or via a server-side admin endpoint using `clerkClient.users.updateUserMetadata`.
   - `plant_manager` users have zero access to metadata modification APIs.

### 3.4 Plant Manager Permissions Matrix & Recommendations

| Operation | Route | `plant_manager` Permission | Recommendation & Rationale |
| :--- | :--- | :--- | :--- |
| List Plants | `GET /api/admin/plants` | Scoped View | Allowed; backend filters list to show only their assigned `plant_id`. |
| Get Plant Detail | `GET /api/admin/plants/{id}` | Allowed (own plant only) | Allowed if `id == metadata.plant_id`; 403 Forbidden otherwise. |
| Create Plant | `POST /api/admin/plants` | **Denied (403)** | Denied. Global plant creation is reserved for `platform_admin`. |
| Delete Plant | `DELETE /api/admin/plants/{id}` | **Denied (403)** | Denied. Plant removal cascades deletion of all historical telemetry. |
| Update Topology (Normal) | `PUT /api/admin/plants/{id}` | Allowed (own plant only) | Allowed for renaming areas/machines and adding non-destructive elements. |
| Update Topology with Removals | `PUT /api/admin/plants/{id}?confirm_removals=true` | **Recommend Restrict** | **Recommendation:** Require `platform_admin`.<br/>*Reason:* Destructive removals permanently delete machines/signals and all historical time-series data.<br/>*(Marked as Open Question for Student).* |
| Rotate Edge Credentials | `POST /api/admin/plants/{id}/credentials/rotate` | **Recommend Allow** | **Recommendation:** Allow for assigned `plant_manager`.<br/>*Reason:* Field maintenance requires rotating edge passwords when devices are serviced without escalating to global admin.<br/>*(Marked as Open Question for Student).* |

*Claim Validation Rule:* A `plant_manager` token with a missing, empty (`""`), or non-string/wrong-type `plant_id` claim is treated as an invalid role assignment and receives **403 Forbidden** across all administrative endpoints.

---

## 4. Token Lifetime, Revocation Delay & Claim Limits

1. **Role Revocation Delay:**
   - *Behavior:* Clerk session tokens have a default lifetime of **60 seconds**, refreshed automatically in the background by client-side ClerkJS every ~50 seconds ([Clerk Docs: Session tokens](https://clerk.com/docs/guides/sessions/session-tokens)). If a user's role is revoked in `public_metadata`, their existing token remains cryptographically valid until its 60-second `exp` expires.
   - *Mitigation:* The 60-second window is acceptable for standard operations. For critical actions (e.g. plant deletion), the backend can optionally check an in-memory revocation list or query Clerk's Backend API.
2. **Custom Claim Size Limits:**
   - *Behavior:* Clerk notes that *"most browsers limit cookie size to 4KB"* (linking to RFC 2109, which is obsolete and replaced by RFC 6265). Clerk recommends keeping total custom session claims under **1.2KB** ([Clerk Docs: Session tokens size limitations](https://clerk.com/docs/guides/sessions/session-tokens#size-limitations)).
   - *Mitigation:* Store strictly minimal scalar fields in `public_metadata` (`role` and `plant_id`), totaling under 70 bytes. Never embed plant definitions or machine catalogs in user metadata.

---

## 5. Backend Architecture (FastAPI)

### 5.1 Verification Dependency
- **Implementation:** PyJWT (`jwt.decode`) with `algorithms=["RS256"]`, validating:
  - `exp` and `nbf` with clock skew tolerance (`leeway=10`).
  - `iss` matching `CLERK_ISSUER` (e.g. `https://<slug>.clerk.accounts.dev`).
  - `azp` matching allowed origins in `CLERK_AUTHORIZED_PARTIES` (e.g. `http://localhost:3000`).
- **Verification Modes:**
  - *Primary (Networkless):* `CLERK_PEM_PUBLIC_KEY` verified in memory (zero external network latency, works offline/tests).
  - *Fallback (Dynamic):* `PyJWKClient` pointing to `CLERK_JWKS_URL` with built-in key caching.

### 5.2 401 Unauthorized vs. 403 Forbidden
- **401 Unauthorized**: Missing or malformed `Authorization: Bearer` header, expired token (`exp`), signature failure, or mismatched `iss`/`azp`.
- **403 Forbidden**: Valid token signature and issuer, but user lacks necessary role permissions (no role, non-admin role, cross-plant access attempt, or `plant_manager` with a missing, empty, or wrong-type `plant_id` claim).

### 5.3 Overlap Period (Coexistence of `ADMIN_TOKEN` and Clerk)
During the transition (PR 1 through PR 3), authentication on admin endpoints follows this exact sequence:
1. **Exact Evaluation Order & Rate Limiting:**
   - **(a) Lockout check first:** Before performing any credential comparison, inspect `admin_rate_limiter`. If the client IP is currently locked out (exceeded failure threshold), immediately return **429 Too Many Requests**.
   - **(b) Static `ADMIN_TOKEN` compare:** If `ADMIN_TOKEN` is configured and `secrets.compare_digest(token, ADMIN_TOKEN)` matches, authenticate the request as `platform_admin` (legacy bypass). A valid static token does **not** count as a failure.
   - **(c) Clerk JWT verify:** If the token does not match `ADMIN_TOKEN`, attempt Clerk RS256 JWT decoding and validation (`exp`, `nbf`, `iss`, `azp`, signature). A valid JWT does **not** count as a failure.
   - **(d) Failure handling & rate limiter increment:** A request that fails both checks—including a malformed `Authorization` header, missing token, expired/invalid JWT signature, or incorrect static token guess—counts as one failure in `admin_rate_limiter` (5 attempts / 60s lockout) and returns **401 Unauthorized**. Valid static tokens or valid JWTs do not increment failures.
2. **Switch-off Step (PR 3):**
   - Remove `ADMIN_TOKEN` parsing and fallback logic entirely.
3. **Hosted Deployment Gate:**
   - `MOUNT_ADMIN_ENDPOINTS` **must stay `false`** on any hosted deploy until PR 2 (frontend integration) is merged and deployed, ensuring transitional admin endpoints are not exposed publicly.

---

## 6. Route Authentication Rules: Before vs. After

| Endpoint | Method | Pre-Clerk Auth Rule | Post-Clerk Auth Rule | Scope |
| :--- | :--- | :--- | :--- | :--- |
| `/health` | GET | Public | Public | None |
| `/api/plants` | GET | Public | Public | None |
| `/api/plants/{plant_id}/definition` | GET | `verify_plant_viewer` | `verify_plant_viewer` | Viewer token (Unchanged) |
| `/api/plants/{plant_id}/ws-ticket` | POST | `verify_plant_viewer` | `verify_plant_viewer` | Viewer token (Unchanged) |
| `/api/plants/{plant_id}/machines/latest` | GET | `verify_plant_viewer` | `verify_plant_viewer` | Viewer token (Unchanged) |
| `/api/plants/{plant_id}/queue-depths` | GET | `verify_plant_viewer` | `verify_plant_viewer` | Viewer token (Unchanged) |
| `/api/plants/{plant_id}/machines/{machine_code}/signals/{signal_code}/history` | GET | `verify_plant_viewer` | `verify_plant_viewer` | Viewer token (Unchanged) |
| `/ws/{plant_id}/telemetry` | WS | Ticket / Token | Ticket / Token | Viewer token (Unchanged) |
| `/api/plants/{plant_id}/units` | GET | `verify_plant_viewer` | `verify_plant_viewer` | Viewer token (Unchanged) |
| `/api/plants/{plant_id}/units/{unit_id}` | GET | `verify_plant_viewer` | `verify_plant_viewer` | Viewer token (Unchanged) |
| `/api/plants/{plant_id}/stats/defect-rate-by-hour` | GET | `verify_plant_viewer` | `verify_plant_viewer` | Viewer token (Unchanged) |
| `/api/plants/{plant_id}/stats/defect-rate-by-stage` | GET | `verify_plant_viewer` | `verify_plant_viewer` | Viewer token (Unchanged) |
| `/api/plants/{id}/stats/*` | GET | `verify_plant_viewer` | **REMOVED** | Legacy wildcard from old doc; replaced by explicit defect-rate routes |
| `/docs`, `/redoc`, `/openapi.json` | GET/HEAD | Public | Public | OpenAPI documentation / schemas |
| **`/api/admin/health`** | GET | Static `ADMIN_TOKEN` | Clerk JWT (Any admin role) | Authenticated |
| **`/api/admin/plants`** | GET | Static `ADMIN_TOKEN` | Clerk JWT (Filtered) | All (`platform_admin`) / Scoped (`plant_manager`) |
| **`/api/admin/plants/{plant_id}`** | GET | Static `ADMIN_TOKEN` | Clerk JWT (`require_plant_access`) | `platform_admin` or matching `plant_id` |
| **`/api/admin/plants`** | POST | Static `ADMIN_TOKEN` | Clerk JWT (`require_platform_admin`) | `platform_admin` only |
| **`/api/admin/plants/{plant_id}`** *(normal)* | PUT | Static `ADMIN_TOKEN` | Clerk JWT (`require_plant_access`) | `platform_admin` or matching `plant_id` |
| **`/api/admin/plants/{plant_id}?confirm_removals=true`** | PUT | Static `ADMIN_TOKEN` | **Pending student decision** (Recommend `platform_admin`) | `platform_admin` only (recommended) |
| **`/api/admin/plants/{plant_id}/credentials/rotate`** | POST | Static `ADMIN_TOKEN` | Clerk JWT (`require_plant_access`) | `platform_admin` or matching `plant_id` |
| **`/api/admin/plants/{plant_id}`** | DELETE | Static `ADMIN_TOKEN` | Clerk JWT (`require_platform_admin`) | `platform_admin` only |

---

## 7. Frontend Architecture (Next.js 16)

1. **SDK & Middleware:**
   - Install `@clerk/nextjs`. Wrap root tree in `<ClerkProvider>` ([`frontend/app/layout.tsx`](file:///home/critic-coder/project/PlantPulse/frontend/app/layout.tsx)).
   - Add root [`frontend/proxy.ts`](file:///home/critic-coder/project/PlantPulse/frontend/proxy.ts) using `clerkMiddleware()` (Next.js 16 convention).
2. **Sign-In & Admin Protection:**
   - Add route `/sign-in/[[...sign-in]]/page.tsx` rendering `<SignIn />`.
   - Update [`frontend/app/admin/layout.tsx`](file:///home/critic-coder/project/PlantPulse/frontend/app/admin/layout.tsx): remove `AdminTokenEntryCard`. If unauthenticated, redirect to `/sign-in`.
   - In `AdminHeader`: render `<UserButton />` and display active role badge (`Platform Admin` or `Plant Manager: <plant_id>`).
3. **API Client Integration:**
   - In [`frontend/lib/admin-api.ts`](file:///home/critic-coder/project/PlantPulse/frontend/lib/admin-api.ts), retrieve token using Clerk's `getToken()` and pass `Authorization: Bearer <token>`.
4. **WebSocket Flow:**
   - Viewer token flow for live telemetry remains unchanged.

---

## 8. Environment Variables

| Variable | Target | Description |
| :--- | :--- | :--- |
| `CLERK_PEM_PUBLIC_KEY` | Backend (`api`) | PEM-formatted RSA public key for networkless JWT verification. |
| `CLERK_ISSUER` | Backend (`api`) | Expected issuer (e.g. `https://dev-slug.clerk.accounts.dev`). |
| `CLERK_AUTHORIZED_PARTIES` | Backend (`api`) | Allowed `azp` origins (`http://localhost:3000,http://127.0.0.1:3000`). |
| `CLERK_JWKS_URL` | Backend (`api`) | Optional JWKS URL fallback. |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Frontend (`dashboard`) | Clerk publishable key (`pk_test_...` or `pk_live_...`). |
| `CLERK_SECRET_KEY` | Frontend (`dashboard`) | Clerk secret key (`sk_test_...`) for server-side Next.js. |
| `NEXT_PUBLIC_CLERK_SIGN_IN_URL` | Frontend (`dashboard`) | `/sign-in`. |
| `NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL` | Frontend (`dashboard`) | `/admin`. |
| `ADMIN_TOKEN` | Backend | Phased out in PR 3. |

---

## 9. Risks & Mitigations

1. **External Dependency Outages:**
   - *Risk:* Inability to verify tokens if Clerk APIs suffer downtime.
   - *Mitigation:* Networkless JWT verification via `CLERK_PEM_PUBLIC_KEY` in memory (zero outbound HTTP calls).
2. **Clock Drift Between Hosts:**
   - *Risk:* Rejection of valid tokens due to slight server clock differences.
   - *Mitigation:* Pass `leeway=10` to PyJWT `jwt.decode`.
3. **Breaking Test Automation:**
   - *Risk:* Existing pytest and npm test suites fail without active Clerk connection.
   - *Mitigation:* Pytest fixtures generate synthetic RSA-256 test keypairs to mint tokens locally; no live Clerk network calls during automated CI.

---

## 10. Tests-First Plan

| Test Name | File | Assertion | Why It Fails First |
| :--- | :--- | :--- | :--- |
| `test_clerk_valid_platform_admin_token` | `tests/test_clerk_auth.py` | Valid RS256 JWT with `platform_admin` role returns 200 on `/api/admin/plants`. | Endpoint expects legacy `ADMIN_TOKEN`. |
| `test_clerk_token_expired_fails_401` | `tests/test_clerk_auth.py` | JWT with expired timestamp returns 401 with `"Token has expired"`. | Backend lacks JWT expiration parser. |
| `test_clerk_token_wrong_azp_fails_401` | `tests/test_clerk_auth.py` | JWT with untrusted `azp` returns 401. | Backend does not check `azp`. |
| `test_clerk_token_wrong_issuer_fails_401` | `tests/test_clerk_auth.py` | JWT with foreign `iss` returns 401. | Backend does not validate issuer. |
| `test_plant_manager_accesses_own_plant` | `tests/test_clerk_auth.py` | `plant_manager` with `plant_id="plant_water_district_9"` accesses `/api/admin/plants/plant_water_district_9`. | Role scoping logic does not exist. |
| `test_plant_manager_cannot_access_other_plant`| `tests/test_clerk_auth.py` | `plant_manager` targeting a foreign plant returns 403 Forbidden. | Cross-plant scoping check missing. |
| `test_plant_manager_cannot_create_or_delete_plant`| `tests/test_clerk_auth.py` | `plant_manager` calling `POST /api/admin/plants` or `DELETE /api/admin/plants/{id}` returns 403. | Endpoint permits any bearer token matching `ADMIN_TOKEN`. |
| `test_plant_manager_invalid_or_missing_plant_id_claim_fails_403` | `tests/test_clerk_auth.py` | JWT with `role: "plant_manager"` but missing `plant_id`, empty `""`, or wrong type returns 403 Forbidden. | Section 3 fail-closed enforcement: corrupt or missing plant assignment claims cannot bypass plant scoping. |
| `test_admin_lockout_check_runs_before_token_eval` | `tests/test_clerk_auth.py` | Client IP exceeding lockout threshold receives 429 immediately, even with a valid static `ADMIN_TOKEN` or valid Clerk JWT. | Asserts rule (a): lockout check executes first before any token compare or decode. |
| `test_invalid_token_or_malformed_header_increments_rate_limiter` | `tests/test_clerk_auth.py` | 5 failed attempts (malformed header, bad static token, or invalid JWT) lock out client; 6th attempt returns 429. | Asserts rule (d): any failed authentication attempt increments `admin_rate_limiter`. |
| `test_valid_tokens_do_not_increment_rate_limiter` | `tests/test_clerk_auth.py` | Consecutive successful requests with valid `ADMIN_TOKEN` or valid Clerk JWT return 200 without triggering lockout. | Asserts valid static and JWT credentials never count as failures or trigger lockout. |
| `test_viewer_token_endpoints_remain_unaffected`| `tests/test_clerk_auth.py` | `/api/plants/{id}/definition` and `/api/plants/{id}/ws-ticket` validate against `viewer_token_hash`. | Asserts zero regression on viewer auth. |
| `test_frontend_admin_redirects_unauthenticated`| `frontend/tests/clerk-admin.test.ts` | Navigating to `/admin` without session redirects to `/sign-in`. | Layout currently renders token card. |

---

## 11. PR Split & Rollback Strategy

- **PR 1: Backend Clerk Verification & Scoped Roles**
  - Add `pyjwt[crypto]` to `requirements.txt`.
  - Implement `get_current_admin_user`, `require_platform_admin`, and `require_plant_access` in `admin_auth.py`.
  - Maintain dual-mode fallback (`ADMIN_TOKEN` + Clerk JWT).
  - Add `tests/test_clerk_auth.py` with synthetic RSA fixtures.
- **PR 2: Frontend Clerk Next.js 16 Integration & Admin Redesign**
  - Install `@clerk/nextjs`. Add `frontend/proxy.ts` and `/sign-in` route.
  - Redesign `/admin` layout: remove token card, integrate `<UserButton />`, role badges, and scoped views.
  - Update `lib/admin-api.ts` to attach live Clerk token.
- **PR 3: Deprecation & Cleanup**
  - Remove `ADMIN_TOKEN` evaluation, compose variables, and documentation references.
  - Close issues #55 and #35.

### Rollback Strategy
- During PR 1 & PR 2, dual-mode auth allows instant fallback by setting `ADMIN_TOKEN`.
- If an emergency rollback is required after PR 3, `git revert` restores static token verification cleanly.

---

## 12. Open Questions for the Student

1. **`confirm_removals=true` for Plant Managers:**
   - *Question:* Should `plant_manager` users be allowed to perform structural removals (`PUT /api/admin/plants/{plant_id}?confirm_removals=true`) on their own plant, or should removing machines and cascading historical data deletion strictly require `platform_admin`?
   - *Recommendation:* Require `platform_admin` due to the permanent destruction of historical machine telemetry.
2. **Edge Credential Rotation by Plant Managers:**
   - *Question:* Should `plant_manager` users be allowed to rotate edge MQTT device passwords (`POST /api/admin/plants/{plant_id}/credentials/rotate`) for their own plant?
   - *Recommendation:* Allow for `plant_manager` so field maintenance can proceed without platform admin intervention, while warning that edge devices will disconnect until updated.
3. **Sign-Up Policy:**
   - *Question:* In the Clerk Dashboard (**User & Authentication -> Sign-up**), will sign-ups be open to the public (requiring manual admin role assignment for access), or restricted to invited email addresses?

### Future, out of scope for PRs 1–3
- **Viewer Access for Plant Managers:** Should authenticated `plant_manager` users automatically be granted viewer access (minting WebSocket tickets) to their assigned plant without entering the viewer token? *Scope Decision:* Out of scope for PRs 1–3; the viewer-token flow stays completely unchanged.
