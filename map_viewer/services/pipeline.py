from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Callable


class _QueueLogHandler(logging.Handler):
    """Forwards ctw logger records into the SSE event queue during a pipeline run."""

    def __init__(self, send_fn: Callable[[str, dict], None]) -> None:
        super().__init__()
        self._send = send_fn

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._send("log", {"message": self.format(record), "level": record.levelname.lower()})
        except Exception:
            self.handleError(record)


def run_pipeline_steps(
    map_folder: Path,
    map_output_dir: Path,
    name: str,
    force: bool,
    send: Callable[[str, dict], None],
) -> None:
    """Execute all analysis pipeline steps, emitting SSE events via send()."""
    from ctw.log import setup_map_file_logging
    from map_analysis.pipeline import run_island_geometry, run_symmetry, assemble_map
    from layout_analysis.pipeline import analyze_layout
    from xml_analysis.pipeline import analyze_xml
    from layout_analysis.map_layout_config import get_map_layout

    map_output_dir.mkdir(parents=True, exist_ok=True)
    setup_map_file_logging(map_output_dir)

    log_handler = _QueueLogHandler(send)
    log_handler.setLevel(logging.DEBUG)
    log_handler.setFormatter(logging.Formatter('%(message)s'))
    ctw_logger = logging.getLogger('ctw')
    ctw_logger.addHandler(log_handler)

    try:
        map_layout_cfg = get_map_layout(name)

        if map_layout_cfg is not None and map_layout_cfg.skip:
            send("skipped", {"reason": "Map is excluded in map_layouts.json"})
            return

        if map_layout_cfg is not None:
            island_layout_type = "y0" if (map_layout_cfg.layer == "y0" and not map_layout_cfg.exclude) else "decided"
        else:
            island_layout_type = "bedrock"

        # Step 1 — XML (runs first so max_build_height is available for layout)
        send("step", {"step": "xml", "status": "running", "label": "XML"})
        xml_context = None
        try:
            xml_context = analyze_xml(map_folder, force_rerun=force, output_dir=map_output_dir)
            if xml_context:
                md = xml_context.map_data
                detail_txt = f"{len(md.teams)} team(s), {len(md.wools)} wool(s)"
            else:
                detail_txt = "no map.xml found"
            send("step", {"step": "xml", "status": "done", "label": "XML", "detail": detail_txt})
        except Exception as exc:
            send("step", {"step": "xml", "status": "error", "label": "XML", "detail": str(exc)})
            # Non-fatal: continue without XML (layout will run without height cap)

        # Step 2 — Layout (receives max_build_height from XML context)
        send("step", {"step": "layout", "status": "running", "label": "Layout"})
        try:
            mbh = xml_context.map_data.max_build_height if xml_context else None
            parquet_files = analyze_layout(
                map_folder, force_rerun=force, output_dir=map_output_dir,
                map_layout_config=map_layout_cfg, max_build_height=mbh,
            )
            n = len(parquet_files) if parquet_files else 0
            send("step", {"step": "layout", "status": "done", "label": "Layout", "detail": f"{n} file(s) written"})
        except Exception as exc:
            send("step", {"step": "layout", "status": "error", "label": "Layout", "detail": str(exc)})
            send("error", {"message": f"Layout failed: {exc}"})
            return

        # Step 3 — Islands
        send("step", {"step": "islands", "status": "running", "label": "Islands"})
        try:
            geometry = run_island_geometry(
                map_folder, force_rerun=force,
                layout_type=island_layout_type, map_output_dir=map_output_dir,
            )
            if not geometry:
                send("step", {"step": "islands", "status": "error", "label": "Islands",
                              "detail": "No islands detected — check layout"})
                send("error", {"message": "Island detection produced no results"})
                return
            send("step", {"step": "islands", "status": "done", "label": "Islands",
                          "detail": f"{len(geometry.islands)} island(s)"})
        except Exception as exc:
            send("step", {"step": "islands", "status": "error", "label": "Islands", "detail": str(exc)})
            send("error", {"message": f"Islands failed: {exc}"})
            return

        # Step 4 — Symmetry
        send("step", {"step": "symmetry", "status": "running", "label": "Symmetry"})
        symmetry = None
        try:
            symmetry = run_symmetry(map_output_dir, geometry=geometry)
            desc = (symmetry.primary["description"] if symmetry and symmetry.primary else "none detected")
            send("step", {"step": "symmetry", "status": "done", "label": "Symmetry", "detail": desc})
        except Exception as exc:
            send("step", {"step": "symmetry", "status": "error", "label": "Symmetry", "detail": str(exc)})
            # Non-fatal: continue without symmetry

        # Step 5 — Assembly
        send("step", {"step": "assembly", "status": "running", "label": "Assembly"})
        try:
            exclude_isl = map_layout_cfg.exclude_islands if map_layout_cfg is not None else []
            bbox        = map_layout_cfg.playable_bbox if map_layout_cfg is not None else None
            assemble_map(
                map_folder, geometry, map_output_dir,
                symmetry=symmetry, xml_context=xml_context,
                exclude_observer_island=False, exclude_islands=exclude_isl, playable_bbox=bbox,
            )
            send("step", {"step": "assembly", "status": "done", "label": "Assembly"})
        except Exception as exc:
            send("step", {"step": "assembly", "status": "error", "label": "Assembly", "detail": str(exc)})
            send("error", {"message": f"Assembly failed: {exc}"})
            return

        send("done", {"message": "Pipeline complete"})

    except Exception as exc:
        send("error", {"message": f"Unexpected error: {exc}", "detail": traceback.format_exc()})
    finally:
        ctw_logger.removeHandler(log_handler)


def run_layout_only_steps(
    map_folder: Path,
    map_output_dir: Path,
    force: bool,
    send: Callable[[str, dict], None],
) -> None:
    """Run only the layout extraction (all 4 layers). No config required."""
    from layout_analysis.pipeline import analyze_layout

    map_output_dir.mkdir(parents=True, exist_ok=True)
    send("step", {"step": "layout", "status": "running", "label": "Layout"})
    try:
        analyze_layout(map_folder, force_rerun=force, output_dir=map_output_dir, skip_features=True)
        send("step", {"step": "layout", "status": "done", "label": "Layout",
                      "detail": "4 layer files written"})
        send("done", {"message": "Layer extraction complete"})
    except Exception as exc:
        send("step", {"step": "layout", "status": "error", "label": "Layout", "detail": str(exc)})
        send("error", {"message": str(exc)})


_PIPELINE_STEPS = [
    {"id": "xml",      "label": "XML",      "file": "map_data.json"},
    {"id": "layout",   "label": "Layout",   "file": "layout_y0.parquet"},
    {"id": "islands",  "label": "Islands",  "file": "islands.json"},
    {"id": "symmetry", "label": "Symmetry", "file": "symmetry.json"},
    {"id": "assembly", "label": "Assembly", "file": "map_context.json"},
]


def check_pipeline_status(output_dir: Path) -> list[dict]:
    return [
        {
            "id": step["id"],
            "label": step["label"],
            "file": step["file"],
            "done": (output_dir / step["file"]).exists(),
        }
        for step in _PIPELINE_STEPS
    ]