from pathlib import Path


_PIPELINE_STEPS = [
    {"id": "xml",      "label": "XML",      "file": "map_data.json"},
    {"id": "layout",   "label": "Layout",   "file": "layout_bedrock.parquet"},
    {"id": "islands",  "label": "Islands",  "file": "islands.json"},
    {"id": "symmetry", "label": "Symmetry", "file": "symmetry.json"},
    {"id": "assembly", "label": "Assembly", "file": "map_context.json"},
]


def _check_pipeline_status(output_dir: Path) -> list[dict]:
    return [
        {
            "id": step["id"],
            "label": step["label"],
            "file": step["file"],
            "done": (output_dir / step["file"]).exists(),
        }
        for step in _PIPELINE_STEPS
    ]