# Capture the Wool — Gameplay Mechanics Reference

_Internal reference for analysis design. Describes how matches typically unfold,
what roles emerge, and what signals each role produces. Written to inform role
detection heuristics and match-stage classification._

---

## Map Structure

A CTW map consists of **islands** — clusters of blocks — separated by **void gaps**.
Each team has a home island containing a wool room with one or more wool objectives.
Teams win by capturing **all** of the enemy's wool and returning each piece to their
own monument (located at spawn, ~99% of cases).

Islands are connected over the course of a match by player-built bridges.
At match start, only spawn-area connections exist; everything else must be bridged.

**Build constraints:** Only specific regions of the map are buildable. Void gaps
are outside all build regions — no blocks can be placed there. Islands are bounded
below by y=0 or by block-36 underneath. A per-map **maximum build height** caps
skybridge construction. These constraints make it feasible to interpret positional
data as a traffic network of nodes and edges.

---

## Map Layout Archetypes

CTW maps share common structural patterns that shape their gameplay and role
distributions. Understanding which archetype a map belongs to provides important
context for interpreting movement and spatial data.

### Single-lane
One bridge corridor connects home islands, with the wool room at the far end.
Defences form perpendicular to the lane; attack has no flanking option. Classic
examples: Race for Victory 1, early Overcast-era maps. Rare in the modern map pool.

### H-layout (two-lane)
Two parallel lanes connect home islands, with spawn accessible from both.
Players can rotate between lanes; teams must cover two fronts simultaneously.
Introduced by Race for Victory 2. Doubles strategic options — teams can apply
split pressure or commit fully to one lane to create an overstretch.

### Dynamic frontline (grid / island cluster)
Multiple mid-map islands arranged in a cluster or grid create a contested
no-man's-land zone. Neither team can cross directly; they advance through
intermediate islands, gaining and losing ground. Neither pure attack nor pure
defence can hold a match indefinitely — there is always a flanking route.
Introduced by Reshif (Golden Drought, Sky Traffic); became a CTW design signature.

### Vertical / elevation-based
Maps with significant elevation differences built into the terrain — islands at
different heights, cliffs, ramps. Players are _expected_ to staircase between
platforms as part of normal traversal, not just for skybridging. Introduced in
the Kung Fu Capture tournament era (Bamboo Valley, etc.) as a partial solution to
communal skybridge and defence scaling. Because staircases reach fixed platforms,
height gain has defined endpoints rather than open-air exposure.

**Analytical implication:** The traffic graph is a 2D (x/z) projection. On
vertically complex maps, nodes at different y-levels but the same x/z position
are collapsed together. Role and route analysis on vertically complex maps should
be treated with caution until a y-aware spatial layer is developed.

---

## Wool Objectives

### Counts and match duration (from database, 177 maps)

| Wools per team | Maps | Avg match duration |
|---|---|---|
| 1 | 58 | ~5.7 min |
| 2 | 94 | ~14.9 min |
| 3 | 20 | ~7.2 min |
| 5–7 | 4 | ~8–12 min |

Two-wool maps are significantly longer than one-wool maps, and the distribution
is wide (see extreme cases below under _Map Examples_). Three-wool maps
are shorter on average than two-wool, possibly because at least one wool tends
to be easier to access.

### How wool is obtained ("touching" the wool)

A player gets a touch by one of three means:
- **Breaking** the wool block in the wool room
- **Picking up** the item from a chest that regenerates wool automatically
- **Walking over** the item if the map has a spawner that drops wool on the floor

The wool room is inside a **protected region** that only the attacking team can
enter. Defenders cannot cross this boundary even if a chest is within reach.
Defenders camp and fortify *outside* the boundary.

Once touched, the wool item sits in the player's inventory and **travels with
them until they die**, at which point it drops to the floor (unless drop-on-death
is disabled in the map XML — uncommon, exact XML mechanism TBD).

### Safeties

A player carrying wool can **place the block** anywhere on their route home.
This "safety" lets teammates pick it up from a less contested position. Safety
placement can also be disabled per-map in XML (exact mechanism TBD).

### Double-capping

Players can carry **multiple wools simultaneously**. On maps with multiple wool
objectives per team, attackers almost always single-cap (capture one, return,
capture the next). Occasionally a brave player will move directly from one wool
room to another before returning. A double-cap attempt is detectable in data as
two wool-touch events at different wool-room locations without an intervening death.

### Capturing (scoring)

