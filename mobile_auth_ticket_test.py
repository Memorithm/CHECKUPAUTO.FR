import mobile_auth_ticket
import pytest

def test_ticket_is_single_use(tmp_path,monkeypatch):
    monkeypatch.setenv("CYBERCHECK_DATA_DIR",str(tmp_path))
    ticket=mobile_auth_ticket.issue("opaque-session")
    assert mobile_auth_ticket.consume(ticket)=="opaque-session"
    with pytest.raises(PermissionError):
        mobile_auth_ticket.consume(ticket)
