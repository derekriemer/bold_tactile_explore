"""MCP server (stdio). Thin wrappers around api.py.

Server hygiene: only protocol messages go to stdout, logging goes to stderr, and heavy
libraries are imported inside the tools so the server starts quickly.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from typing import Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

INSTRUCTIONS = """\
Tactile terrain: turn a map area into a 3D-printable model a blind person can read by touch.
Every result is plain text; never rely on images. Workflow:
1. resolve_area: confirm the bounding box, size, elevation range and which features exist.
   Use the names it lists for include_names and include_refs filters.
2. Confirm the area, scale and printer with the user, then create_model.
   The reply includes analysis: warnings first, each with a Fix that update_model can apply.
3. describe_model: read the result back to the user and check it against what they know.
4. update_model for changes (z_multiply, crop_percent, drop_feature, revert_to, or any
   merge-patch of the spec). Every edit keeps the previous spec, so it can be undone.
5. check_print before sending a file to be printed.
Use list_capabilities to discover providers, filters and styles, list_models and get_spec to
see what already exists. Tactile numbers (line widths and heights, spacing) come from the
user's tactile profile and are never guessed.
"""

logger = logging.getLogger("tactile_terrain")
mcp = MCPServer("tactile-terrain", instructions=INSTRUCTIONS)


# Failures we expect (bad input, missing model, network trouble) reach the model as readable
# text. Anything else is a bug and the SDK reports it as a crash.
EXPECTED = (ValueError, KeyError, FileNotFoundError, FileExistsError)


def _message(error: Exception) -> str:
    return str(error.args[0]) if isinstance(error, KeyError) and error.args else str(error)


def _guarded(fn: Callable[..., str], *args: Any, **kwargs: Any) -> str:
    import httpx

    try:
        with redirect_stdout(sys.stderr):
            return fn(*args, **kwargs)
    except EXPECTED as error:
        raise ToolError(_message(error)) from error
    except httpx.HTTPError as error:
        raise ToolError(f"A data service could not be reached: {error}") from error


async def _in_thread(ctx: Context | None, fn: Callable[..., str], *args: Any, **kwargs: Any) -> str:
    """Run a long build off the event loop, reporting progress to the client."""

    def progress(stage: str, position: int, total: int) -> None:
        if ctx is not None:
            anyio.from_thread.run(ctx.report_progress, position, total, f"Running {stage}")

    return await anyio.to_thread.run_sync(
        lambda: _guarded(fn, *args, **kwargs, on_progress=progress)
    )


async def _quick(fn: Callable[..., str], *args: Any, **kwargs: Any) -> str:
    return await anyio.to_thread.run_sync(lambda: _guarded(fn, *args, **kwargs))


@mcp.tool()
async def resolve_area(
    place: str | None = None, bbox: list[float] | None = None, width_km: float | None = None
) -> str:
    """Describe an area before building: size, elevation range, available data, and the named
    streams, roads, lifts and peaks inside it. Give a place name (with width_km for a square
    around it) or a bbox [west, south, east, north] in degrees. Builds nothing."""
    from tactile_terrain import api

    return await _quick(api.resolve_area, place=place, bbox=bbox, width_km=width_km)


@mcp.tool()
async def create_model(
    name: str,
    bbox: list[float],
    features: list[dict[str, Any]],
    scale_m_per_mm: float | None = None,
    long_side_mm: float | None = None,
    z_exaggeration: float = 1.0,
    base_mm: float = 3.0,
    mode: str = "terrain",
    printer: str | None = None,
    tactile_profile: str | None = None,
    overwrite: bool = False,
    ctx: Context | None = None,
) -> str:
    """Create and build a model. bbox is [west, south, east, north] in degrees. Give exactly one
    of scale_m_per_mm or long_side_mm. mode is terrain or flat. Each feature is
    {type, provider, style, filter}; style names come from the tactile profile (see
    list_capabilities). Returns a build summary plus analysis with fixes."""
    from tactile_terrain import api

    print_settings: dict[str, Any] = {"z_exaggeration": z_exaggeration, "base_mm": base_mm}
    if scale_m_per_mm is not None:
        print_settings["scale_m_per_mm"] = scale_m_per_mm
    if long_side_mm is not None:
        print_settings["long_side_mm"] = long_side_mm
    if printer:
        print_settings["printer"] = printer
    return await _in_thread(
        ctx,
        api.create_model,
        name,
        area=bbox,
        print=print_settings,
        mode=mode,
        features=features,
        style={"tactile_profile": tactile_profile} if tactile_profile else None,
        overwrite=overwrite,
    )


@mcp.tool()
async def update_model(name: str, changes: dict[str, Any], ctx: Context | None = None) -> str:
    """Change a model and rebuild it. changes is a JSON merge-patch of the spec, plus the
    shortcuts z_multiply (factor), crop_percent ({north|south|east|west: percent}),
    drop_feature (type) and revert_to (earlier version number). Reports each change as
    before to after. An invalid change leaves the model untouched."""
    from tactile_terrain import api

    return await _in_thread(ctx, api.update_model, name, changes)


@mcp.tool()
async def describe_model(name: str, sections: list[dict[str, Any]] | None = None) -> str:
    """Read a model out as text: footprint, scale, high and low points, the course of every
    line, crossings, cross-sections, the tactile legend and distortion. sections adds extra
    cross-sections: {"y_mm": 40}, {"x_mm": 60} or {"through": "Second Creek", "direction":
    "EW"}."""
    from tactile_terrain import api

    return await _quick(api.describe_model, name, sections)


@mcp.tool()
async def analyze_model(name: str) -> str:
    """Metrics and suggestions for a built model: warnings first, each with its fix."""
    from tactile_terrain import api

    return await _quick(api.analyze_model, name)


@mcp.tool()
async def check_print(name: str) -> str:
    """Check a model is printable: watertight, volume and filament (an upper bound), print time
    when a slicer is installed, and minimum feature and bed-fit problems. Also writes the
    print pack (STL, attribution, print notes, submission notes) next to the model."""
    from tactile_terrain import api

    return await _quick(api.check_print, name)


@mcp.tool()
async def doctor() -> str:
    """Report the installation: versions, config path, models folder, which data services
    are reachable, and whether a slicer is available."""
    from tactile_terrain import api

    return await _quick(api.doctor)


@mcp.tool()
async def list_capabilities() -> str:
    """Every provider, filter, style, analyzer and printer this installation supports."""
    from tactile_terrain import api

    return await _quick(api.list_capabilities)


@mcp.tool()
async def list_models() -> str:
    """The models that already exist."""
    from tactile_terrain import api

    return await _quick(api.list_models)


@mcp.tool()
async def get_spec(name: str) -> str:
    """The current spec of a model, as JSON text."""
    from tactile_terrain import api

    return await _quick(api.get_spec, name)


def run() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(message)s")
    logger.info("tactile-terrain MCP server starting")
    mcp.run("stdio")
