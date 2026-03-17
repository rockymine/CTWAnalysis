# CTW Analysis — Glossary of Terms

_Reference definitions for terminology used across all project documents. Drawn
from gameplay observation, the CTW history transcript (Reshif, 2018), the chat
conversation on skybridge mechanics (2026-03-16), and data analysis work._

_Last updated: 2026-03-17_

---

## Map Structures

**Island**
A contiguous cluster of blocks forming a distinct navigable area. Players spawn
on their team's home island. Islands are separated by void gaps. The traffic graph
contains one node cluster per island.

**Void gap**
Air (or void below y=0) between islands that cannot be crossed on existing terrain.
Players must place blocks to cross. The necessity of bridging across void gaps is
the fundamental strategic challenge of CTW — every approach to the enemy is a
choice about where and how to cross.

**Build region**
The portion of the map where block placement is permitted by the XML configuration.
Build regions cover islands and crossing corridors. Void gaps are outside build regions.

**Wool room**
The protected region containing the wool objective(s). Only the attacking team may
enter; defenders are blocked at the boundary. Defenders set up positions _outside_
the boundary, shooting in. A captured wool room may be used as a staging area by
attackers or reused as a loot source.

**Wool monument / Victory Monument**
The block at spawn where a carried wool item must be physically placed to score a
capture. Almost universally located on the home island near spawn. The concept
originates in Vechs' Super Hostile CTM maps.

**Bedrock wall / Border control**
A pre-placed bedrock structure in the map design creating a natural chokepoint or
limiting how far players can dig. Named "border control" in early competitive maps
(Race for Victory 2). Later map design shifted from using bedrock to protect one
side toward using it to constrain both offense and defense options, preventing
pits from extending indefinitely and keeping the match dynamics balanced.

**Chokepoint**
Any narrow section of the map where passable routes cluster. Effective for defence
(one archer covers many attackers) but also creates queues on attack. Common at
the transition from bridge/void to enemy island, and immediately in front of the
wool room.

**Dynamic frontline**
A zone of multiple closely-spaced mid-map islands (rather than a single continuous
bridge corridor) creating a contested no-man's-land. Players advance and retreat
through intermediate islands, gaining and losing ground without the match
immediately resolving. Introduced by Reshif (Golden Drought, Sky Traffic) as a
signature design element. Contrasts with single-lane maps where crossing immediately
puts you at the enemy wool.

**Max build height**
The per-map ceiling for block placement (`maps.max_build_height` in the database).
Players cannot place blocks above this y-level. Determines how high a skybridge
can be built and is the reference level for skybridge detection
(y ≥ max_build_height − 2).

---

## Bridging Techniques and Transport Modes

**Flat bridge / Ground bridge**
A bridge built at approximately map floor height across a void gap. The fastest
initial crossing route and the default early-game approach. Becomes progressively
more contested and blocked as the match advances — defenders dig pits beneath it
and build walls on the far side.

**Sprint-jump bridging (block spamming)**
A movement technique where a player sprint-jumps while rapidly placing blocks
below and behind them. Produces a trail of scattered blocks rather than a clean
single-layer bridge. The accumulated block debris left across the map makes terrain
increasingly unpredictable over match time.

**Staircase**
An ascending sequence of blocks (each one block higher than the last) used to gain
elevation. The foundation of skybridge construction. Building a staircase is
deliberate and slow — the builder is vulnerable while placing. Teams
water-protect their staircases: fences and iron bars are placed at intervals
(they do not connect, do not let water flow through, but allow players to run up
between them), making the staircase resistant to flooding. In competitive play,
signs were used for the same purpose before water mechanics changed.

**Skybridge**
A player-built bridge at or near the maximum build height. The skybridge is a
parallel transport layer that bypasses contested ground-level terrain entirely.
It follows the same island and void-gap topology as the ground route — projected
in x/z — but bypasses surface-level constructions (pits, water walls, denial items)
because it travels through unconstructed airspace.

Key properties:
- The traffic graph is **2D (x/z only)**. Skybridge movement and ground movement
  at the same x/z snap to the same traffic graph nodes. The `position_events.y`
  column is the only signal that distinguishes skybridge use from ground movement.
- A skybridge typically starts as a staircase from near spawn and extends
  horizontally at the build limit toward the enemy island.
- It grows incrementally over match time as more players build it out; it can also
  shrink if enemies destroy sections.
