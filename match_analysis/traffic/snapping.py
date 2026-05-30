"""Nearest-node snapping and path reconstruction for the traffic graph.

This module operates on the topology dict returned by
``match_analysis.traffic_graph.build_traffic_topology()``.

Terminology
-----------
Observed (sampled) positions
    The raw x/z coordinates recorded every ~2 seconds.  These are ground truth.

Snapped anchors
    Each observed position is mapped to the nearest traffic-graph node.  This
    is an approximation — the player may be anywhere within the 5×5 grid cell
    that node represents.

Inferred (reconstructed) intermediate path
    The graph path between two consecutive snapped anchors.  Because position
    samples are ~2 s apart, the player may have traversed multiple edges
    between samples.  This layer is *inferred*, not observed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import networkx as nx
except ImportError as exc:
    raise ImportError("networkx is required for traffic_snapping") from exc


# ---------------------------------------------------------------------------
# Grid geometry
# ---------------------------------------------------------------------------

def bresenham_cells(
    cx1: int, cz1: int, cx2: int, cz2: int, grid_size: int
) -> list[tuple[int, int]]:
    """Return all grid cells on the Bresenham line from (cx1,cz1) to (cx2,cz2).

    Coordinates are grid-cell origins (i.e. already snapped to grid_size
    multiples).  The returned list always starts with (cx1,cz1) and ends
    with (cx2,cz2), with every intermediate cell included.
    """
    cells: list[tuple[int, int]] = [(cx1, cz1)]
    if cx1 == cx2 and cz1 == cz2:
        return cells

    dx = abs(cx2 - cx1) // grid_size
    dz = abs(cz2 - cz1) // grid_size
    sx = grid_size if cx2 > cx1 else -grid_size
    sz = grid_size if cz2 > cz1 else -grid_size

    cx, cz = cx1, cz1
    if dx >= dz:
        err = dx // 2
        while cx != cx2:
            err -= dz
            if err < 0:
                cz += sz
                err += dx
            cx += sx
            cells.append((cx, cz))
    else:
        err = dz // 2
        while cz != cz2:
            err -= dx
            if err < 0:
                cx += sx
                err += dz
            cz += sz
            cells.append((cx, cz))
    return cells


# ---------------------------------------------------------------------------
# Nearest-node snapping
# ---------------------------------------------------------------------------

def snap_positions(
    xs: np.ndarray,
    zs: np.ndarray,
    node_info: dict[int, dict],
) -> np.ndarray:
    """Map each (x, z) sample to the nearest traffic-graph node.

    Parameters
    ----------
    xs, zs:
        1-D arrays of world-space x and z coordinates (observed positions).
    node_info:
        ``{node_id: node_dict}`` mapping from ``build_traffic_topology()``.
        Each node dict must contain ``"coords": [x, z]``.

    Returns
    -------
    np.ndarray of int
        Array of node_ids (same length as xs/zs).  Each element is the id of
        the nearest graph node to the corresponding sample.
    """
    if len(node_info) == 0:
        raise ValueError("node_info is empty — cannot snap positions")

    node_ids = np.array(list(node_info.keys()), dtype=int)
    coords   = np.array([node_info[nid]["coords"] for nid in node_ids], dtype=float)

    pts = np.column_stack([np.asarray(xs, float), np.asarray(zs, float)])  # (N, 2)

    # Compute pairwise squared distances: (N, M)
    diff = pts[:, None, :] - coords[None, :, :]   # broadcast
    sq   = (diff ** 2).sum(axis=2)
    nearest_idx = sq.argmin(axis=1)
    return node_ids[nearest_idx]


def snap_positions_df(
    positions_df: pd.DataFrame,
    node_info: dict[int, dict],
    x_col: str = "x",
    z_col: str = "z",
) -> pd.Series:
    """Convenience wrapper around snap_positions for a DataFrame.

    Returns a pd.Series of node_ids aligned with positions_df.index.
    """
    node_ids = snap_positions(
        positions_df[x_col].to_numpy(),
        positions_df[z_col].to_numpy(),
        node_info,
    )
    return pd.Series(node_ids, index=positions_df.index, name="snapped_node_id")


# ---------------------------------------------------------------------------
# Path reconstruction
# ---------------------------------------------------------------------------

def reconstruct_path(
    G: nx.Graph,
    src: int,
    dst: int,
    mode: str = "dense",
    grid_size: float = 5.0,
) -> list[int] | None:
    """Find a path between two nodes on the traffic graph.

    Parameters
    ----------
    G:
        NetworkX graph from ``build_traffic_topology()["full_graph"]``.
        Edges carry ``weight`` (Euclidean distance) and ``transitions`` attributes.
    src, dst:
        Source and destination node ids.
    mode:
        ``"dense"`` *(default)* — penalises long edges quadratically:
            effective weight = distance² / grid_size.
            A single 30-block edge costs 180 (30²/5); six 5-block hops cost 30
            (6 × 5²/5 = 30).  Forces routing through the dense short-hop
            neighbourhood rather than taking void-crossing shortcuts.

        ``"shortest"`` — minimise total Euclidean distance (uses ``weight``
            attr directly).  May take void-crossing shortcuts when a long direct
            edge is shorter in Euclidean terms than going around.

        ``"traffic_weighted"`` — prefer high-traffic edges; effective weight =
            distance / (transitions + 1), so popular edges are cheaper.

        ``"traffic_dense"`` — combines both penalties: prefers short, high-traffic
            edges.  Effective weight = distance² / (grid_size × (transitions + 1)).
    grid_size:
        Grid cell side length in blocks (default 5).  Used by ``"dense"`` and
        ``"traffic_dense"`` modes to normalise the quadratic penalty so that
        adjacent-cell edges (distance ≈ grid_size) still have unit weight.

    Returns
    -------
    list[int] | None
        Ordered list of node_ids from src to dst (inclusive), or ``None`` if the
        nodes are not connected (e.g. on separate disconnected subgraphs).
    """
    if src == dst:
        return [src]

    if src not in G or dst not in G:
        return None

    if mode == "dense":
        _gs = grid_size
        def _weight(u, v, data):
            dist = data.get("weight", 1.0)
            return (dist * dist) / _gs
        weight_arg: str | None = _weight  # type: ignore[assignment]
    elif mode == "traffic_weighted":
        def _weight(u, v, data):
            dist = data.get("weight", 1.0)
            trans = data.get("transitions", 1)
            return dist / (trans + 1)
        weight_arg = _weight
    elif mode == "traffic_dense":
        _gs = grid_size
        def _weight(u, v, data):
            dist  = data.get("weight", 1.0)
            trans = data.get("transitions", 1)
            return (dist * dist) / (_gs * (trans + 1))
        weight_arg = _weight
    else:
        # "shortest" — plain Euclidean distance
        weight_arg = "weight"

    try:
        return nx.shortest_path(G, src, dst, weight=weight_arg)
    except nx.NetworkXNoPath:
        return None
    except nx.NodeNotFound:
        return None


def reconstruct_full_path(
    snapped_sequence: list[int],
    G: nx.Graph,
    mode: str = "dense",
    grid_size: float = 5.0,
) -> tuple[list[int], list[bool]]:
    """Reconstruct the full graph path for a snapped node sequence.

    For each consecutive pair in *snapped_sequence*, finds the shortest (or
    traffic-weighted) path through *G* and concatenates the results.

    Parameters
    ----------
    snapped_sequence:
        Raw snapped node-id list (may contain repeated consecutive entries).
    G:
        Traffic graph (networkx).
    mode:
        Passed through to :func:`reconstruct_path`.
    grid_size:
        Passed through to :func:`reconstruct_path` (used by ``"dense"`` modes).

    Returns
    -------
    (path_nodes, is_anchor) : tuple[list[int], list[bool]]
        ``path_nodes`` — full concatenated path (deduplicating shared junction
        nodes between consecutive segment pairs).
        ``is_anchor`` — boolean mask: ``True`` where the node is a snapped
        anchor (observed), ``False`` where it is an inferred intermediate.

    Notes
    -----
    When no path exists between two consecutive anchors (disconnected graph
    components), only the anchor nodes are kept and the gap is noted by a
    missing inferred segment (the anchors still appear in the output as
    consecutive observed entries).
    """
    if not snapped_sequence:
        return [], []

    path_nodes: list[int] = [snapped_sequence[0]]
    is_anchor:  list[bool] = [True]

    for prev_id, curr_id in zip(snapped_sequence, snapped_sequence[1:]):
        if prev_id == curr_id:
            # Stayed on the same node — record anchor again (shows dwell)
            path_nodes.append(curr_id)
            is_anchor.append(True)
            continue

        segment = reconstruct_path(G, prev_id, curr_id, mode=mode, grid_size=grid_size)

        if segment is None or len(segment) == 0:
            # No path found — jump directly to next anchor
            path_nodes.append(curr_id)
            is_anchor.append(True)
        else:
            # Skip first node (already the last node added) and mark intermediates
            for i, nid in enumerate(segment[1:], start=1):
                is_obs = (i == len(segment) - 1)  # only the last node is an anchor
                path_nodes.append(nid)
                is_anchor.append(is_obs)

    return path_nodes, is_anchor


# ---------------------------------------------------------------------------
# Sequence simplification
# ---------------------------------------------------------------------------

def simplify_sequence(
    sequence: list[int],
    method: str = "consecutive_dedup",
) -> list[int]:
    """Simplify a node-id sequence by removing redundancy.

    Parameters
    ----------
    sequence:
        Input list of node ids.
    method:
        ``"consecutive_dedup"`` — collapse immediately repeated consecutive
        nodes.  ``[A, A, B, A, A]`` → ``[A, B, A]``.  ABAB oscillations are
        *kept* because they represent alternating anchors, not pure repetition.

        ``"none"`` — return a copy of the sequence unchanged.

    Returns
    -------
    list[int]
        Simplified sequence (copy; original is not mutated).
    """
    if not sequence:
        return []

    if method == "none":
        return list(sequence)

    if method == "consecutive_dedup":
        out: list[int] = [sequence[0]]
        for nid in sequence[1:]:
            if nid != out[-1]:
                out.append(nid)
        return out

    raise ValueError(f"Unknown simplification method: {method!r}")
