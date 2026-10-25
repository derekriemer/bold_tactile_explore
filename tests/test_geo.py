import numpy as np
import pytest

from tactile_terrain.geo import PrintTransform, utm_crs_for

WINTER_PARK = (-105.86, 39.79, -105.71, 39.96)


def _transform(**kw):
    args = {"scale_m_per_mm": 100, "z_exaggeration": 1.5, "base_mm": 3.0, "min_elevation_m": 2500.0}
    return PrintTransform.build(WINTER_PARK, **(args | kw))


def test_utm_zone_for_winter_park():
    assert utm_crs_for(WINTER_PARK) == "EPSG:32613"


def test_southern_hemisphere_zone():
    assert utm_crs_for((150.0, -34.0, 151.0, -33.0)) == "EPSG:32756"


def test_round_trip_within_a_micrometre():
    t = _transform()
    x, y = np.array([t.sw_x + 1234.5, t.sw_x + 9999.0]), np.array([t.sw_y + 77.7, t.sw_y + 5000.0])
    back_x, back_y = t.print_to_world(*t.world_to_print(x, y))
    assert np.allclose(back_x, x, atol=1e-6) and np.allclose(back_y, y, atol=1e-6)


def test_south_west_corner_is_origin():
    t = _transform()
    px, py = t.world_to_print(t.sw_x, t.sw_y)
    assert (float(px), float(py)) == (0.0, 0.0)


def test_minimum_elevation_maps_to_base():
    t = _transform()
    assert float(t.elevation_to_z(t.min_elevation_m)) == pytest.approx(3.0)


def test_thousand_metres_above_minimum():
    t = _transform()
    assert float(t.elevation_to_z(t.min_elevation_m + 1000)) == pytest.approx(3.0 + 15.0)


def test_z_round_trip():
    t = _transform()
    assert float(t.z_to_elevation(t.elevation_to_z(2789.0))) == pytest.approx(2789.0)


def test_long_side_derives_scale():
    t = PrintTransform.build(WINTER_PARK, long_side_mm=140)
    assert max(t.width_mm, t.height_mm) == pytest.approx(140)


def test_needs_a_scale():
    with pytest.raises(ValueError):
        PrintTransform.build(WINTER_PARK)
