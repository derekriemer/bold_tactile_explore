# Contributing

Read [docs/design-invariants.md](docs/design-invariants.md) first. Those decisions are deliberate and must not be undone by a refactor.

Run `uv run pytest -q` and `uv run ruff check` before committing.

## Dependency licences

Checked at M0 (2026-10-24): every runtime and dev dependency in `uv.lock` is MIT, BSD, Apache-2.0, PSF, MPL-2.0 or similar permissive. None is GPL-2.0-only or proprietary. Apache-2.0 and MPL-2.0 are compatible with AGPL-3.0-or-later. Re-check when adding a dependency.
