from __future__ import annotations

import re

import mercure_admin_client as mercure


CLIENT_KINDS = {"account", "free"}
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def parse_subject_ref(value: object) -> tuple[str, str]:
    """Parse an opaque Mercure customer reference without accepting URL fragments.

    The rights engine persists only the SHA-256 of this raw reference. The
    ``kind:id`` value is supplied again by the operator when executing a request
    and is re-verified against that hash before this adapter is called. The
    provider identifier keeps its original case and is limited to path-safe
    characters already accepted by the mobile Mercure bindings.
    """
    raw = str(value or "").strip()
    if raw.count(":") != 1:
        raise ValueError("subjectRef Mercure invalide")
    client_kind_raw, client_id = raw.split(":", 1)
    client_kind = client_kind_raw.strip().lower()
    if client_kind not in CLIENT_KINDS:
        raise ValueError("subjectRef Mercure invalide")
    if not _CLIENT_ID_RE.fullmatch(client_id):
        raise ValueError("subjectRef Mercure invalide")
    return client_kind, client_id


def contact_snapshot(subject_ref: object) -> dict:
    """Return the bounded contact fields already exposed by the Mercure client.

    This deliberately does not return the raw provider object: doing so would
    couple data-subject exports to an undocumented provider schema and could
    expose internal fields. Vehicle and appointment coverage remains a separate
    follow-up and the result therefore declares itself partial.
    """
    client_kind, client_id = parse_subject_ref(subject_ref)
    session = mercure._session()
    contact = mercure._customer_contact(session, client_kind, client_id)
    email = str(contact.get("email") or "").strip()[:254]
    telephone = str(contact.get("telephone") or "").strip()[:40]
    return {
        "provider": "mercure",
        "subject": {
            "clientKind": client_kind,
            "clientId": client_id,
        },
        "contact": {
            "email": email,
            "telephone": telephone,
        },
        "coverage": {
            "contact": True,
            "vehicles": False,
            "appointments": False,
            "billing": False,
        },
        "partial": True,
    }