Wool is scored by **physically placing the block on the wool monument** — a single
defined block, located at spawn on the home island. Already-captured wools become
inert building material; their wool room remains accessible only to the attacking team
(sometimes used as a safe staging area or loot source).

---

## Respawn and Kit

### Respawn
- Players **click to respawn** (vanilla Minecraft mechanic) — not instant.
- Rarely an additional server-side spawn delay.
- Spawn point is **fixed on the home island**. Multiple spawns per team are rare;
  no example found in the current match database.
- Players start **fresh each life** — no inventory persistence across deaths.

### Starter kit (defined in map XML `<kit>` tags, per team)

| Item | Notes |
|---|---|
| Sword | Stone or iron, varies per map |
| Bow | Usually Infinity (one arrow sufficient) |
| Tools | Pick, axe, shovel |
| Blocks | Up to ~3 stacks for bridging, varies |
| Armor | Weak leather starter set |
| Golden apple | Usually 1, for health regeneration |

Food is rarely provided. Additional armor pieces may be craftable if the map
provides gold, iron, or diamond blocks (diamond is extremely rare).

### Kill rewards
Default: 1 golden apple per kill + sometimes a small quantity of blocks.
Exact reward is defined per map in XML.

### Renewable resources
Chests and resource spawners regenerate over time, controlled by the XML
`<renewables>` module. Wool chests in the wool room auto-refill. Kit and
renewable data are **not yet parsed** — a gap in the current pipeline.

---

## Match Phases

### Phase 1 — Early Game (Rush)

The match opens with immediate aggression. One or more players from each team
attempt to reach the enemy wool as quickly as possible, before a defense is set up.

**Signals:**
- High movement speed, low time-on-home-island
- Direct trajectory through the map toward the enemy objective
- Inventory count drops fast (blocks spent bridging)
- Engagement with enemies early (combat events near mid-map)
- Low y-level variation unless stair-bridging

**Outcomes:**
- Successful rush: wool captured within the first few minutes — match ends very quickly
- Intercepted rush: defenders catch the rusher, match continues into Phase 2
- Partial rush: attacker reaches the room but cannot escape; stays trapped (see _Extraction_ below)

**Key observation:** Not all maps are equally rushable. Small maps and open-layout
maps tend to produce more frequent early rush wins. This is also match-dependent:
whether the enemy team prioritizes defense affects whether a rush succeeds.

---

### Phase 2 — Defense Setup

If the early rush is repelled, both teams begin fortifying their wool room.
This phase involves digging, block-placing, and resource gathering simultaneously.

**The pit:** Defenders dig out the approach to the wool room down to bedrock (or
the lowest destructible layer). This removes the ground-level attack path.
Once dug, ground-level crossing becomes very difficult.

**Wall construction:** Defenders place blocks directly around and above the wool room.
Materials include crafting tables, water, fences, fence gates, buttons, pressure plates,
and whatever defensive blocks are available in the chests.

**Water walls:** A common defensive technique is building a 3-block-thick wall with
water placed every other layer in the middle section. This makes the wall extremely
slow to push through at ground level (water slows movement). Bypassed entirely by
a successful skybridge.

**Denial items:** After the pit is dug, defenders place crafting tables, furnaces,
fences, buttons, and pressure plates on the remaining surfaces in front of the room.
These slow attackers (right-clicking inventory blocks) and funnel movement.

**Note on lava:** Lava is forbidden and not available on the vast majority of maps.
Water/buckets are available on most maps but not all (detectable from the data).

**Signals (defenders):**
- Stays close to the objective (high proximity to wool room)
- Inventory count may rise (digging), then fall (placing)
- Y-level trends downward (pit digging), then fluctuates around room height
- Combat activity moderate (repelling attackers who got through)

---

### Phase 3 — Mid Game (Stalemate / Skybridging)

Once the ground path is denied or heavily fortified, teams escalate to the
**skybridge** — a bridge built at or near the maximum build height that bypasses
ground-level terrain entirely.

#### The Skybridge as a Parallel Transport Layer

The skybridge is not a new route — it follows the same underlying island and
void-gap topology as the ground route, projected upward. A player crossing at
y ≈ max_build_height travels the same x/z positions as a ground crosser, but
entirely above all constructed defences (pits, water walls, denial items).

**Critical data implication:** The traffic graph is 2D (x/z only). Skybridge
movement and ground movement at the same x/z snap to the _same_ traffic graph
nodes. The `position_events.y` column is the only signal that distinguishes
them. A player who skybrided and one who flat-bridged may produce identical
snapped sequences with different y-profiles.

