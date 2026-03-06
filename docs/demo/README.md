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

---

# Tumbleweed — Match Data Processing Demo

Visual walkthrough of the **match data processing pipeline** using a live match
on the **Tumbleweed** Capture the Wool map (match recorded 2026-01-24, 141 players,
75 minute duration).

> Regenerate these images with:
> ```
> python docs/demo/generate_demo.py --map tumbleweed --match 3 --player 21
> ```
>
> The pipeline to produce match data before running this script:
> ```
> python ctw.py run --all
> python ctw.py maps load
> python ctw.py maps spawns
> python ctw.py matches index --match-dir match_logs
> python ctw.py matches process-all
> python ctw.py matches post-process --all
> ```

---

## Map Structure

The Tumbleweed map features a linear layout with two team bases connected by
a central bridge region. Nine islands total, with 180-degree rotational symmetry.

### Block Layout

Bedrock layer blocks colored by island assignment. Team islands face each other
across the central void, with neutral islands forming the mid-section.

![Block Layout](assets/tumbleweed/01_blocks.png)

### XML Regions

Build regions (green overlay) parsed from the map XML. The long central bridge
section spans most of the map's length, defining where players can construct.

![XML Regions](assets/tumbleweed/02_regions.png)

### Skeleton Overlay

Topological skeleton of each island showing the medial axis (light blue paths)
and key structural nodes: endpoints (dark blue) mark entry/exit points,
junction nodes (gray) mark branching locations used for role classification.

![Skeleton](assets/tumbleweed/03_skeleton.png)

### Island Outlines

Simplified polygon outlines derived from the block layout. The elongated shapes
of Tumbleweed's islands reflect its linear map design.

![Island Outlines](assets/tumbleweed/04_outline.png)

---

## Match Analysis

Once match logs are indexed and processed, the pipeline extracts per-player
life segments — each life from spawn to death — annotated with spatial context
(which island, build region, or void the player occupied at each tick).

### Player Trace — Single Player

Position trace for the top-fragging player (blue team, 20 lives, 68 kills)
across all life segments in the match. Each life is drawn in a distinct color.
The tight clustering near the enemy base reflects consistent offensive pressure.

![Single Trace](assets/tumbleweed/05_trace_single.png)

### Player Traces — Full Team View

All 141 players colored by team (blue vs red). The density distribution reveals
team territory control: blue players concentrated around the enemy wool rooms,
red players defending and contesting the central bridge area.

![Team Traces](assets/tumbleweed/06_trace_team.png)

### Match Time Series

Per-team attack depth and death rate over the course of the match (60-second
buckets). Attack depth measures how close players are to the enemy wool objectives
on average — a depth of 1.0 means players are at the wool, 0.0 means they are
at spawn. Triangle markers (▲) indicate wool touches, stars (★) indicate captures.

The 75-minute match shows sustained blue-team pressure with multiple deep pushes,
while red's depth spikes indicate counter-attacks. The negative push-pull correlation
(−0.41) confirms a back-and-forth dynamic between the two teams.

![Time Series](assets/tumbleweed/07_timeseries.png)

### Player Role Archetypes

Life segments are clustered into behavioural archetypes using unsupervised learning
on spatial features derived from the skeleton graph. Each bar shows how many lives
each archetype was played, broken down by team:

| Archetype | Description |
|---|---|
| **deep-attacker** | Consistently pushes deep into enemy territory; high kill rate |
| **attacker** | Objective-focused; pushes deep with moderate home-island time |
| **bridge-fighter** | Spends most time in build/void regions between islands |
| **defender** | Stays almost exclusively on home island; rarely departs |
| **outlier** | Edge cases; lives on neutral islands or very short durations |

The tumbleweed match shows a high proportion of attackers and bridge-fighters,
consistent with its long central corridor design encouraging sustained mid-map combat.

![Archetype Distribution](assets/tumbleweed/08_archetypes.png)
