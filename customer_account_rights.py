from __future__ import annotations

import hashlib
import json
from pathlib import Path

import customer_account_erasure_plan
import customer_accounts
import customer_ct_reports
import data_subject_rights


ADAPTER="customer_account"
SUPPORTED_RIGHTS=("access","portability","erasure")


def _email(value: object) -> str:
    return customer_accounts._email(value)


def _account(email: str):
    customer_accounts.init_db()
    digest=customer_accounts._hmac("email",email)
    with customer_accounts._connect() as db:
        row=db.execute(
            """SELECT account_id,kind,email_hash,profile_blob,wallet_code,created_at,updated_at
               FROM customer_account WHERE email_hash=?""",
            (digest,),
        ).fetchone()
        if not row:
            return None, []
        identities=db.execute(
            """SELECT provider,created_at,last_login_at
               FROM customer_identity WHERE account_id=? ORDER BY provider""",
            (str(row["account_id"]),),
        ).fetchall()
    return row,identities


def _report_rows(account_id: str):
    customer_ct_reports.init_db()
    with customer_ct_reports._connect() as db:
        return db.execute(
            """SELECT report_id,account_id,document_hash,content_type,payload_blob,created_at,updated_at
               FROM customer_ct_report WHERE account_id=? ORDER BY created_at,report_id""",
            (account_id,),
        ).fetchall()


def snapshot(subject_email: object) -> dict:
    email=_email(subject_email)
    row,identities=_account(email)
    if row is None:
        return {
            "account":None,
            "identities":[],
            "reports":[],
            "identityCount":0,
            "reportCount":0,
            "lookup":"hmac_normalized_email",
            "localCoverageComplete":True,
        }

    account_id=str(row["account_id"])
    profile=customer_accounts._decrypt_profile(account_id,row["profile_blob"])
    reports=[]
    for report in _report_rows(account_id):
        payload=customer_ct_reports._decrypt(report)
        reports.append({
            "reportId":str(report["report_id"]),
            "documentHash":str(report["document_hash"]),
            "contentType":str(report["content_type"]),
            "createdAt":str(report["created_at"]),
            "updatedAt":str(report["updated_at"]),
            "payload":payload,
        })
    return {
        "account":{
            "accountId":account_id,
            "kind":str(row["kind"]),
            "displayName":str(profile.get("displayName") or ""),
            "email":str(profile.get("email") or ""),
            "companyName":str(profile.get("companyName") or ""),
            "siret":str(profile.get("siret") or ""),
            "phone":str(profile.get("phone") or ""),
            "addressLine1":str(profile.get("addressLine1") or ""),
            "addressLine2":str(profile.get("addressLine2") or ""),
            "postalCode":str(profile.get("postalCode") or ""),
            "city":str(profile.get("city") or ""),
            "walletCode":str(row["wallet_code"] or ""),
            "createdAt":str(row["created_at"]),
            "updatedAt":str(row["updated_at"]),
        },
        "identities":[
            {
                "provider":str(identity["provider"]),
                "createdAt":str(identity["created_at"]),
                "lastLoginAt":str(identity["last_login_at"]),
            }
            for identity in identities
        ],
        "reports":reports,
        "identityCount":len(identities),
        "reportCount":len(reports),
        "lookup":"hmac_normalized_email",
        "localCoverageComplete":True,
    }


