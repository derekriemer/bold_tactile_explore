from dataclasses import replace

import pytest
from helpers import assert_printable
from synthetic import plane

from tactile_terrain.config import PrinterProfile
from tactile_terrain.geo import utm_crs_for
from tactile_terrain.pipeline import stages
from tactile_terrain.providers.base import ElevationGrid
from tactile_terrain.registry import elevation_providers
from tactile_terrain.spec import Spec

BBOX = [-105.80, 39.88, -105.76, 39.91]


class PlaneProvider:
    """Elevation rising 1 m per 10 m northwards, delivered in lon/lat so project reprojects."""

    def fetch(self, bbox, resolution_m):
        west, south, east, north = bbox
        n = 40
        res = (east - west) / n
        grid = plane(2500.0, slope_y=0.0, n=n, res=res, crs="EPSG:4326", x0=west, y0=north)
        for row in range(n):
            grid.data[row, :] = 2500.0 + (n - row) * 2.0
        return ElevationGrid(grid.data, grid.crs, west, north, res, (north - south) / n)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setitem(elevation_providers._items, "synthetic", PlaneProvider())


@pytest.fixture
def printer():
    return PrinterProfile(bed_mm=[152, 152, 158], nozzle_mm=0.5, grid_mm=1.0)


def _spec(**print_kw):
    p = {"printer": "louisville-library", "scale_m_per_mm": 40, "z_exaggeration": 1.5} | print_kw
    return Spec.model_validate(
        {
            "name": "synthetic",
            "area": {"bbox": BBOX},
            "print": p,
            "elevation": {"provider": "synthetic", "resolution_m": 10},
        }
    )


def _spied():
    calls = []

    def spy(stage):
        def wrapped(spec, upstream, ctx):
            calls.append(stage.name)
            return stage.func(spec, upstream, ctx)

        return replace(stage, func=wrapped)

    return calls, [spy(s) for s in stages.STAGES]


def test_second_run_runs_no_stage_again(tmp_path, provider, printer):
    calls, spied = _spied()
    stages.run_pipeline(_spec(), tmp_path, printer, spied)
    assert calls == [s.name for s in stages.STAGES]
    calls.clear()
    stages.run_pipeline(_spec(), tmp_path, printer, spied)
    assert calls == []


def test_changing_z_exaggeration_reruns_from_heightfield(tmp_path, provider, printer):
    calls, spied = _spied()
    stages.run_pipeline(_spec(), tmp_path, printer, spied)
    calls.clear()
    stages.run_pipeline(_spec(z_exaggeration=3.0), tmp_path, printer, spied)
    names = [s.name for s in stages.STAGES]
    assert calls == names[names.index("heightfield") :]
    assert "fetch" not in calls and "project" not in calls


def test_pipeline_builds_a_printable_model(tmp_path, provider, printer):
    import trimesh

    result = stages.run_pipeline(_spec(), tmp_path, printer)
    hf = result["heightfield"]
    assert hf.transform.crs == utm_crs_for(tuple(BBOX))
    assert hf.z.min() == pytest.approx(3.0)  # lowest point sits at base_mm
    mesh = trimesh.load(result["export"].path)
    assert_printable(mesh)


def test_flat_mode_needs_no_elevation(tmp_path, printer):
    spec = _spec().model_copy(update={"mode": "flat"})
    hf = stages.run_pipeline(spec, tmp_path, printer)["heightfield"]
    assert (hf.z == 3.0).all()
