from tactile_terrain.config import config_path, load_config


def test_first_load_creates_file_and_second_reads_it_back():
    assert not config_path().exists()
    first = load_config()
    assert config_path().exists()
    assert first.active_profile == "standard"
    assert first.default_printer == "louisville-library"
    assert first.models_dir == "~/TactileModels"
    printer = first.printers["louisville-library"]
    assert printer.bed_mm == [152, 152, 158]
    assert printer.max_print_hours == 8
    assert load_config() == first


def test_edits_are_read_back():
    load_config()
    path = config_path()
    path.write_text(path.read_text().replace('"standard"', '"coarse"'), encoding="utf-8")
    assert load_config().active_profile == "coarse"
