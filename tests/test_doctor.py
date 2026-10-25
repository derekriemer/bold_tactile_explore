import httpx

from tactile_terrain import api, doctor
from tactile_terrain.config import config_path


def test_unreachable_endpoints_are_reported_without_crashing(monkeypatch):
    def refuse(*args, **kwargs):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "get", refuse)
    text = api.doctor()
    assert str(config_path()) in text
    assert text.count("unreachable (") == 4
    for name in ("3DEP", "NHDPlus HR", "Overpass", "Nominatim"):
        assert name in text
    assert "Tactile profile active: standard" in text and "louisville-library" in text


def test_reachable_and_error_statuses(monkeypatch):
    class Response:
        def __init__(self, status):
            self.status_code = status

    answers = iter([200, 503, 200, 200])
    monkeypatch.setattr(httpx, "get", lambda *a, **k: Response(next(answers)))
    text = api.doctor()
    assert text.count("reachable") >= 3 and "error status 503" in text


def test_slicer_line(monkeypatch):
    monkeypatch.setattr(doctor, "find_slicer", lambda: "C:/tools/prusa-slicer-console.exe")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: type("R", (), {"status_code": 200})())
    assert "Slicer: C:/tools/prusa-slicer-console.exe" in api.doctor()


def test_cli_doctor_prints_the_report(monkeypatch, capsys):
    from tactile_terrain import cli

    monkeypatch.setattr(httpx, "get", lambda *a, **k: type("R", (), {"status_code": 200})())
    assert cli.main(["doctor"]) == 0
    assert "Doctor report" in capsys.readouterr().out
