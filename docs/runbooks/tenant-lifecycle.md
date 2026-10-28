# Runbook: Tenant Lifecycle, Billing & Provisioning

## 1. Overview & Principles

This runbook defines the operational procedures and architectural behaviors governing tenant lifecycle states, billing tier enforcement, invitation delivery, and permanent tenant deletion within the Laptop Productivity Monitoring SaaS.

As mandated by **`AGENTS.md`** and **`docs/spec/SPEC.md`**:
- Monitoring is transparent, policy-driven, and auditable.
- Tenant isolation is strictly enforced at every layer; tenant context is always derived from authenticated credentials, never accepted from request parameters.
- Missing telemetry during suspension or deletion is treated as an explicit unknown gap—never fabricated as active, idle, or productive time.
- Acceptance of events and webhooks is idempotent; raw billing webhook events are immutably logged for auditability.

---

## 2. Tenant Lifecycle States

```
                ┌───────────────────────────────────────┐
                │               PROVISIONING            │
                └───────────────────┬───────────────────┘
                                    │ Registration complete
                                    ▼
                ┌───────────────────────────────────────┐
       ┌───────►│                ACTIVE                 │◄────────┐
       │        └───────────────────┬───────────────────┘         │
       │                            │                             │
       │ Payment resolved /         │ Non-payment / E43           │ Manual
       │ Admin un-suspend           │ Admin suspension            │ reactivation
       │                            ▼                             │
       │        ┌───────────────────────────────────────┐         │
       └────────┤               SUSPENDED               ├─────────┘
                └───────────────────┬───────────────────┘
                                    │ Deletion requested
                                    ▼
                ┌───────────────────────────────────────┐
                │          PENDING DELETION /           │
                │          CASCADE DELETING (E44)       │
                └───────────────────┬───────────────────┘
                                    │ Cascade sweep finished
                                    ▼
                ┌───────────────────────────────────────┐
                │                DELETED                │
                └───────────────────────────────────────┘
```

---

## 3. Subscription & Quota Enforcement (REQ-15-3, E85)

### 3.1 Per-Tenant Seat Quotas
- Every tenant is linked to an active `Subscription` specifying an approved `Plan` (e.g. Free, Starter, Professional, Enterprise).
- Each plan specifies `max_seats` (allowed enrolled devices) and `retention_days`.
- Seat enforcement is executed **server-side** during device registration and enrollment:
  ```python
  from apps.billing.services import enforce_subscription_seat_limit
  enforce_subscription_seat_limit(tenant)
  ```
- If the tenant has reached `max_seats`:
  - Enrollment endpoint returns HTTP `400 Bad Request` with code `seat_limit_reached` (Edge Case **E85**).
  - The desktop installer aborts enrollment cleanly with error code `SEAT_QUOTA_EXCEEDED` and presents an actionable message instructing the administrator to upgrade the subscription plan.

### 3.2 Plan Upgrades & Webhook Synchronization (E84)
- Billing events from the payment gateway (Stripe/Paddle) arrive at `/api/billing/webhook/`.
- Every incoming webhook is authenticated via HMAC-SHA256 signature verification (`verify_webhook_signature`).
- **Idempotency (E84):** If a webhook `event_id` has already been recorded in `WebhookEvent`, the handler skips processing and immediately acknowledges with HTTP `200 OK`.
- **Out-of-Order Delivery (E84):** Webhooks carry `event_time`. If an event arrives whose `event_time` is earlier than the subscription's `last_event_timestamp`, it is classified as `skipped_out_of_order` to prevent stale downgrades from overwriting newer subscription upgrades.

---

## 4. Tenant Suspension Procedures (E43)

### 4.1 Triggering Suspension
Suspension is triggered automatically when a billing invoice remains past-due beyond the grace period (7 days) or manually by a superadmin / organization owner via:
```http
POST /api/tenants/{tenant_id}/suspend/
Authorization: Bearer <AdminToken>
Content-Type: application/json

{
  "reason": "Payment overdue / non-payment after grace period"
}
```

### 4.2 System Behavior Under Suspension
1. **API & Web Dashboard Access:**
   - Any authenticated request for a suspended tenant fails closed with `403 Forbidden` (`{"error": "tenant_suspended", "detail": "Tenant account is suspended."}`).
   - All tenant-scoped cache entries are purged (`cache.delete(f"tenant:{tenant.id}:active")`).
