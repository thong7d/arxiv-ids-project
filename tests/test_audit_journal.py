import copy

import pytest

from ids_arxiv.audit_journal import AuditJournal


class MemoryIO:
    def __init__(self):
        self.files = {}
        self.fail_index = False

    def call(self, request):
        path = request["path"]
        if request["action"] == "read_json":
            return copy.deepcopy(self.files.get(path, request.get("default")))
        if self.fail_index and path.endswith("index.json"):
            raise OSError("Disconnected before index commit")
        self.files[path] = copy.deepcopy(request["value"])
        return True


def test_checkpoint_survives_vm_change_and_preserves_revisions(tmp_path):
    io = MemoryIO()
    journal = AuditJournal(io, tmp_path, {"owner": "a"}, ["x", "y"])
    journal.remember({"arxiv_id": "x", "classification": "pending"})
    journal.flush()
    recovered = AuditJournal(io, tmp_path, {"owner": "a"}, ["x", "y"])
    assert recovered.load()["x"]["classification"] == "pending"
    recovered.remember({"arxiv_id": "x", "classification": "full_success"})
    recovered.remember({"arxiv_id": "y", "classification": "verified_exception"})
    recovered.flush()
    third = AuditJournal(io, tmp_path, {"owner": "a"}, ["x", "y"])
    assert len(third.load()) == 2
    assert third.rows["x"]["classification"] == "full_success"
    assert not AuditJournal(io, tmp_path, {"owner": "b"}, ["x", "y"]).load()


def test_interrupted_upload_does_not_acknowledge_or_lose_old_checkpoint(tmp_path):
    io = MemoryIO()
    journal = AuditJournal(io, tmp_path, {}, ["x", "y"])
    journal.remember({"arxiv_id": "x"})
    journal.flush()
    journal.remember({"arxiv_id": "y"})
    io.fail_index = True
    with pytest.raises(OSError):
        journal.flush()
    recovered = AuditJournal(io, tmp_path, {}, ["x", "y"])
    assert set(recovered.load()) == {"x"}
    assert "y" in journal.pending


def test_tampering_and_wrong_owner_ids_are_rejected(tmp_path):
    io = MemoryIO()
    journal = AuditJournal(io, tmp_path, {}, ["x"])
    with pytest.raises(ValueError):
        journal.remember({"arxiv_id": "other"})
    journal.remember({"arxiv_id": "x"})
    journal.flush()
    name = journal.parts[0]["name"]
    io.files[str(tmp_path / name)]["records"]["x"]["classification"] = "full_success"
    with pytest.raises(ValueError, match="integrity"):
        AuditJournal(io, tmp_path, {}, ["x"]).load()