#### Building a Skybridge

A player starts near spawn, constructs a staircase upward, then bridges
horizontally at the build limit toward the enemy island. The staircase is
water-protected (fences and iron bars placed at intervals let players run up
but resist flooding) to prevent opponents from destroying it. Building is slow
and deliberate — the builder cannot fight effectively while placing blocks.
The staircase is a **commitment signal**: it locks a player out of ground combat
while under construction and announces intent.

Once the staircase reaches the height limit, teammates can run up and extend the
bridge forward. The skybridge grows incrementally over match time and may eventually
expand into a full aerial platform that mirrors the map's island layout.

#### Drop-Down Attack

A player uses the completed or partially-built skybridge to gain height, then
deliberately drops off the structure to land on enemy territory below, bypassing
the fortified ground approach. This is a distinct attack mode:

- Y rises near home spawn → plateaus at max_build_height → drops sharply near
  enemy island → ground-level movement toward enemy wool
- A single life segment can contain: ground traversal → staircase build →
  sky traverse → deliberate drop → ground attack near enemy wool room

Drop-down attacks are likely more common on longer matches where the ground route
is heavily defended, and should be detectable as a characteristic y-profile shape.

#### Counter-Skybridge and Sky Combat

The defending team builds their own staircase from near the wool room toward the
enemy (the **anti-skybridge** or **defensive staircase**). This provides:
- A height advantage to shoot down at the approaching attacker
- A rapid-response route when the enemy's skybridge approaches the wool room

Once both teams have structures at height, bow combat dominates. Attackers push
forward; defenders hold or destroy attacker bridges. Winning sky combat opens a
clean approach to the wool room roof or a drop-in point.

#### Public vs Competitive Skybridge Behaviour

In competitive play, a **communal skybridge** stalemate could form: both teams
build partway toward each other but neither closes the gap — shooting at the
other's builder discourages completing the bridge. This was a major balance problem
that broke several competitive CTW maps.

**In public matches (our dataset), skybridges complete and connect.** The communal
skybridge stalemate is a competitive-tier phenomenon and does not apply to public
match analysis. Skybridge detection in our data can assume that high y-activity
at mid-map x/z positions represents genuine crossing attempts.

#### Tunneling

Separately from skybridging, attackers may dig horizontally or diagonally through
remaining terrain to bypass a surface defence. Only viable where terrain is not
yet fully dug to bedrock. Detectable by sustained y-decrease followed by lateral
movement at low y. Becomes rare or impossible once the pit is complete.

**Signals (attacker on skybridge):**
- Y-level at or near build height limit (y ≥ max_build_height − 2)
- Inventory dropping (bridge construction)
- Bow combat events (aerial exchanges)
- Proximity to enemy objective increasing
- Snapped sequence may be identical to a ground crosser — y is the distinguishing
  signal

**Signals (drop-down attacker):**
- Y rises near home spawn, plateaus at build height, drops sharply near enemy
- Ground-level nodes near enemy territory appear _after_ the high-y phase
- death_region likely `enemy_island` or `bridge`

**Signals (sky defender / anti-skybridger):**
- High y-position near home island — not advancing toward enemy
- Bow combat events at height, directed toward approaching enemy skybridge
- Low max_attack_depth (does not penetrate enemy territory)

---

### Defense Scaling Over Match Time

A structural property of CTW is that defences grow stronger as the match
progresses. This is the primary cause of long stalemates and bimodal duration
distributions:

1. **Pit deepening:** As diggers work, the pit reaches bedrock and becomes
   permanent. Once complete, the flat ground crossing route is eliminated.
   This structural change does not reset between lives — the terrain stays dug.
2. **Wall growth:** Defenders add layers, height, and water. Denial items
   multiply. Escape routes from the wool room are progressively closed. Built
   structures persist until an attacker destroys them.
3. **Player learning:** Defenders optimise their positioning over time.
   Attackers, starting fresh each life, face a progressively more capable setup.

**Resource dynamics:** Attackers respawn with the same starter kit every life
and have equal access to renewable armour. The material constraint lies on the
_defensive side_: the blocks needed for walls, water placements, and denial items
come from finite map chest supplies. Wood is the key defensive building material
and is not always included in the spawn kit — teams sometimes coordinate to
donate material from the chest supply to the defence. Kill rewards (extra blocks)
can supplement this but are unreliable. In practice, defensive materials are
limited by what the map provides, which is a key map balance lever.

