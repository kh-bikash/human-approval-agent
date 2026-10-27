import pytest
from human_approval_agent.engine import ApprovalStore


def test_pause_approve_resume_audit(tmp_path):
    store = ApprovalStore(tmp_path / "approval.db")
    request = store.propose("email", {"to": "a@example.com"}, confidence=0.4)
    with pytest.raises(PermissionError):
        store.resume(request.id, executor=lambda *_: None)
    store.decide(request.id, actor="reviewer-1", approve=True)
    assert store.resume(request.id, executor=lambda action, payload: (action, payload["to"])) == ("email", "a@example.com")
    assert [event for _, event, _ in store.history(request.id)][-1] == "completed"
    with pytest.raises(PermissionError):
        store.resume(request.id, executor=lambda *_: None)


def test_rejection_is_terminal(tmp_path):
    store = ApprovalStore(tmp_path / "approval.db")
    request = store.propose("delete", {"id": 1}, confidence=0.1)
    assert store.decide(request.id, actor="owner", approve=False) == "rejected"
    with pytest.raises(PermissionError):
        store.resume(request.id, executor=lambda *_: None)


def test_idempotency_and_expiration(tmp_path):
    store = ApprovalStore(tmp_path / "approval.db")
    one = store.propose("send", {"x": 1}, confidence=0.1, idempotency_key="event-1", ttl_seconds=0.01)
    two = store.propose("send", {"x": 1}, confidence=0.1, idempotency_key="event-1")
    assert one.id == two.id
    with pytest.raises(ValueError):
        store.propose("send", {"x": 2}, confidence=0.1, idempotency_key="event-1")
    import time
    time.sleep(0.02)
    with pytest.raises(ValueError):
        store.decide(one.id, actor="reviewer", approve=True)
