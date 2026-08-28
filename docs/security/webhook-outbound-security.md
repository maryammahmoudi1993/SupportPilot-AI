# Webhook Outbound Security

The implemented SSRF and transport security controls for outbound webhook
delivery (`backend/webhooks/security.py`, `backend/webhooks/transport.py`).
This describes what is actually enforced today, not an aspirational goal.

## URL policy

- **HTTPS required by default.** Plaintext HTTP is only ever accepted when
  the server-owned setting `WEBHOOKS_ALLOW_INSECURE_HTTP` is explicitly
  `True` (default `False`, intended for local development only) — no
  endpoint owner's URL can opt into HTTP by itself.
- Credentials embedded in the URL (`user:pass@host`), a URL fragment, a
  malformed or out-of-range port, and an unparseable URL are all rejected
  before any network activity.

## Destination validation

- An address is only usable as a webhook destination if it is a verified,
  **globally-routable** Internet address — the primary gate is
  `ipaddress.*.is_global`, not a hand-maintained blacklist. This
  correctly rejects loopback, private (RFC 1918), link-local (including
  the `169.254.169.254` cloud-metadata address), unspecified, reserved,
  carrier-grade NAT (`100.64.0.0/10`), IETF benchmarking
  (`198.18.0.0/15`), and the RFC 5737/3849 documentation ranges — without
  needing each enumerated individually.
- Two corrections are applied on top of `is_global`, because CPython's
  `ipaddress` module classifies them as globally routable even though
  they must never be treated as valid webhook destinations: all multicast
  addresses, and deprecated IPv6 site-local addresses (`fec0::/10`).
- An IPv4-mapped IPv6 address (e.g. `::ffff:169.254.169.254`) is unwrapped
  to its embedded IPv4 form before this check runs, so that form of
  bypass attempt is caught too.
- **DNS is resolved immediately before every attempt** — never cached from
  endpoint creation time or a prior attempt. If a hostname's resolution
  changes between retries (including a legitimate DNS change, not just an
  attack), the new resolution is what gets validated.
- **Every resolved address must be safe, or the whole destination is
  rejected** — a hostname that resolves to one public and one private
  address fails closed; the public one is never silently selected.

## Pinned, DNS-rebinding-safe transport

- The TCP/TLS connection is opened directly to the address `resolve_and_validate`
  already approved — the HTTP client is never given the hostname to
  resolve itself, so nothing downstream of validation can be tricked into
  connecting to a different (rebound) address than the one that was
  checked.
- TLS SNI (`server_hostname`) and certificate hostname verification
  (`assert_hostname`) both still use the **original hostname**, never the
  IP — certificate validation is never weakened to make IP-pinning work.
  `cert_reqs="CERT_REQUIRED"` is always set; there is no `verify=False`,
  no `CERT_NONE`, and no hostname-verification bypass anywhere in this
  code path.
- The `Host` header sent is also the original hostname.
- Redirects are never followed (`redirect=False` is always passed); a 3xx
  response is surfaced to the caller as a terminal, non-retried error. A
  redirect Location pointing at an internal address is never reached,
  because it is never followed at all.
- Connect and read timeouts are both bounded server-owned settings
  (`WEBHOOKS_CONNECT_TIMEOUT_SECONDS` / `WEBHOOKS_READ_TIMEOUT_SECONDS`);
  no unbounded wait is possible.
- The response body is read only far enough to drain the socket cleanly
  (a bounded cap) and is never persisted or logged — only the numeric
  status code and latency are retained.

## Read-fresh-then-act boundaries

Endpoint-disable and secret-rotation are both "read the current value,
then act" at the start of each attempt, not atomically locked against a
concurrent administrative change made mid-attempt. See
[Asynchronous delivery and outbound webhooks](../architecture/asynchronous-delivery-and-webhooks.md#read-fresh-then-act-boundaries-honest-limitations)
for the exact, honestly-stated boundary — this implementation does not
claim to be able to retroactively cancel or re-sign a request that has
already begun.
