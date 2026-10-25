def assert_printable(mesh):
    """Every mesh we build must be a closed, consistently wound solid."""
    assert mesh.is_watertight, "mesh is not watertight"
    assert mesh.is_volume, "mesh is not a valid volume"