The combined effect: the longer a stalemate lasts, the more permanent terrain
changes have accumulated (pit dug, walls placed) and the harder it is for
attackers — who face the same defence fresh each life — to break through.
This paradox was explicitly identified by CTW designer Reshif as the central
game design problem for the genre. His Golden Drought 5 design (ice blocks
limiting water availability, water depleted by attacker actions) was a direct
attempt to reverse the dynamic by making defences weaker over time.

**Analytical implication:** On medium- and long-duration matches, the
distribution of `death_region` and `max_attack_depth` should shift over match
time — attacker lives ending further from the enemy wool in the late match
compared to early, reflecting the accumulated physical defence. This is directly
testable from the existing data (see H9 in `analysis_roadmap.md`).

---

### Phase 4 — Late Game / Resolution

Matches end when one team successfully captures all of the enemy wool.
Late-game scenarios include:

- **Overpowering:** One team dominates in combat, pushing forward relentlessly
- **Attrition:** Repeated deaths exhaust a team's willingness or ability to defend
- **Stalemate break:** A lucky or well-coordinated push slips through when defenders
  are respawning, distracted, or overstretched across ground and sky simultaneously
- **Extraction difficulty:** A player who entered the wool room but cannot exit
  may stay trapped for a very long time until teammates create an opening

---

## Wool Room Combat

The wool region is accessible **only to the attacking team** — defenders cannot
enter. However, combat across the boundary is fully permitted:

- **Bow fire** passes through the region boundary in both directions
- **Melee** is possible when attacker and defender are close to the boundary edge
- Both teams can take damage regardless of who is inside/outside the region
- Attackers can sometimes **build inside the wool room** (defined per-map in XML,
  not of general interest for current analysis)

A trapped attacker can still interact freely within the wool room — they simply
cannot leave through a heavily defended entrance. Options: wait for an opening,
attempt a desperate solo run, or wait for teammates to make a coordinated push.

---

## Player Roles

Roles are not fixed at match start — a player may shift roles during a match.
Role assignment should be done **per life segment**, then aggregated with a
confidence score across all segments for a match-level summary.

Because player IDs are re-assigned per match, cross-match role tracking is not
possible per-player. However, **per-map role frequency** is meaningful: does map X
consistently produce high rusher density? Does map Y tend toward long stalemates?

---

### Rusher

**Definition:** Attempts to penetrate enemy terrain early, aiming for the wool.

**Characteristics:**
- Activates early in the match (low match time at death or capture)
- High movement speed; moves directly toward enemy objective
- Low dwell time on home island
- Path through traffic graph: crosses mid-map nodes quickly
- Combat events near mid-map or enemy territory
- Inventory drops fast (bridging)
- May tunnel if the pit is not yet dug
- May get trapped in the enemy room (very low movement, high proximity to enemy objective, long dwell)

---

### Defender — Archer

**Definition:** Stationed at an elevated position near the wool room; primarily bow combat.

**Characteristics:**
- High proximity to wool room; stays there almost entirely
- Low movement (stationary or patrolling a small zone)
- High bow combat event rate
- Y-level stable or slightly elevated (on walls or fortifications)
- Inventory roughly stable (not building or digging much)

---

### Defender — Digger

**Definition:** Responsible for digging out the pit in front of the wool room.

**Characteristics:**
- High proximity to wool room
- Y-level trends downward over time
- Inventory may increase (collecting dug blocks) but not guaranteed
  (map XML may prevent blocks from dropping)
- Moderate movement (working across the pit area)
- Low combat activity unless attacked while digging

---

### Defender — Wall Builder

**Definition:** Constructs fortifications around and above the wool room.

**Characteristics:**
- Extreme proximity to wool room (working on or adjacent to the room itself)
- Y-level trends upward (building walls higher)
- Inventory drops (placing blocks)
- Uses specific materials: crafting tables, water, fences, fence gates, buttons,
  pressure plates, furnaces, logs (whatever the chests provide)
- Low combat activity

---

### Skybridger (Attacker)

**Definition:** Builds a skybridge toward the enemy room during Phase 3.

**Characteristics:**
- Y-level at or near build height limit
- Inventory drops (bridging material spent)
- Moves toward enemy objective (proximity to enemy wool room increasing)
- Bow combat events at height
- Appears in mid-to-late game (not Phase 1)
- **Note:** snapped sequence alone cannot confirm this role — y-data from
  `position_events` is required to distinguish sky movement from ground movement
  at the same x/z positions

