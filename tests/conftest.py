import pytest


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Every test gets its own config directory."""
    monkeypatch.setenv("TACTILE_TERRAIN_CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path / "cfg"
