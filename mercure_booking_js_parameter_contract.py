"""Read-only qualification of observed Mercure JavaScript booking parameter."""
from __future__ import annotations

from mercure_booking_write_form_contract import audit


class MercureJavascriptContractError(ValueError):
    pass


def qualify_observation(*, html_fields: object, javascript_source: str) -> dict:
    if not isinstance(javascript_source,str) or len(javascript_source)>5000000:
        raise MercureJavascriptContractError("mercure_javascript_source_invalid")
    observed=audit(html_fields)
    # These strings must coexist in the provider's observed inline submit
    # handler. They do not prove backend acceptance or authorization.
    js_observed=all(fragment in javascript_source for fragment in (
        "function addRendezVous(tcheckDispo = true)",
        "'tcheckDispo' : tcheckDispo",
        'url: "rendez_vous_add"',
    ))
    return {
        "htmlContractObserved":observed.contract_observed,
        "javascriptParameterObserved":js_observed,
        "customerWriteQualified":False,
        "productionWriteEnabled":False,
    }