def erase(
    request_id: object,
    subject_email: object,
) -> dict:
    rid=data_subject_rights._request_id(request_id)
    email=_email(subject_email)
    plan=customer_account_erasure_plan.load(rid,email)
    row,identities=_account(email)

    if plan is None and row is None:
        return {
            "removedAccountCount":0,
            "removedIdentityCount":0,
            "removedReportCount":0,
            "remainingAccountCount":0,
            "remainingIdentityCount":0,
            "remainingReportCount":0,
            "recoveredFromPlan":False,
        }

    if plan is None:
        account_id=str(row["account_id"])
        reports=_report_rows(account_id)
        plan=customer_account_erasure_plan.stage(
            rid,
            email,
            account_id,
            identity_count=len(identities),
            report_count=len(reports),
        )
        recovered=False
    else:
        account_id=str(plan["accountId"])
        recovered=row is None

    customer_ct_reports.init_db()
    with customer_ct_reports._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        removed_reports=int(db.execute(
            "DELETE FROM customer_ct_report WHERE account_id=?",
            (account_id,),
        ).rowcount or 0)
        remaining_reports=int(db.execute(
            "SELECT COUNT(*) n FROM customer_ct_report WHERE account_id=?",
            (account_id,),
        ).fetchone()["n"])
        if remaining_reports:
            raise RuntimeError("effacement rapports client incomplet")

    customer_accounts.init_db()
    with customer_accounts._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        before_identity=int(db.execute(
            "SELECT COUNT(*) n FROM customer_identity WHERE account_id=?",
            (account_id,),
        ).fetchone()["n"])
        removed_account=int(db.execute(
            "DELETE FROM customer_account WHERE account_id=?",
            (account_id,),
        ).rowcount or 0)
        remaining_account=int(db.execute(
            "SELECT COUNT(*) n FROM customer_account WHERE account_id=?",
            (account_id,),
        ).fetchone()["n"])
        remaining_identity=int(db.execute(
            "SELECT COUNT(*) n FROM customer_identity WHERE account_id=?",
            (account_id,),
        ).fetchone()["n"])
        remaining_sessions=int(db.execute(
            "SELECT COUNT(*) n FROM customer_session WHERE account_id=?",
            (account_id,),
        ).fetchone()["n"])
        remaining_passages=int(db.execute(
            "SELECT COUNT(*) n FROM customer_passage_confirmation WHERE account_id=?",
            (account_id,),
        ).fetchone()["n"])
        if any((remaining_account,remaining_identity,remaining_sessions,remaining_passages)):
            raise RuntimeError("effacement compte client incomplet")

    removed_identity=before_identity
    return {
        "removedAccountCount":removed_account,
        "removedIdentityCount":removed_identity,
        "removedReportCount":removed_reports,
        "remainingAccountCount":remaining_account,
        "remainingIdentityCount":remaining_identity,
        "remainingReportCount":remaining_reports,
        "recoveredFromPlan":recovered,
        "plannedIdentityCount":int(plan["identityCount"]),
        "plannedReportCount":int(plan["reportCount"]),
    }


def execute(
    request_id: object,
    subject_ref: object,
    db_path: Path | str | None = None,
) -> dict:
    rid=data_subject_rights._request_id(request_id)
    row=data_subject_rights._request(rid,db_path)
    if str(row["status"]) not in {"open","in_progress"}:
        raise RuntimeError("demande non exécutable")
    request_type=str(row["request_type"])
    if request_type not in SUPPORTED_RIGHTS:
        raise NotImplementedError("type de droit non pris en charge par cet adaptateur")
    raw_ref=str(subject_ref or "").strip()
    data_subject_rights._verify_subject(row,raw_ref,ADAPTER,db_path)
    email=_email(raw_ref)
    if data_subject_rights._adapter_executed(rid,ADAPTER,db_path):
        raise RuntimeError("adaptateur déjà exécuté pour cette demande")

    if request_type in {"access","portability"}:
        data=snapshot(email)
        evidence={
            "requestId":rid,
            "requestType":request_type,
            "adapter":ADAPTER,
            "identityCount":int(data["identityCount"]),
            "reportCount":int(data["reportCount"]),
            "accountPresent":data["account"] is not None,
            "localCoverageComplete":True,
            "exportHash":hashlib.sha256(
                json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
            ).hexdigest(),
        }
        execution_id=data_subject_rights._audit_execution(
            row,ADAPTER,"export_complete",evidence,db_path
        )
        return {
            "ok":True,
            "requestId":rid,
            "requestType":request_type,
            "adapter":ADAPTER,
            "format":"application/json",
            "data":data,
            "executionId":execution_id,
            "requestStatus":"in_progress",
            "requestComplete":False,
        }

    erased=erase(rid,email)
    evidence={
        "requestId":rid,
        "requestType":request_type,
        "adapter":ADAPTER,
        "removedAccountCount":int(erased["removedAccountCount"]),
        "removedIdentityCount":int(erased["removedIdentityCount"]),
        "removedReportCount":int(erased["removedReportCount"]),
        "remainingAccountCount":0,
        "remainingIdentityCount":0,
        "remainingReportCount":0,
        "recoveredFromPlan":bool(erased["recoveredFromPlan"]),
    }
    execution_id=data_subject_rights._audit_execution(
        row,ADAPTER,"erasure_complete",evidence,db_path
    )
    plan_cleared=customer_account_erasure_plan.clear(rid,email)
    return {
        "ok":True,
        "requestId":rid,
        "requestType":request_type,
        "adapter":ADAPTER,
        **erased,
        "planCleared":bool(plan_cleared),
        "executionId":execution_id,
        "requestStatus":"in_progress",
        "requestComplete":False,
    }


def capability() -> dict:
    return {
        "adapter":ADAPTER,
        "bound":True,
        "partial":False,
        "supportedRights":list(SUPPORTED_RIGHTS),
        "subjectKind":"email",
        "exactNormalizedEmailRequired":True,
        "accountProfileEncryptedAtRest":True,
        "reportPayloadEncryptedAtRest":True,
        "erasurePlanEncryptedAtRest":True,
        "rawSubjectPersistedByAdapter":False,
        "auditStoresEvidenceHashOnly":True,
        "coveredStores":["customer_account","customer_identity","customer_ct_report"],
    }
