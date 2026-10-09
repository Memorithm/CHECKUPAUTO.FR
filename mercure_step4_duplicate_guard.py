"""Pure decision gate for ambiguous booking outcomes; never replay a provider write."""
def next_action(state, *, provider_reference=None):
    if state=="prepared" and provider_reference is None:
        return "create_once"
    if state in ("reconciliation_required","confirmed"):
        return "read_only"
    raise ValueError("booking_state_unrecognized")