---

### Sky Defender / Anti-Skybridger

**Definition:** Builds and occupies the defensive staircase near the home wool
room to contest an approaching enemy skybridge.

**Characteristics:**
- Y-level at or near build height limit, but positioned over home island —
  not advancing toward enemy territory
- Inventory drops (building staircase and defensive structure upward)
- Bow combat events at height, directed toward an approaching skybridge
- Low `max_attack_depth` (does not penetrate enemy territory)
- Appears in Phase 3, in response to detected enemy sky activity
- **Note:** like the Skybridger, requires y-data from `position_events` —
  the snapped sequence cannot distinguish this role from a ground defender
  at the same x/z positions

---

## Key Analysis Signals Summary

| Signal | Source | Notes |
|---|---|---|
| Y-level over time | position_events | Distinguish ground vs skybridge vs digging; required for Skybridger/Sky Defender roles |
| Y-profile shape | position_events | Rise-plateau-drop = drop-down attack; flat = ground; sustained high = skybridge |
| Proximity to objective | position_events + map_context | Home vs enemy wool room |
| Time on home island | position_events + island classification | Defender vs attacker |
| Movement speed/path | traffic graph nodes | Which route taken across map (2D only) |
| Inventory count change | position_events (inv_count) | Building (down) vs digging (up, sometimes) |
| Combat events | combat_events | Bow vs sword, location |
| Match time at death | life_segments | Early vs mid vs late game |
| Materials used | position_events (held item) | Wall building heuristic |
| death_region | life_segment_traffic_features | First-order role proxy |
| max_attack_depth | life_segment_traffic_features | Penetration depth into enemy territory (lower = deeper) |

---

## Notes on Temporal Staging

Match phases do not have fixed time boundaries — they depend on:
- Map size and layout
- Team composition and skill
- Whether the early rush succeeded
- Whether chests contain sufficient defensive materials

A reasonable heuristic for phase boundaries:
- **Phase 1 (rush):** 0–3 minutes (or until first player death near enemy objective)
- **Phase 2 (defense setup):** 3–10 minutes
- **Phase 3+ (stalemate):** 10+ minutes

But these will need tuning empirically once role signals are extracted from match data.

---

## Notes on Map Variation

Not all maps reach Phase 3. Some maps lack sufficient defensive materials in chests,
meaning walls cannot be built and the match is decided entirely by combat skill.
This is a key hypothesis for the resource/chest analysis:

> Maps with excessive defensive materials relative to their scale (player count × map size)
> tend to produce longer matches and more pronounced Phase 3 stalemates.

Maps also vary in how many void gaps must be bridged, whether bedrock closes off
the pit option, whether there are floating islands reachable only by skybridge,
and how much vertical relief is built into the terrain. Vertically complex maps
(multiple platforms at distinct heights) produce staircase movement as a normal
traversal mechanic rather than just a Phase 3 skybridge activity. The traffic
graph, being 2D, collapses all vertical movement — analysis on such maps should
note this limitation explicitly.

### Map examples (anchored by database)

**Pirates I** — pico-tier, 2 teams × 5 players, 1 wool each, avg match duration **1.7 min**.
No defensive materials beyond starter kit blocks. Water connects islands; some lily pads.
Rectangular layout: home island is a long rectangle, wool and spawn at opposite ends
~15 blocks apart. Designed for early-hour play. Ends fast by design.
Representative of _pure Phase 1 rush_ maps; rarely if ever reaches Phase 3.

**Sanctum Wasser** — milli-tier, 2 teams × 24 players, 2 wools each, avg match duration
**101.8 min** (range 8–222 min). The wool closer to spawn is heavily defended; sky
control is the dominant path in. Representative of _classic Phase 3 skybridge grind_.

---

## Known XML Parsing Gaps

The following mechanics are defined in map XML but **not yet parsed** by the pipeline:

| Feature | Notes |
|---|---|
| Kit contents | `<kits>` module per team — starter items not extracted |
| Renewable resources | `<renewables>` module — regeneration rules not extracted |
| Wool drop on death | Disabling is uncommon; exact XML attribute TBD |
| Safety placement | Disabling is uncommon; exact XML attribute TBD |
| Attacker build rights | Whether attackers can place blocks inside wool room |

These gaps mean kit-based signals (material availability, block type analysis) require
manual inspection of map XML until parsing is implemented.

---

_Last updated: 2026-03-17_
