import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tactile_terrain.spec import Spec, load_spec, save_spec, validate_registry_names

EXAMPLE = Path(__file__).parent.parent / "examples" / "winter-park.json"


def _data():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_example_round_trips_byte_identically(tmp_path):
    out = tmp_path / "spec.json"
    save_spec(load_spec(EXAMPLE), out)
    assert out.read_bytes() == EXAMPLE.read_bytes()


def test_unknown_top_level_key_names_the_key():
    data = _data() | {"bogus_key": 1}
    with pytest.raises(ValidationError, match="bogus_key"):
        Spec.model_validate(data)


def test_unknown_nested_key_names_the_key():
    data = _data()
    data["print"]["wobble"] = 3
    with pytest.raises(ValidationError, match="wobble"):
        Spec.model_validate(data)


def test_both_scale_and_long_side_raises():
    data = _data()
    data["print"]["long_side_mm"] = 140
    with pytest.raises(ValidationError, match="exactly one"):
        Spec.model_validate(data)


def test_neither_scale_nor_long_side_raises():
    data = _data()
    del data["print"]["scale_m_per_mm"]
    with pytest.raises(ValidationError, match="exactly one"):
        Spec.model_validate(data)


def test_reserved_keys_accepted():
    data = _data() | {"regions": [{"x": 1}], "textures": [{"y": 2}], "tiles": {"z": 3}}
    spec = Spec.model_validate(data)
    assert spec.tiles == {"z": 3}


def test_unknown_profile_and_printer_list_valid_names():
    data = _data()
    data["style"]["tactile_profile"] = "nope"
    with pytest.raises(ValueError, match="standard"):
        validate_registry_names(Spec.model_validate(data))
    data = _data()
    data["print"]["printer"] = "nope"
    with pytest.raises(KeyError, match="louisville-library"):
        validate_registry_names(Spec.model_validate(data))
    validate_registry_names(Spec.model_validate(_data()))
