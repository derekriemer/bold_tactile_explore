# Golden fingerprints

Fingerprints (`.json` summary and `.npz` height raster, made by `tests/golden.py`) of these STLs. The STLs themselves live outside the repo.

| Fingerprint | Source STL | Made by |
|---|---|---|
| `tilden_off` | `drive-download-20261106T205231Z-1-001/tilden_berkeley_sample/print-pack/tilden_berkeley_sample.stl` | tactile-terrain 0.1.0, before dashing existed (checked by hand) |
| `tilden_dashed_2mm` | `additions/golden/tilden_dashed_2mm_v1.stl` | dash-trails 1.0.0, `--height 2`, run on the STL above (the fork's default) |
| `tilden_dashed_1mm` | `additions/golden/tilden_dashed_1mm_v1.stl` | dash-trails 1.0.0, `--height 1`, run on the STL above |

`tilden_spec.json` is that model's spec. `../tilden-cache/` holds its recorded source data, so the model builds offline.

To remake the fingerprints, from this repo's root:

```bash
uv run python tests/fixtures/golden/make_golden.py
```
