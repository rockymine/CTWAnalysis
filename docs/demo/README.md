# Ingwaz — Map Demo

Visual walkthrough of the analysis pipeline output for the **Ingwaz** Capture the Wool map.

> Regenerate these images with:
> ```
> python docs/demo/generate_demo.py --map Ingwaz
> ```

---

## Block Layout

Individual blocks from the bedrock layer, colored by island assignment.
Team islands appear in red/blue, neutral islands in gray.
Star markers show spawn points and wool objectives.

![Block Layout](assets/ingwaz/01_blocks.png)

## XML Regions

Build region (green overlay) parsed from the map XML, with island polygon
outlines and POI markers. The build region represents the area where players
can place blocks during the match.

![XML Regions](assets/ingwaz/02_regions.png)

## Skeleton Overlay

Topological skeleton extracted from each island's shape. Skeleton edges
(light blue) trace the medial axis of each island, with endpoints (dark blue)
and junction nodes marking key positions.

![Skeleton](assets/ingwaz/03_skeleton.png)

## Island Outlines

Simplified polygon outlines of each detected island. These polygons are
derived from the block layout via alpha-shape triangulation and polygon
simplification.

![Outlines](assets/ingwaz/04_outline.png)

## Connectivity Graph

Full map connectivity showing all layers: build region, island outlines,
skeleton paths, and void links (red dashed lines) connecting islands across
open space. Void link thickness is inversely proportional to distance.

![Connectivity](assets/ingwaz/05_connectivity.png)

## Player Trace (Single Player)

Position trace for a single player across all life segments in one match.
Each life (spawn to death) is drawn in a distinct color, showing movement
patterns and engagement areas.

![Single Trace](assets/ingwaz/06_trace_single.png)

## Player Traces (Team View)

All players in a match colored by team assignment (red vs blue).
Useful for understanding team-level movement patterns and territory control.

![Team Traces](assets/ingwaz/07_trace_team.png)
