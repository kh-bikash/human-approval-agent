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
