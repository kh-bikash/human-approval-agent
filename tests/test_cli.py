import json

from human_approval_agent.__main__ import main


def test_cli_reviews_and_writes_file(tmp_path, capsys):
    prefix = [
        "--db",
        str(tmp_path / "approvals.sqlite3"),
        "--outdir",
        str(tmp_path / "out"),
    ]
    assert main(prefix + ["propose", "report.txt", "approved"]) == 0
    request_id = json.loads(capsys.readouterr().out)["id"]
    assert main(prefix + ["approve", request_id, "--actor", "reviewer"]) == 0
    capsys.readouterr()
    assert main(prefix + ["execute", request_id]) == 0
    assert (tmp_path / "out" / "report.txt").read_text() == "approved"
