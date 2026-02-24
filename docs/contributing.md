# CTW Analysis — Developer Guidelines

Guidelines covering the three cross-cutting concerns that appear throughout the
pipeline: structured logging, type annotations, and custom domain types.

---

## 1. Structured Logging

### The `ctw` logger

All pipeline output goes through a single named logger:

```python
import logging
logger = logging.getLogger('ctw')
```

Two handlers are attached at startup (see `ctw/log.py`):

| Handler | Level | Destination | Format |
|---------|-------|-------------|--------|
| Console | INFO  | stderr      | `%(message)s` |
| File    | DEBUG | `output/<map>/pipeline.log` | `HH:MM:SS  LEVEL  filename: message` |

### Setup calls

```python
# ctw/cli.py — once at process startup
from ctw.log import setup_console_logging
setup_console_logging()

# ctw/commands/run.py — once per map, before any pipeline step
from ctw.log import setup_map_file_logging
setup_map_file_logging(map_output_dir)
```

Do **not** call either setup function from inside pipeline modules —
those modules only call `logging.getLogger('ctw')`.

### Level conventions

| Level | Use for |
|-------|---------|
| `logger.info(...)` | One-line human summary per major step (visible on console) |
| `logger.debug(...)` | Implementation detail: counts, file paths, intermediate metrics |
| `logger.warning(...)` | Unexpected but recoverable situation (visible on console) |

Avoid `logger.error` / `logger.critical` in pipeline code; raise exceptions
for hard failures instead.

```python
# Good — info summarises the step for the human watching the terminal
logger.info(f"  Islands: {len(islands)} detected, {len(skeleton_results)} skeletons computed")

# Good — debug records detail useful for post-hoc diagnosis
logger.debug(f"  Saved: {output_path}")
logger.debug(f"  Canonical groups: {len(canonical_groups)}")

# Good — warning surfaces an anomaly without aborting the run
logger.warning(f"  Wool '{color}' outside all islands, trying wool-room fallback")
```

### Extracting `_log_*` helpers

When a function contains more than ~3 consecutive log lines — especially loops
that accumulate diagnostics — extract them into a private `_log_*` function
placed immediately above the caller:

```python
def _log_skeleton_stats(
    skeleton_results: list[IslandResult],
    canonical_groups: dict[str, list[int]],
) -> None:
    total_nodes = sum(len(r.graph.nodes) for r in skeleton_results)
    total_edges = sum(len(r.graph.edges) for r in skeleton_results)
    total_endpoints = sum(
        sum(1 for n in r.graph.nodes if n.node_type == 'endpoint')
        for r in skeleton_results
    )
    logger.debug(f"  Skeleton nodes:     {total_nodes}")
    logger.debug(f"  Skeleton edges:     {total_edges}")
    logger.debug(f"  Skeleton endpoints: {total_endpoints}")
    logger.debug(f"  Canonical groups:   {len(canonical_groups)}")


def _compute_skeletons(...) -> ...:
    ...
    _log_skeleton_stats(skeleton_results, canonical_groups)
    return skeleton_results, canonical_groups
```

Rules for `_log_*` helpers:
- Pure diagnostic — read data only, no side-effects.
- Return `None`.
- Named with `_log_` prefix and placed directly above their only caller.
- Accept the already-computed values as arguments; do not recompute them.

---

## 2. Type Annotations

Every function in the pipeline must have a fully annotated signature.
Python does not enforce this at runtime, but Pylance/mypy and human readers
depend on it.

### Return types

| Signature | Meaning |
|-----------|---------|
| `def f() -> None:` | Void — returns nothing (explicit) |
| `def f() -> SomeType:` | Returns a value of that type |
| `def f():` | **Unannotated** — do not write this in new code |

### Parameter types

Annotate every parameter, including `self`-free module-level functions:

