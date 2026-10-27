# Architecture

## Goal

Pause uncertain actions, record human decisions, and resume only an approved immutable payload with an audit trail.

## Request path

Proposal -> SQLite pending checkpoint -> authenticated reviewer integration -> atomic status transition -> executor -> completed or failed audit event.

## Components

- `src/human_approval_agent/engine.py`: policy and state transitions for this project.

- `tests/test_engine.py`: deterministic behavior and failure tests.
- `.github/workflows/ci.yml`: install and test gate.


## State and failure behavior

The library records actor names but does not authenticate them; the integrating API must authenticate reviewers. External side effects need idempotency keys because a process crash during execution cannot be rolled back automatically.

The application should propagate failed operations to its caller or queue so the caller can decide whether to retry. Input and handler output are treated as untrusted at the integration boundary.

## Operations checklist

1. Set secrets through a secret manager and rotate them regularly.
2. Put the service or integrating application behind TLS and authentication.
3. Persist and back up the SQLite approval and audit store. Reconcile requests left in executing state against downstream idempotency records.
4. Run `pytest -q` in CI before deployment.
5. Define workload specific evaluation cases, latency objectives, and rollback criteria before serving real users.

## Durable approval state

`requests` stores the immutable action, canonical JSON payload, SHA-256 digest, status, timestamps, and expiry. `request_keys` maps caller idempotency keys to requests; replaying a key with different payload is rejected. `audit` stores actor, event, and time. Low confidence proposals pause as `pending`; higher confidence proposals become `approved` according to the caller's threshold. Expired requests cannot be approved or executed.

`decide` uses one transactional status transition and records the review event. `resume` atomically changes `approved` to `executing`, checks the digest, calls the supplied executor, then marks `completed` or `failed`. It will not execute the same request twice through the normal API. A process crash between an external side effect and the completion record can leave `executing`; an operator must reconcile it. Use the request ID as the external idempotency key. This package records reviewer identity but relies on an authenticated service to establish it.
