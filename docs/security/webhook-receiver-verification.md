# Webhook Receiver Verification

How a receiver of SupportPilot AI's outbound webhooks should verify a
delivered request. This describes the receiver's own responsibility — the
sender-side signing implementation lives in `backend/webhooks/signing.py`.

## Headers sent with every request

| Header                       | Meaning                                                  |
|-------------------------------|-----------------------------------------------------------|
| `X-SupportPilot-Event-Id`     | Stable id of the logical event (never changes on retry)  |
| `X-SupportPilot-Delivery-Id`  | Stable id of this logical delivery (never changes on retry) |
| `X-SupportPilot-Timestamp`    | Unix seconds at the time of *this* attempt — fresh every attempt |
| `X-SupportPilot-Signature`    | `v1=<hex HMAC-SHA256>` — recomputed fresh every attempt   |
| `Idempotency-Key`             | Equal to `X-SupportPilot-Delivery-Id` — stable across every retry |

## Verifying a request

1. **Read the raw request body bytes exactly as received** — do not parse
   the JSON and re-serialize it before verifying. Any re-serialization
   (different key order, whitespace, float formatting, etc.) will not
   match the signed bytes even though the parsed content is identical.
2. **Reconstruct the signed payload** as
   `f"{timestamp}.".encode("ascii") + raw_body_bytes`, using the exact
   value of `X-SupportPilot-Timestamp` and the exact raw body bytes from
   step 1.
3. **Compute `HMAC-SHA256(your_signing_secret, signed_payload)`** and
   compare it, as the lowercase hex digest prefixed `v1=`, against
   `X-SupportPilot-Signature` using a **constant-time comparison**
   (e.g. Python's `hmac.compare_digest`, not `==`) to avoid a timing
   side-channel.
4. **Enforce a timestamp tolerance.** Reject a request whose
   `X-SupportPilot-Timestamp` is further from your own current time than a
   tolerance you choose (a few minutes is typical). The timestamp alone is
   not a replay-protection guarantee — it only bounds how old a valid
   signature can be; you must also do step 5.
5. **Deduplicate using the stable identity**, not the signature or
   timestamp (which are intentionally fresh per attempt, not stable). Use
   `X-SupportPilot-Delivery-Id` (equivalently `Idempotency-Key`) as your
   dedup key: if you have already durably processed a delivery with this
   id, treat a repeat as a no-op rather than re-applying the side effect.
   This is required, not optional — SupportPilot AI's delivery guarantee
   is at-least-once (see
   [Asynchronous delivery and outbound webhooks](../architecture/asynchronous-delivery-and-webhooks.md)),
   so the same logical delivery may arrive more than once under normal
   operation (retries, at-least-once redelivery), not only under attack.
6. **Return a 2xx status only once you consider the event durably
   accepted** — e.g. after your own database transaction that records the
   dedup key and applies the side effect has committed. Returning 2xx
   before that point and then failing to actually process the event will
   not be retried, because the sender only retries on a non-2xx (or
   connection-level) outcome.

## What the sender does and does not guarantee

- The sender always sends the identical raw body bytes for every retry of
  the same logical delivery — verifying the same secret against those
  bytes will always succeed regardless of which attempt you received.
- The sender never reuses a timestamp or signature across attempts, so
  your tolerance/replay check should be based on your own dedup state
  (step 5), not on assuming a given signature can only ever be presented
  once in principle.
- The sender does not guarantee delivery order between different logical
  deliveries, and does not guarantee that a given delivery's attempts
  arrive in strict attempt-number order under all failure conditions.
  Use the event's own id/timestamp for any ordering your integration
  needs — never arrival order.