- Once both teams have structures at height, sky combat (primarily bow) dominates.
- In public matches (our dataset), skybridges do complete and connect between teams.
  See _Communal skybridge_ for the competitive-only exception.

**Anti-skybridge / Defensive staircase**
A staircase built from near the defending team's spawn toward their own wool room,
ascending to max build height. Gives defenders a height advantage and rapid-response
route when an enemy skybridge approaches. Defenders on this structure can shoot down
at attacking builders. The structure may later be integrated into a connected sky network.

**Communal skybridge** _(competitive-era term, not present in public matches)_
A competitive stalemate where both teams build skybridge staircases partway toward
each other but neither closes the gap. Each team shoots at the other's builder to
discourage bridging forward. The result is two incomplete staircases with a gap
between, and sustained bow combat but no completion. Explicitly identified as a match
design problem in competitive CTW (Guardians of the Wool era, ~2013–2015). The tactic
was broken by vertical map designs that allowed staircasing to platforms rather than
open air. **This phenomenon does not occur in public matches** — in our dataset,
skybridges complete and connect.

**Drop-down**
A technique where a player ascends via a skybridge or staircase to gain height, then
intentionally drops off the structure to land on enemy terrain below, bypassing the
fortified ground approach. Used when the ground route is impassable but sky height
advantage allows reaching a drop-in point. Life segment y-signature: rise near
home spawn → plateau at max_build_height → sharp drop near enemy territory →
ground-level movement toward enemy wool. A single life segment can encompass:
ground movement → staircase → sky traverse → drop-down → ground attack.

**Tunnel**
Digging horizontally or diagonally through existing terrain to bypass a surface
defense. Only viable where terrain is not yet fully dug to bedrock. Detectable
in data by a sustained y-decrease (digging down) followed by horizontal movement
at low y. Becomes rare or impossible once the pit is complete.

---

## Defensive Techniques

**Pit**
The primary defensive construction: systematically digging out all terrain in front
of the wool room down to bedrock (or the lowest destructible layer). Once complete,
the ground route becomes a sheer drop equivalent — attackers must bridge across
a new void gap. Combined with walls and defenders above the pit edge, this is the
foundation of a mature CTW defense. Pit digging is the primary Phase 2 activity.

**Water defense**
Pouring water onto approach slopes, bridges, or pit walls to slow attackers. Water
slows movement, prevents sprint-jumping, and knocks players sideways. One of the
most effective defensive tools. Limited by map water availability (from chests or
ice blocks). The game design question of how much water to make available is a key
map balance lever — scarce water means defenses weaken as the match progresses
(a design explicitly explored in Golden Drought 5).

**Denial items**
Blocks placed in front of the wool room that interrupt player movement or force
unintended right-click interactions: crafting tables, furnaces, fences, fence gates,
buttons, pressure plates. These slow attackers and create noise (players accidentally
opening inventory screens). They cannot stop attackers, only impede and funnel them.

**Defense scaling**
The structural tendency for a CTW defense to grow stronger over match time. As the
match progresses, pits deepen, walls grow, water placements multiply, and defenders
optimise their positioning. This creates a paradox: the longer a stalemate lasts,
the harder it becomes to end — the defense is furthest from collapse precisely when
the match has run longest. Identified by Reshif as the central game design problem
for CTW. Maps like `brittlebush_ii` and `clearcut` (high stddev, bimodal duration
distributions) are likely exhibiting this dynamic: the match is decided before
the defense fully forms (fast cluster) or after a breakthrough despite the scaled
defense (long cluster), with no stable intermediate state.

---

## Wool and Objectives

**Wool touch**
Obtaining a wool item from the wool room — by breaking the block, opening the chest,
or walking over a floor-spawned item. Recorded as `event_type = 6` in `wool_events`.
Initiates a carry attempt.

**Wool carry / Wool extraction**
Moving the wool item from the wool room back to the team's monument. The most
dangerous phase of an attack. A failed carry returns wool to the room (drop on
death) or leaves a safety somewhere accessible.

**Wool safety**
Placing the carried wool block at a reachable, less-contested location so a teammate
can pick it up. Allows the team to maintain wool possession across multiple lives.
Safety placement can be disabled per-map in the XML configuration (uncommon).

