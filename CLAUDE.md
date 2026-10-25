# bold_tactile_explore

Tactile terrain printing tool: a Python MCP server plus a Claude plugin and skill. The intent is in `docs/design-spec.md` and the decisions are in `plans/` (start with `plans/README.md`). The design invariants in the handoff are non-negotiable.

The user is blind and uses NVDA. Report results as plain structured text, and never ask them to look at anything.

## Working cost-efficiently

The user is on a plan with usage limits. The build runs on Sonnet, so keep usage low.

- **One milestone per session.** The plans are the handoff, so start each milestone (M0–M12 in `plans/phase-1-mvp.md`) in a fresh session instead of carrying a long history forward. Long context is the main cost.
- **Read narrowly.** Read the plan section for the current milestone, not every plan file. Use Grep or Glob and read the line ranges you need.
- **Subagents only for broad, read-only lookups** whose details you don't need to keep, such as:
  - checking a library's current API (py3dep, pynhd, FastMCP, manifold3d)
  - searching several docs pages
  - surveying many files

  Pass `model: "haiku"` for these, and ask for a short answer such as a function signature or a yes/no with a citation. Don't spawn a subagent for something a few direct tool calls can do, because each one starts cold.
- **Don't re-download data.** Tests use synthetic grids and the cached golden tile, and real-data runs reuse `cache/`. Mark network tests (`@pytest.mark.network`) and leave them out of the default run.
- **Keep test output short.** Use `uv run pytest -q`, and rerun only the failing test while iterating.
- **Don't overthink the plans.** They already settle the architecture. Follow them, and ask the user only when a plan is wrong or silent on something.

## Commands

- Python runs only through `uv`, because `python` is not on PATH: `uv run pytest -q`, `uv run tactile-terrain ...`
- Shell: PowerShell is primary on Windows, and Git Bash is available.
