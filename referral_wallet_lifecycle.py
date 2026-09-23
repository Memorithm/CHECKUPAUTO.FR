from __future__ import annotations

import hashlib
import json
import re
import uuid

import analytics_store as analytics
import mobile_devices
import referral_wallet_claims


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _installation_hash(installation_id: str) -> str:
    return hashlib.sha256(installation_id.encode("utf-8")).hexdigest()


def _init_mobile_erasure_receipts() -> None:
    """Create the privacy-minimised mobile erasure proof store.

    Receipts live in the same SQLite database as the mobile rows so deletion and
    proof creation can commit atomically. Only a SHA-256 installation reference,
    aggregate row counts and a hash of the canonical evidence are retained. APNs
    tokens, registration secrets and raw installation identifiers are never copied
    into the receipt table.
    """
    mobile_devices.init_db()
    with mobile_devices.connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS mobile_erasure_receipt(
              receipt_id TEXT PRIMARY KEY,
              installation_hash TEXT NOT NULL,
              evidence_hash TEXT NOT NULL UNIQUE,
              device_records INTEGER NOT NULL,
              deadline_records INTEGER NOT NULL,
              vehicle_binding_records INTEGER NOT NULL,
              erased_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mobile_erasure_installation
              ON mobile_erasure_receipt(installation_hash,erased_at,receipt_id);
            """
        )


def mobile_erasure_receipt_by_subject_hash(subject_hash: object) -> dict | None:
    """Return the latest non-identifying erasure proof for an exact mobile subject.

    The caller supplies the SHA-256 subject hash already used by the compliance
    request registry. This deliberately avoids accepting or returning a raw mobile
    installation identifier.
    """
    digest = str(subject_hash or "").strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError("subject hash invalide")
    _init_mobile_erasure_receipts()
    with mobile_devices.connect() as db:
        row = db.execute(
            """SELECT receipt_id,evidence_hash,device_records,deadline_records,
                      vehicle_binding_records,erased_at
               FROM mobile_erasure_receipt
               WHERE installation_hash=?
               ORDER BY erased_at DESC,receipt_id DESC LIMIT 1""",
            (digest,),
        ).fetchone()
    if not row:
        return None
    return {
        "receiptId": str(row["receipt_id"]),
        "evidenceHash": str(row["evidence_hash"]),
        "removed": {
            "deviceRecords": int(row["device_records"]),
            "deadlineRecords": int(row["deadline_records"]),
            "vehicleBindingRecords": int(row["vehicle_binding_records"]),
        },
        "erasedAt": str(row["erased_at"]),
        "rawInstallationPersisted": False,
        "pushTokenPersisted": False,
        "registrationSecretPersisted": False,
    }


def _release_installation_ownership(installation_id: str) -> dict:
    """Internal mutation for callers that have already verified the subject.

    The mobile API authenticates the installation secret before calling this;
    the rights engine re-verifies the request subject before its erasure adapter.
    This primitive must never be exposed as a raw-installation-ID public route.
    It deletes only ownership evidence, not wallet accounts, rewards or balances.
    Repeating it after an interrupted deletion is safe, including when the mobile
    row is already absent. Storage failures propagate so callers cannot report a
    successful erasure while ownership release has failed.
    """
    installation_id = mobile_devices._install_id(installation_id)
    referral_wallet_claims.init_db()
    installation_hash = _installation_hash(installation_id)
    with analytics.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        cursor = db.execute(
            "DELETE FROM referral_wallet_owner WHERE installation_hash=?",
            (installation_hash,),
        )
        released = max(0, int(cursor.rowcount or 0))

    return {
        "ok": True,
        "released": released,
        "rawInstallationPersisted": False,
    }


def release_for_authenticated_installation(payload: dict) -> dict:
    """Release wallet ownership evidence before deleting a mobile installation.

    The caller must prove the current installation identity. Only the SHA-256
    installation hash is used to locate durable wallet ownership evidence; neither
    the raw installation id nor registration secret is persisted in the wallet DB.
    This operation is intentionally performed before the mobile installation row is
    deleted so authentication cannot be bypassed or become impossible to retry.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload invalide")
    if set(payload) != {"installationId", "registrationSecret"}:
        raise ValueError("payload invalide")

    installation_id = mobile_devices._install_id(payload.get("installationId"))
    secret_hash = mobile_devices._hash(
        mobile_devices._secret(payload.get("registrationSecret"))
    )
    mobile_devices.init_db()
    with mobile_devices.connect() as db:
        mobile_devices._authenticated_installation(db, installation_id, secret_hash)

    return _release_installation_ownership(installation_id)


def _erase_authenticated_mobile(payload: dict) -> dict:
    """Delete one authenticated installation and atomically persist its proof.

    The receipt transaction is the crash boundary: after COMMIT, both the mobile
    rows are gone and their non-identifying evidence exists; before COMMIT, neither
    change is visible. A retry after a lost response therefore observes an absent
    installation without creating a second or synthetic receipt.
    """
    installation_id = mobile_devices._install_id(payload.get("installationId"))
    secret_hash = mobile_devices._hash(
        mobile_devices._secret(payload.get("registrationSecret"))
    )
    installation_hash = _installation_hash(installation_id)
    _init_mobile_erasure_receipts()
    with mobile_devices.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT secret_hash FROM mobile_device WHERE installation_id=?",
            (installation_id,),
        ).fetchone()
        if not row:
            return {"ok": True, "removed": False}
        if not hashlib.compare_digest(str(row["secret_hash"]), secret_hash):
            raise PermissionError("identité mobile refusée")

        device_count = int(
            db.execute(
                "SELECT COUNT(*) n FROM mobile_device WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"]
        )
        deadline_count = int(
            db.execute(
                "SELECT COUNT(*) n FROM mobile_deadline WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"]
        )
        binding_count = int(
            db.execute(
                "SELECT COUNT(*) n FROM mobile_vehicle_binding WHERE installation_id=?",
                (installation_id,),
            ).fetchone()["n"]
        )
        stamp = mobile_devices._now_iso()
        receipt_id = uuid.uuid4().hex
        evidence = {
            "receiptId": receipt_id,
            "installationHash": installation_hash,
            "removed": {
                "deviceRecords": device_count,
                "deadlineRecords": deadline_count,
                "vehicleBindingRecords": binding_count,
            },
            "erasedAt": stamp,
        }
        canonical = json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        evidence_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        db.execute("DELETE FROM mobile_deadline WHERE installation_id=?", (installation_id,))
        db.execute("DELETE FROM mobile_vehicle_binding WHERE installation_id=?", (installation_id,))
        db.execute("DELETE FROM mobile_device WHERE installation_id=?", (installation_id,))
        db.execute(
            """INSERT INTO mobile_erasure_receipt(
                 receipt_id,installation_hash,evidence_hash,device_records,
                 deadline_records,vehicle_binding_records,erased_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                receipt_id,
                installation_hash,
                evidence_hash,
                device_count,
                deadline_count,
                binding_count,
                stamp,
            ),
        )
    return {"ok": True, "removed": True}


def delete_installation(payload: dict) -> dict:
    """Release wallet ownership, then delete mobile data with durable evidence.

    Wallet ownership is released first while the installation can still be
    authenticated. Mobile deletion and its receipt then commit atomically in the
    mobile database. A wallet-release failure aborts before mobile deletion.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload invalide")
    if set(payload) != {"installationId", "registrationSecret"}:
        raise ValueError("payload invalide")

    installation_id = mobile_devices._install_id(payload.get("installationId"))
    secret_hash = mobile_devices._hash(
        mobile_devices._secret(payload.get("registrationSecret"))
    )
    _init_mobile_erasure_receipts()
    with mobile_devices.connect() as db:
        row = db.execute(
            "SELECT secret_hash FROM mobile_device WHERE installation_id=?",
            (installation_id,),
        ).fetchone()
        if not row:
            return {
                "ok": True,
                "removed": False,
                "referralWalletOwnershipReleased": 0,
            }
        if not hashlib.compare_digest(str(row["secret_hash"]), secret_hash):
            raise PermissionError("identité mobile refusée")

    release = _release_installation_ownership(installation_id)
    result = _erase_authenticated_mobile(payload)
    return {
        **result,
        "referralWalletOwnershipReleased": int(release["released"]),
    }
