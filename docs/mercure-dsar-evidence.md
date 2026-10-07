# Mercure DSAR provider evidence

This runbook documents the fail-closed evidence boundary used by `mercure_provider_coverage.py`. It does **not** assert that Mercure guarantees exhaustive data coverage. Provider or contract evidence must exist outside this repository before an operator enables an attestation.

## Why the boundary is split

A date window and a subject-level inventory are different claims. A configured historical start and future horizon can describe **when** CheckupAuto queries Mercure, but they do not prove that the observed appointment calendar is the provider's exhaustive inventory for that subject. Vehicle inventory authority is another independent claim.

CheckupAuto therefore requires separate evidence for:

1. the temporal query boundary;
2. the authority/completeness of the subject appointment inventory source;
3. the subject-to-vehicle inventory source when vehicle completeness is required.

An empty provider response, an observed endpoint, or a locally empty residual store is never sufficient evidence by itself.

## Runtime configuration

Two bounded configuration paths are supported. Environment variables remain authoritative when any Mercure DSAR coverage variable is present. Otherwise, an MFA-authenticated administrator may use the **Compliance Center → Frontière DSAR Mercure · preuves externes** form, backed by the private runtime file `integrations/mercure-provider-coverage.json`.

The private form stores only the reviewed historical date, future horizon, implementation-supported source identifiers, and SHA-256 evidence digests. Evidence files selected in the browser are hashed locally with Web Crypto and their raw bytes are never uploaded to CheckupAuto. The private file is outside Git and is written atomically with restrictive permissions. Deleting it removes only the private configuration; it cannot override an environment-managed configuration.

For environment-managed deployments, configure these variables only from the deployment secret/configuration layer. Do not commit provider documents, credentials, API payloads, customer data, or raw contractual evidence to Git.

### Temporal boundary

- `CYBERCHECK_MERCURE_DSAR_HISTORY_START`: ISO date (`YYYY-MM-DD`) representing the externally evidenced historical start.
- `CYBERCHECK_MERCURE_DSAR_FUTURE_DAYS`: integer future horizon. The implementation rejects negative values and values above its bounded maximum.
- `CYBERCHECK_MERCURE_DSAR_COVERAGE_EVIDENCE_SHA256`: lowercase SHA-256 of the external evidence supporting the temporal boundary.

### Subject appointment inventory

- `CYBERCHECK_MERCURE_DSAR_APPOINTMENT_INVENTORY_SOURCE`: must equal the implementation-supported identifier `subject_bound_appointment_calendar`.
- `CYBERCHECK_MERCURE_DSAR_APPOINTMENT_INVENTORY_EVIDENCE_SHA256`: lowercase SHA-256 of external provider/contract evidence establishing that this source is the authoritative complete subject-level appointment inventory for the intended DSAR scope.

A valid temporal boundary without this independent appointment-inventory evidence remains **unattested**. Partial, unsupported, or malformed appointment evidence fails closed.

### Subject vehicle inventory

- `CYBERCHECK_MERCURE_DSAR_VEHICLE_INVENTORY_SOURCE`: must equal the implementation-supported identifier `appointment_calendar_subject_vehicle_set`.
- `CYBERCHECK_MERCURE_DSAR_VEHICLE_INVENTORY_EVIDENCE_SHA256`: lowercase SHA-256 of external evidence establishing that this relation is the authoritative complete subject-to-vehicle set for the intended DSAR scope.

Vehicle evidence is independent from appointment evidence. Observing vehicle IDs on appointments does not, by itself, prove that every vehicle for the subject has been discovered.

## Safe evidence procedure

1. Obtain a provider document, signed contract/addendum, API specification, or equivalent auditable source that states the exact coverage claim being relied upon.
2. Keep that evidence in the approved external compliance/document system. Do not add it to this repository.
3. Compute a SHA-256 digest of the exact evidence artifact through the controlled operator environment.
4. Configure only the supported source identifier and the lowercase SHA-256 digest, either through the deployment configuration or the MFA-protected Compliance Center form. When using the form, review the displayed authoritative source identifier and tick the explicit confirmation only after the external evidence actually supports that claim.
5. Reload the Compliance Center and confirm that the provider boundary reports the expected state. `attested` means the configured evidence gates passed; it does not override runtime read failures, truncation checks, or the separate vehicle gate.
6. If evidence changes, recompute the digest and repeat the review. Do not reuse a digest for a materially different document or scope.

## Operator self-check

The following command prints only bounded configuration state from the implementation. It does not read or emit raw provider evidence:

```bash
python3 - <<'PY'
import json
import mercure_provider_coverage as coverage

print(json.dumps({
    "boundary": coverage.boundary(),
    "capability": coverage.capability(),
}, indent=2, sort_keys=True))
PY
```

Expected fail-closed states include `unconfigured` when required evidence has not been provided and `invalid` when supplied configuration is incomplete, unsupported, or malformed.

## What this does not prove

This configuration does not invent or discover a Mercure capability. In particular, it does not establish a provider-backed mutation API for customer contact data or technical-inspection deadlines, and it does not make `GLOBAL_COVERAGE_COMPLETE` true. Stores that depend on a complete Mercure subject inventory must remain partial until the corresponding provider evidence and runtime conditions are actually satisfied.