**Double-cap / Multi-wool loop**
Carrying two (or more) wool items simultaneously — touching wool A, moving to wool B,
then returning with both. Reduces the number of return trips required. Rare on
2-wool maps; slightly more common on 3-wool 4-team maps due to shorter inter-wool
distances.

**Capture (scoring)**
Placing the carried wool block on the team's victory monument. Recorded as
`event_type = 7` in `wool_events`. Permanent.

---

## Match Phases

**Phase 1 — Rush**
Immediate post-spawn aggression. Players attempt to reach the enemy wool before
defenses form. Determines outcome on fast maps. On stalemate maps, a successful
rush ends the match quickly; an intercepted rush triggers Phase 2.

**Phase 2 — Defense setup**
If the Phase 1 rush is repelled, both teams begin fortifying. Primary activities:
pit digging, wall construction, resource gathering. Attackers probe the forming
defense and apply pressure to slow construction.

**Phase 3 — Stalemate / Skybridging**
Ground route blocked or heavily fortified. Teams escalate to skybridge construction
and sky combat. Sky control becomes strategically decisive. Absent on fast maps
where Phase 1 settled the outcome.

**Phase 4 — Resolution**
One team finally breaks through. Methods: coordinated push exploiting a gap in
defender attention, successful skybridge drop-in, attrition exhausting defenders,
or a solo run while defenders are occupied elsewhere.

---

## Player Roles

**Rusher**
Attempts to penetrate enemy terrain directly after spawn. Characterised by forward
trajectory, low home-island dwell, and early-match activation.

**Wool carrier**
A rusher or attacker who has obtained the wool. Focused on extraction. Sub-types:
successful return (reaches monument), failed extraction (dies en route), trapped
carrier (in wool room, cannot escape).

**Defender**
Stays near the home wool room. Sub-roles: archer (stationary, bow combat), digger
(pit construction), wall builder (fortification work).

**Skybridger**
Builds the team's skybridge. Characterised by sustained high y-position, block
expenditure, and forward movement at build height. Phase 3 activity.

**Sky defender / Anti-skybridger**
Builds and occupies the defensive staircase from near home spawn. Responds to
enemy skybridge approaches. Characterised by high y-position over home island,
bow combat directed outward, and defensive trajectory (not advancing toward enemy).

**Roamer / Support**
Does not fit a single role cleanly. Active across mid-map, assisting attack or
defence opportunistically. High unique-node count, mid-range attack depth.

---

## Analysis Data Structures

**Life segment**
One row in the `life_segments` table, spanning from a player's spawn to their death
(or match end). The atomic unit of role analysis. All traffic features and positional
aggregates are computed per life segment.

**Traffic graph**
A 2D graph (x/z projection) of navigable map space, constructed from aggregated
player movement across all matches for a given map. Nodes represent visited positions;
edges connect adjacent positions. Used for spatial trajectory analysis and route
comparison. **Critical limitation:** the graph is 2D and cannot distinguish ground-level
movement from skybridge movement at the same x/z position. The y-coordinate in
`position_events` is required to make this distinction.

**Snapped sequence**
The ordered list of traffic graph node IDs visited during a life segment, stored in
`life_segment_traffic_features.snapped_sequence`. Provides a compact spatial
trajectory at the resolution of the traffic graph. Sufficient for role classification
of most roles — the confirmed exception is the Skybridger and Sky Defender, which
require y-coordinate confirmation from `position_events` (established in roadmap H7).

**max_attack_depth**
Per-life-segment metric in `life_segment_traffic_features`. Represents how close to
the enemy wool the player got, as a normalised graph distance. **Lower = deeper into
enemy territory.** A value near 0.0 means the player reached the enemy wool; near
1.0 means they never left home territory.

**death_region**
Classification of where a player's life segment ended: `home_island`, `enemy_island`,
`bridge`, or `void`. Stored in `life_segment_traffic_features`. First-order proxy
for role at time of death.

**Wool carry chain**
A group of consecutive wool carry attempts (touches and partial returns) grouped
into waves, stored in `wool_carry_chains`. Captures the ebb and flow of attack
pressure on a single wool objective over the course of a match.

**Zone sequence**
A derived representation of a life segment's spatial trajectory, compressing the
snapped sequence into a sequence of zone labels: e.g., `[home, bridge, enemy, bridge,
home]`. Constructed by mapping each node in the snapped sequence to its island/region
classification. The right level of abstraction for role classification and trajectory
shape analysis.
