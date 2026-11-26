# Contributing

Read [docs/design-invariants.md](docs/design-invariants.md) first. Those decisions are deliberate and must not be undone by a refactor.

Run `uv run pytest -q` and `uv run ruff check` before committing.

## Dependency licences

Checked at M0 (2026-10-24): every runtime and dev dependency in `uv.lock` is MIT, BSD, Apache-2.0, PSF, MPL-2.0 or similar permissive. None is GPL-2.0-only or proprietary. Apache-2.0 and MPL-2.0 are compatible with AGPL-3.0-or-later. Re-check when adding a dependency.

Re-checked 2026-11-25 when adding `scikit-image` and `skan` for dashed lines. Every new package is BSD (scikit-image, skan, numba, llvmlite, pandas, networkx, imageio, tifffile, toolz, lazy-loader, contourpy, cycler, kiwisolver), MIT or MIT-CMU (openpyxl, et-xmlfile, fonttools, pillow), PSF-based (matplotlib), or MPL-2.0 and MIT (tqdm). None is GPL-2.0-only or proprietary.
