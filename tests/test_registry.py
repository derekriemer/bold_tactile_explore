import subprocess
from importlib.metadata import EntryPoint

import pytest

from tactile_terrain import registry
from tactile_terrain.registry import Registry


def test_register_and_get():
    r = Registry("widgets")
    r.register("a", 1)
    assert r.get("a") == 1
    assert r.names() == ["a"]


def test_unknown_name_lists_valid_names():
    r = Registry("widgets")
    r.register("alpha", 1)
    r.register("beta", 2)
    with pytest.raises(KeyError) as exc:
        r.get("gamma")
    assert "alpha" in str(exc.value) and "beta" in str(exc.value)


def test_entry_point_loading(monkeypatch):
    ep = EntryPoint(name="demo", value="math:pi", group="tactile_terrain.widgets")

    def fake_entry_points(group):
        return [ep] if group == "tactile_terrain.widgets" else []

    monkeypatch.setattr(registry, "entry_points", fake_entry_points)
    r = Registry("widgets")
    r.load_entry_points()
    assert r.get("demo") == pytest.approx(3.14159, abs=1e-4)


def test_all_registries_present():
    assert len(registry.ALL_REGISTRIES) == 9


def test_cli_help_lists_subcommands():
    out = subprocess.run(
        ["uv", "run", "tactile-terrain", "--help"], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0
    for name in ("mcp", "build", "doctor"):
        assert name in out.stdout
