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

---

## Wool Dynamics

Deep analysis of objective play from the `wool_dynamics` notebook.  Four views
examine how each wool was contested throughout the match — from raw node coverage
to reconstructed carry attempts.

> Regenerate with:
> ```
> jupyter nbconvert --to notebook --execute notebooks/wool_dynamics.ipynb
> ```

### Per-Wool Node Coverage

For each of the four wool objectives, defender and attacker tick-counts at the
wool's skeleton node are plotted per 60-second bucket.  Triangles (▲) mark wool
touches; stars (★) mark captures.

The asymmetric defence pattern is clear: **lime** and **orange** wools (bottom
half) were captured early (~t=200–250 s) because attacker ticks vastly
outnumbered defender ticks.  **Cyan** (top) had heavy blue-team coverage the
entire match and was never captured.  **Yellow** was held until the final minutes
when blue finally overwhelmed the defence.

![Wool Node Coverage](assets/tumbleweed/09_wool_coverage.png)

### Y-Level Phase Detection

Rolling 5-minute median player Y per team reveals the transition from ground-level
play to skybridge-level play.  The left panel shows both teams trending upward from
Y ≈ 10 (ground) toward the skybridge threshold (Y = 22, dashed) late in the match.
Blue's median Y crosses the threshold ~t = 3500 s, roughly 60 minutes in.

The right panel confirms bimodality: the early-game Y distribution peaks at Y ≈ 10
(ground layer), while the late-game distribution develops a second peak at Y = 29
(max build height) — the skybridge itself.

![Y-Level Phase](assets/tumbleweed/10_y_phase.png)

### Per-Wool Attack Depth

Attack depth measures how close attacking players are to each wool objective
independently (`depth = 1 − dist / baseline`), averaged per 60-second bucket.

Both series sit well below 0.5 for most of the match, reflecting the long travel
distance from spawn to wool.  The slight upward trend for **yellow wool** (blue
attacks, top panel) toward the end of the match corresponds to the late skybridge
push that eventually secured the capture.

![Per-Wool Attack Depth](assets/tumbleweed/11_wool_depth.png)

### Wool Carry Chain Timeline

Gantt chart of every reconstructed carry wave.  Each bar spans the first touch to
capture/loss, coloured by the carrying team (blue / red), hatched by outcome.
Annotation shows handoff count (+N↔) and approach type (sky / gnd).

| Wool | Carrier | Outcome | t (s) | Handoffs | Approach |
|---|---|---|---|---|---|
| orange | blue | captured ★ | ~250 | 3 | ground |
| lime | red | captured ★ | ~200 | 9 | ground |
| yellow | blue | captured ★ | ~4 450 | 9 | ground |

All three captures in this match were ground-level approaches — the skybridge was
constructed but used for map control rather than as a direct wool-room entry route.

![Carry Chain Timeline](assets/tumbleweed/12_carry_chains.png)