2. **Device Agent Behavior:**
   - On the next agent heartbeat or sync attempt, the backend returns HTTP `403 Forbidden` with header `X-Tenant-Status: suspended`.
   - The desktop agent catches the suspension response, pauses telemetry recording and screenshot capture, and transitions to the `SUSPENDED` state.
   - The agent spool retains un-uploaded events up to the local storage limit without overflowing or crashing.
   - A desktop tray notification alerts the user: *"Organization account is suspended. Productivity monitoring paused."*
3. **Audit Trail:**
   - A high-severity audit record `TENANT_SUSPENDED` is written to `AuditLog` capturing actor IP, timestamp, and suspension reason.

### 4.3 Reactivation Workflow
```http
POST /api/tenants/{tenant_id}/suspend/
Authorization: Bearer <AdminToken>
Content-Type: application/json

{
  "active": true
}
```
Reactivating the tenant resets `tenant.is_active = True`, invalidates negative cache entries, and permits agents to resume normal heartbeat and sync operations.

---

## 5. Tenant Deletion & Cascade Procedures (E44)

### 5.1 Deletion Policy
Tenant deletion is permanent and irretrievable. Deletion requires organization owner authentication or platform superadmin authorization.

```http
DELETE /api/tenants/{tenant_id}/
Authorization: Bearer <OrgOwnerToken>
```

### 5.2 Staged Cascade Execution Order
The cascade deletion service `delete_tenant_cascade(tenant_id, actor=user)` executes within an atomic database transaction:

1. **Session & Auth Invalidation:**
   - Purge tenant Redis cache keys (`tenant:{id}:*`).
   - Revoke all active API tokens for users whose primary tenant is the deleted tenant.
2. **Object Storage Sweep (Screenshots):**
   - Query all `Screenshot` records associated with devices belonging to the tenant.
   - Dispatch background cleanup tasks to delete raw images and thumbnails from private S3 object storage:
     ```python
     storage.delete(screenshot.storage_key)
     ```
3. **Database Cascade:**
   - Delete `Screenshot` records.
   - Delete `TimelineSegment`, `WindowActivityEvent`, and `DailyMetric` records.
   - Delete `DeviceEventBatch` and `DeviceHeartbeat` records.
   - Delete `Device` records.
   - Delete `Team` and `Membership` records.
   - Delete `Invitation` records.
   - Delete `Subscription`, `Plan`, and `WebhookEvent` records.
   - Delete `AuditLog` entries for the tenant.
   - Finally, delete the `Tenant` record itself.

---

## 6. User Invitations & Delivery Failure (E83)

### 6.1 Invitation Flow
1. An Org Admin invites a team member via `POST /api/tenants/{tenant_id}/invitations/`.
2. The system creates an `Invitation` record with a cryptographically secure token (valid for 7 days) and `delivery_status="pending"`.
3. `send_invitation_email(invitation)` attempts asynchronous email dispatch via SMTP.

### 6.2 Delivery Failure Handling (E83)
- If the SMTP relay fails, drops the connection, or rejects the recipient address:
  - The exception is caught and logged.
  - `invitation.delivery_status` is updated to `"failed"`.
  - `invitation.delivery_error` stores the truncated error reason (e.g., `SMTPException: Connection refused`).
  - **The invitation creation does not abort.** The API response returns HTTP `201 Created` with `delivery_status: "failed"` and includes the invitation token and claim URL.
  - The UI presents a clear warning to the admin with a "Copy Invite Link" action and a "Resend Invitation" button.

### 6.3 Invitation Claiming
- The recipient navigates to `/invitations/claim?token=<token>`.
- `accept_invitation(token, user)` binds the user to the tenant with the assigned role, marks the invitation as accepted, and increments active seat metrics.
- Tokens are single-use; any subsequent claim attempt returns `400 Bad Request` (`invitation_already_accepted` or `invitation_expired`).

---

## 7. Emergency Runbook Commands

### Resending Failed Invitations
```bash
python backend/manage.py shell -c "
from apps.tenancy.models import Invitation
from apps.tenancy.services import send_invitation_email
for inv in Invitation.objects.filter(delivery_status='failed'):
    send_invitation_email(inv)
"
```

### Manual Webhook Replay Verification
```bash
python backend/manage.py shell -c "
from apps.billing.services import process_billing_webhook
payload = {...}
process_billing_webhook(payload, signature_verified=True)
"
```
