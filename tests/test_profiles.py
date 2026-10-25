import pytest
from pydantic import ValidationError

from tactile_terrain.config import profiles_dir
from tactile_terrain.tactile.profile import PRESET_NAMES, TactileProfile, load_profile

MEDICAL_TERMS = ["diabetic", "neuropathy", "condition", "diagnosis"]


@pytest.mark.parametrize("name", PRESET_NAMES)
def test_presets_load(name):
    assert load_profile(name).name == name


def test_coarse_presets_drop_pointed():
    assert "pointed" in load_profile("standard").distinguishable_profiles
    for name in ("coarse", "extra_coarse"):
        assert "pointed" not in load_profile(name).distinguishable_profiles


def _write_user(name, text):
    profiles_dir().mkdir(parents=True, exist_ok=True)
    (profiles_dir() / f"{name}.toml").write_text(text, encoding="utf-8")


def test_user_profile_extends_and_overrides():
    _write_user(
        "mine",
        'extends = "standard"\n'
        "min_line_width_mm = 1.8\n"
        "[lines]\n"
        'flat_top = { profile = "flat_top", width_mm = 2.4, height_mm = 1.5 }\n',
    )
    mine, base = load_profile("mine"), load_profile("standard")
    assert mine.name == "mine"
    assert mine.min_line_width_mm == 1.8
    assert mine.lines["flat_top"].width_mm == 2.4
    assert mine.lines["rounded_major"] == base.lines["rounded_major"]
    assert mine.min_relief_mm == base.min_relief_mm


def test_extends_cycle_raises():
    _write_user("a", 'extends = "b"\n')
    _write_user("b", 'extends = "a"\n')
    with pytest.raises(ValueError, match="cycle"):
        load_profile("a")


def test_pointed_height_below_half_width_raises():
    _write_user(
        "spiky",
        'extends = "standard"\n'
        "[lines]\n"
        'pointed = { profile = "pointed", width_mm = 2.0, height_mm = 0.5 }\n',
    )
    with pytest.raises(ValidationError, match="half"):
        load_profile("spiky")


def test_unknown_profile_lists_valid_names():
    with pytest.raises(KeyError, match="extra_coarse"):
        load_profile("nope")


def _field_names(model):
    for name, field in model.model_fields.items():
        yield name
        ann = field.annotation
        for arg in (ann, *getattr(ann, "__args__", ())):
            if hasattr(arg, "model_fields"):
                yield from _field_names(arg)


def test_no_medical_terms_in_profile_fields():
    """Invariant 6: profiles never collect health information."""
    for name in _field_names(TactileProfile):
        assert not any(term in name.lower() for term in MEDICAL_TERMS), name
    for preset in PRESET_NAMES:
        text = str(load_profile(preset).model_dump()).lower()
        assert not any(term in text for term in MEDICAL_TERMS), preset