```python
# Good
def find_containing_island(
    point_xz: Point2D,
    islands: list[Island],
    tolerance: float = 5.0,
) -> Optional[Island]:

# Bad — bare parameters
def find_containing_island(point_xz, islands, tolerance=5.0):
```

### Use built-in generics (Python 3.9+)

Prefer the lowercase built-in forms; **do not** import `List`, `Dict`, `Tuple`,
`Set` from `typing`:

```python
# Good
list[Island]
dict[str, list[int]]
tuple[float, float]
Optional[MapData]           # Optional still comes from typing

# Bad (old-style)
from typing import List, Dict, Tuple
List[Island]
Dict[str, List[int]]
```

### `Optional` vs union

Use `Optional[T]` (equivalent to `T | None`) for values that can be absent.
Bare `None` default without `Optional` in the annotation is a bug:

```python
def assemble_map(
    map_data: Optional[MapData] = None,   # correct
    plots: bool = False,
) -> MapContext:
```

### External / dynamic types

Use `Any` for Shapely geometry objects or other external types where the
concrete type is not worth importing for annotation purposes only:

```python
from typing import Any

def _reflect_shapely_geom_x(geom: Any, center_x: float) -> Any:
    from shapely import affinity
    return affinity.affine_transform(geom, [-1, 0, 0, 1, 2 * center_x, 0])
```

### DataFrames

Annotate as `pd.DataFrame` — no row/column-level typing is expected:

```python
import pandas as pd

def compute_map_center(layout_df: pd.DataFrame) -> Point2D:
```

---

## 3. Custom Domain Types

Two `NamedTuple` types in `common.geometry` replace bare tuples for the two
most common 2D spatial values.  Import them from `common.geometry` (the
package re-exports them from `common.geometry.coordinates`).

### `Point2D` — world-space (x, z) point

```python
from common.geometry import Point2D

# Use in annotations wherever a world-space point is passed or returned
def find_nearest_node(
    point_xz: Point2D,
    island_result: IslandResult,
) -> Optional[int]:

def compute_map_center(layout_df: pd.DataFrame) -> Point2D:
```

Construct explicitly at call sites — do **not** pass raw tuples where `Point2D`
is expected:

```python
# Good
island = find_containing_island(Point2D(spawn['x'], spawn['z']), islands)

# Bad — passes a plain tuple, breaks type checkers
island = find_containing_island((spawn['x'], spawn['z']), islands)
```

Because `Point2D` is a `NamedTuple` it is still a tuple at runtime, so
unpacking continues to work:

```python
cx, cz = point2d           # works fine
x = point2d.x             # named access also works
```

### `BoundingBox` — world-extent box

```python
from common.geometry import BoundingBox

# Format: (min_x, max_x, min_z, max_z)
# max values carry the +1 block-extent adjustment already applied by
# get_grid_extent(); do not add +1 again when using BoundingBox values.
```

`BoundingBox` is returned by `get_grid_extent()` and stored on `MapContext`.
Use it in annotations for bounding-box parameters and return values:

```python
ctx.bounding_box: Optional[BoundingBox] = None
```

### When to use `tuple[float, float]` vs `Point2D`

Use `Point2D` whenever the pair semantically represents a **world-space (x, z)
location** (a point, center, or coordinate that a human would read as "position
on the map").

Keep `tuple[float, float]` for generic numeric pairs that are not spatial
world-space points (e.g., a (width, height) pair, a (min, max) range).

### Domain object types

For pipeline function signatures always import and use the concrete dataclass /
datatype rather than `Any` or `dict`:

| Type | Module | Use for |
|------|--------|---------|
| `Island` | `island_analysis.datatypes` | A detected island object |
| `IslandResult` | `skeleton_analysis.datatypes` | Skeleton + graph for one island |
| `MapData` | `xml_analysis.datatypes` | Parsed XML map data |
| `MapXmlContext` | `xml_analysis.datatypes` | Full XML parse context (regions, etc.) |
| `MapContext` | `map_analysis.datatypes` | Assembled map model written to JSON |
