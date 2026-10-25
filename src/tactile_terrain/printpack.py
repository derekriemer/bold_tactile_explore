"""check_print pieces: mesh report, slicer step, and the print pack for whoever prints it."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import trimesh

from tactile_terrain.config import PrinterProfile

SLICER_NAMES = ("prusa-slicer-console", "prusa-slicer", "orca-slicer-console", "orca-slicer")
MM3_PER_CM3 = 1000
SLICE_TIMEOUT_S = 900
LAYER_HEIGHT_NOTE = "0.2 to 0.3 mm"  # printing advice for staff, from the spec


@dataclass
class MeshReport:
    watertight: bool
    is_volume: bool
    volume_cm3: float
    mass_g: float  # solid, so an upper bound
    footprint_mm: tuple[float, float]
    height_mm: float
    faces: int


@dataclass
class SlicerResult:
    hours: float | None
    grams: float | None


def mesh_report(mesh: trimesh.Trimesh, printer: PrinterProfile) -> MeshReport:
    extent = mesh.bounds[1] - mesh.bounds[0]
    volume = float(mesh.volume) / MM3_PER_CM3
    return MeshReport(
        watertight=bool(mesh.is_watertight),
        is_volume=bool(mesh.is_volume),
        volume_cm3=volume,
        mass_g=volume * printer.filament_density_g_cm3,
        footprint_mm=(float(extent[0]), float(extent[1])),
        height_mm=float(extent[2]),
        faces=len(mesh.faces),
    )


def find_slicer() -> str | None:
    for name in SLICER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def parse_gcode_stats(text: str) -> SlicerResult:
    """Read the estimates PrusaSlicer and OrcaSlicer write as comments in the G-code."""
    hours = grams = None
    time_hit = re.search(r"estimated printing time \(normal mode\) = ([^\n]+)", text)
    if time_hit:
        parts = {unit: int(n) for n, unit in re.findall(r"(\d+)([dhms])", time_hit.group(1))}
        hours = (
            parts.get("d", 0) * 24
            + parts.get("h", 0)
            + parts.get("m", 0) / 60
            + parts.get("s", 0) / 3600
        )
    grams_hit = re.search(r"filament used \[g\] = ([\d.]+)", text)
    if grams_hit:
        grams = float(grams_hit.group(1))
    return SlicerResult(hours, grams)


def run_slicer(slicer: str, config: str, stl: Path) -> SlicerResult:
    with tempfile.TemporaryDirectory() as work:
        gcode = Path(work) / "out.gcode"
        subprocess.run(
            [slicer, "--export-gcode", "--load", config, "--output", str(gcode), str(stl)],
            check=True,
            capture_output=True,
            timeout=SLICE_TIMEOUT_S,
        )
        return parse_gcode_stats(gcode.read_text(encoding="utf-8", errors="replace"))


def _limit_text(printer: PrinterProfile) -> str:
    if printer.max_print_hours:
        return f"This printer's limit is {printer.max_print_hours:g} hours."
    return "This printer has no time limit."


def print_time_text(
    printer: PrinterProfile, slicer: str | None, result: SlicerResult | None, note: str = ""
) -> str:
    if result is not None and result.hours is not None:
        text = f"Print time: about {result.hours:.1f} hours (slicer estimate)."
        if printer.max_print_hours:
            verdict = "within" if result.hours <= printer.max_print_hours else "OVER"
            text += f" That is {verdict} the printer's limit of {printer.max_print_hours:g} hours."
        if result.grams is not None:
            text += f" Filament: about {result.grams:.1f} g (slicer estimate)."
        return text
    if slicer is None:
        return (
            "Print time: unavailable, no PrusaSlicer or OrcaSlicer was found on PATH. "
            + _limit_text(printer)
        )
    return f"Print time: unavailable. {note or 'The slicer did not report a time.'} " + _limit_text(
        printer
    )


def filament_text(report: MeshReport, printer: PrinterProfile) -> str:
    return (
        f"Filament: volume {report.volume_cm3:.3f} cubic centimetres; solid mass at "
        f"{printer.filament_density_g_cm3:g} g per cubic centimetre is {report.mass_g:.3f} g. "
        "This is an upper bound; real prints use infill and weigh less."
    )


def check_text(
    name: str,
    report: MeshReport,
    printer: PrinterProfile,
    slicer: str | None,
    slicer_result: SlicerResult | None,
    slicer_note: str,
    printability: list[str],
    steepest_degrees: float | None,
    size_line: str,
) -> str:
    yes = {True: "yes", False: "NO"}
    lines = [
        f"Print check for model {name}",
        (
            f"Mesh: watertight {yes[report.watertight]}; valid solid {yes[report.is_volume]}; "
            f"{report.faces} triangles. {size_line}"
        ),
        (
            f"Size: {report.footprint_mm[0]:.1f} mm by {report.footprint_mm[1]:.1f} mm, "
            f"{report.height_mm:.1f} mm tall."
        ),
        filament_text(report, printer),
        (
            "Overhangs: none. The model is a height map, so every surface faces up or is a vertical "
            "wall, and it prints flat side down with no supports."
        ),
    ]
    if steepest_degrees is not None:
        lines.append(f"Steepest slope: {steepest_degrees:.0f} degrees from horizontal.")
    lines.append(print_time_text(printer, slicer, slicer_result, slicer_note))
    lines.append("Minimum features and fit:")
    lines += [f"  {p}" for p in printability] or ["  All line styles meet the minimums."]
    return "\n".join(lines)


def print_notes(name: str, what: str, report: MeshReport, printer) -> str:
    return "\n".join(
        [
            f"Print notes for {name}",
            "",
            f"What it is: {what}",
            (
                f"Size: {report.footprint_mm[0]:.1f} mm by {report.footprint_mm[1]:.1f} mm, "
                f"{report.height_mm:.1f} mm tall."
            ),
            "Orientation: print flat side down, no supports.",
            f"Layer height: {LAYER_HEIGHT_NOTE} is suitable.",
            filament_text(report, printer),
            "",
        ]
    )


def submit_notes(printer: PrinterProfile) -> str:
    description = (
        "Tactile terrain map for a blind user. "
        "Any single high-contrast colour is fine, and it prints flat side down with no supports."
    )
    return f"{printer.submit_notes}\n\n{description}\n" if printer.submit_notes else ""


def write_print_pack(
    model_dir: Path,
    stl: Path,
    attribution: Path,
    notes: str,
    submit: str,
) -> list[Path]:
    pack = model_dir / "print-pack"
    pack.mkdir(exist_ok=True)
    written = [pack / stl.name, pack / "ATTRIBUTION.txt", pack / "PRINT-NOTES.txt"]
    shutil.copy2(stl, written[0])
    shutil.copy2(attribution, written[1])
    written[2].write_text(notes, encoding="utf-8")
    if submit:
        written.append(pack / "SUBMIT-NOTES.txt")
        written[-1].write_text(submit, encoding="utf-8")
    return written
