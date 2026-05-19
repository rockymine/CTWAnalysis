# PGM XML Reference — CTW Maps

Derived from reading 10 real CTW maps (CommunityMaps + PublicMaps) and the pgm.dev documentation.
Covers all XML elements relevant to the CTW authoring tool. Each section notes what is currently
parsed into `map_data.json` and what is missing.

See `docs/authoring-vision.md` for the authoring tool design. See the
[Activity → Field Mapping](#activity--field-mapping) section for which fields belong in which
editor activity.

---

## Table of Contents

1. [Map Root & Metadata](#1-map-root--metadata)
2. [Teams](#2-teams)
3. [Kits](#3-kits)
4. [Spawns](#4-spawns)
5. [Wools (CTW Objective)](#5-wools-ctw-objective)
6. [Regions](#6-regions)
7. [Filters](#7-filters)
8. [Apply Rules](#8-apply-rules)
9. [Spawners (Wool Respawn)](#9-spawners-wool-respawn)
10. [Block Drops & Renewables](#10-block-drops--renewables)
11. [Activity → Field Mapping](#activity--field-mapping)
12. [Parsing Gaps (Priority Order)](#parsing-gaps-priority-order)

---

## 1. Map Root & Metadata

The root element is `<map proto="1.5.0">`. Proto `1.5.0` is used in all modern maps; older maps
use `1.4.2` which has minor format differences (e.g. no `max-overfill` on teams).

### Required children

| Element | Notes |
|---------|-------|
| `<name>` | Display name shown in-game |
| `<version>` | Semantic versioning: X.Y.Z |
| `<objective>` | Match goal shown at match start |
| `<authors>` | At least one `<author>` required |

### Optional children

| Element | Values | Notes |
|---------|--------|-------|
| `<slug>` | lowercase alphanumeric + `_` | Auto-generated from name if omitted |
| `<phase>` | `development` / `staging` / `production` | Default: production |
| `<edition>` | `standard` / `ranked` / `tournament` | Default: standard |
| `<game>` | free text | Custom gamemode title (display only) |
| `<gamemode>` | `ctw`, `dtc`, `tdm`, etc. | Auto-detected if omitted |
| `<created>` | `YYYY-MM-DD` | Map release date |
| `<max-build-height>` | integer | Blocks above this Y are buildable; no default |
| `<constants>` | — | Template substitution block (see below) |

### Authors and contributors

```xml
<authors>
  <author uuid="ef4ea31a-..." contribution="Map design"/>
  <contributor uuid="7b0bac3e-..." contribution="XML"/>
</authors>
```

Both `<author>` and `<contributor>` accept:
- `uuid` — Minecraft player UUID (required; enables mapmaker perks on PGM servers)
- `contribution` — free text description of their role

Player display names must be resolved from UUID via the Mojang API; they are not stored in the XML.

### Constants (template substitution)

```xml
<constants>
  <constant id="team-size">32</constant>
  <constant id="max-overfill">40</constant>
</constants>
```

Referenced anywhere in the XML as `${team-size}`. Used in competitive variants (Jurassic, Jungle Beat)
to toggle team sizes and time limits per variant. Constants are not resolved during parsing today.

### Variants

Some maps define `variant` attributes or `<if variant="...">` / `<unless variant="...">` blocks
to conditionally include content for different editions (e.g. Halloween, competitive). Not relevant
to most maps; treat as read-only if present.

### Currently parsed

`name`, `version`, `objective`, `max_build_height`, authors (uuid + role + contribution).

**Missing:** `phase`, `edition`, `game`, `gamemode`, `created`, `slug`, constants.

---

## 2. Teams

```xml
<teams>
  <team id="blue-team" color="blue" dye-color="light blue"
        max="32" min="1" max-overfill="40" plural="false">Blue</team>
  <team id="red-team"  color="dark red" dye-color="red" max="${team-size}">Red</team>
</teams>
```

### Attributes

| Attribute | Required | Default | Notes |
|-----------|----------|---------|-------|
| `id` | Yes | — | Reference key used in spawns, wools, filters |
| text content | Yes | — | Display name |
| `color` | No | — | Chat color for team name in scoreboard/chat |
| `dye-color` | No | same as `color` | Overrides color for team-colored items (leather armor, stained clay). Must use dye color names (e.g. `light blue` not `cyan`) |
| `max` | No | unlimited | Soft player cap; supports `${constant}` |
| `min` | No | 0 | Minimum players to start a match |
| `max-overfill` | No | 125% of max | Hard player cap; premium players cannot exceed this |
| `plural` | No | auto | Whether team name is plural; affects win messages |
| `show-name-tags` | No | `true` | `true` / `false` / `allies` / `enemies` |

### Valid color names (PGM chat colors)

`black`, `dark_blue`, `dark_green`, `dark_aqua`, `dark_red`, `dark_purple`, `gold`, `gray`,
`dark_gray`, `blue`, `green`, `aqua`, `red`, `light_purple`, `yellow`, `white`.
Most maps use the shorter form without underscores (e.g. `dark red`).

### Currently parsed

`id`, name, `color`, `dye_color`, `max_players`, `min_players`.

**Missing:** `max-overfill`, `plural`, `show-name-tags`.

---

## 3. Kits

Kits define player loadouts. They are applied at spawn, by apply rules, or conditionally.

```xml
<kits>
  <kit id="spawn-kit" force="true">
    <clear/>
    <item slot="0" material="iron sword" unbreakable="true"/>
    <item slot="1" material="bow" enchantment="arrow infinite:1"/>
    <item slot="8" material="stained clay" damage="5" amount="32" team-color="true"/>
    <helmet   material="iron helmet" unbreakable="true"/>
    <chestplate material="leather chestplate" team-color="true" unbreakable="true"/>
    <leggings material="leather leggings" team-color="true"/>
    <boots    material="leather boots"    team-color="true"/>
    <effect duration="oo" amplifier="100">damage resistance</effect>
  </kit>

  <kit id="blue-kit" parents="spawn-kit">
    <!-- inherits spawn-kit; can override or add items -->
  </kit>

  <kit id="reset-kit">
    <clear effects="true" items="false" armor="false"/>
  </kit>
</kits>
```

### Kit attributes

| Attribute | Default | Notes |
|-----------|---------|-------|
| `id` | — | Reference key |
| `parents` | — | Comma-separated list of parent kit IDs (inheritance chain) |
| `force` | `false` | Override existing inventory/armor when applied |
| `filter` | — | Only apply if filter matches |
| `drop-overflow` | `false` | Drop excess items instead of discarding |
| `potion-particles` | `false` | Show potion effect particles |

### Item / armor attributes

| Attribute | Notes |
|-----------|-------|
| `slot` | Inventory slot number (0–8 = hotbar, 9–35 = main inventory, 36–39 = armor) |
| `material` | Material name (e.g. `iron sword`, `stained clay`) |
| `amount` | Stack size; default 1 |
| `damage` | Damage/variant value (e.g. wool color: `damage="14"` = red wool) |
| `unbreakable` | `true`/`false` |
| `team-color` | `true` — dye color set to player's team dye color |
| `enchantment` | Inline: `"name:level"` or `"name"` for level 1. Multiple via nested `<enchantment>` |
| `custom-name` | Display name override |
| `color` | RGB integer for leather armor color (e.g. `color="3568952"`) |
| `lore` | Item lore line (use `<lore>` sub-element for multiple lines) |

Armor slots: `<helmet>`, `<chestplate>`, `<leggings>`, `<boots>` — same attributes as `<item>` minus `slot`.

### Effects

```xml
<effect duration="10s" amplifier="4">speed</effect>
<effect duration="oo"  amplifier="100">damage resistance</effect>
```

`duration="oo"` = infinite. `amplifier` is 0-indexed (amplifier=1 → Potion Level II).

### Conditional sub-kits

```xml
<give kit="bonus-kit" filter="only-blue"/>   <!-- applied once; permanent -->
<lend kit="speed-kit" filter="on-bridge"/>   <!-- applied while filter true; removed when false -->
<take kit="bonus-kit" filter="not-blue"/>    <!-- removes a previously given kit -->
```

### Other kit elements

`<clear items="true" armor="true" effects="false"/>`, `<game-mode>survival</game-mode>`,
`<health>10</health>`, `<max-health>40</max-health>`, `<saturation>20</saturation>`,
`<foodlevel>20</foodlevel>`, `<walk-speed>1.8</walk-speed>`,
`<fly can-fly="true" flying="false" fly-speed="1"/>`,
`<double-jump power="3" recharge-time="2.5s"/>`,
`<knockback-reduction>0.5</knockback-reduction>`,
`<shield health="4" delay="8s"/>`,
`<attribute operation="add" amount="0.5">generic.movementSpeed</attribute>`.

### Currently parsed

`id`, `parents`, `force`, `filter`, items (slot / material / amount / damage / unbreakable /
team-color / enchantments), armor pieces.

**Missing:** `lend`/`give`/`take` sub-kits, structured effect parsing, `game-mode`, attribute
modifiers, `walk-speed`, `fly`, `double-jump`.

---

## 4. Spawns

```xml
<spawns>
  <default kit="observer-kit">
    <regions yaw="0"><point>0,64,0</point></regions>
  </default>
  <spawn team="blue-team" kit="blue-kit">
    <regions yaw="90"><cylinder base="-20,10,-50" radius="4" height="0"/></regions>
  </spawn>
  <spawn team="red-team" kit="red-kit" region="red-spawn"/>
</spawns>
```

### Spawn attributes

| Attribute | Notes |
|-----------|-------|
| `team` | Team ID. Omit for observer spawn (use `<default>` instead) |
| `kit` | Kit ID to apply on spawn |
| `region` | Region reference (alternative to inline `<regions>` child) |
| `safe` | Validate that spawn position is safe (no suffocation) |
| `sequential` | Try next region if current is unsafe |
| `spread` | Maximize distance from enemies at spawn |
| `spread-teammates` | Maximize distance from teammates at spawn |
| `exclusive` | Reserve spawn region for one player/team |
| `outdoors` | Spawn at highest non-solid point |
| `persistent` | Retain spawn assignment on rejoin |
| `filter` | Conditional spawn eligibility |

### Regions sub-element

```xml
<regions yaw="90" pitch="0">
  <cuboid min="-16,10,-197" max="1,17,-185"/>
</regions>
```

- `yaw` — horizontal facing in degrees. 0 = south, 90 = west, 180 = north, -90 = east.
- `pitch` — vertical facing. 0 = horizontal, -90 = looking up, 90 = looking down.
- `angle` — alternative: specify a block coordinate to face instead of yaw/pitch.

### Respawn configuration

```xml
<respawn delay="3s" auto="true" blackout="false" spectate="true" bed="false">
  <message>You will respawn in {0} seconds.</message>
</respawn>
```

Configured as a standalone element at the top level (not inside `<spawns>`).

### Currently parsed

Team, kit, yaw, region (inline or reference), observer spawn (`<default>`).

**Missing:** `safe`, `sequential`, `spread`, `persistent`, respawn config element.

---

## 5. Wools (CTW Objective)

Wools are the win condition for CTW. Each wool has a pickup location and a monument (placement target).

### Two formats seen in the wild

**Format A — group by team, monument as region reference** (older, still common):
```xml
<wools team="blue-team">
  <wool color="red"  location="-23,19,95" monument="blue-red-monument"/>
  <wool color="lime" location="  5,19,95" monument="blue-lime-monument"/>
</wools>
<!-- monument defined elsewhere as a named region -->
<block id="blue-red-monument">112,20,77</block>
```

**Format B — inline monument block** (current preferred):
```xml
<wools>
  <wool team="blue-team" color="red" location="-23,19,95">
    <monument><block>112,20,77</block></monument>
  </wool>
</wools>
```

Both formats are in active use. The parser must handle both.

### Wool attributes

| Attribute | Required | Default | Notes |
|-----------|----------|---------|-------|
| `team` | Yes | — | Can be set on parent `<wools>` group or individual `<wool>` |
| `color` | Yes | — | Dye color name (e.g. `red`, `lime`, `light blue`). Supports `${constant}` |
| `location` | Yes | — | `X,Y,Z` — where the wool block initially spawns in the world |
| `monument` | Yes | — | Region ref (Format A) or nested `<monument><block>X,Y,Z</block></monument>` |
| `id` | No | — | For referencing in filters (e.g. `<completed>wool-id</completed>`) |
| `required` | No | `true` | Whether capturing this wool is required to win |
| `craftable` | No | `true` | Whether players can craft this wool color |
| `show-messages` | No | `true` | Broadcast in chat when captured |
| `show-effects` | No | `true` | Play sounds/fireworks on capture |
| `show-info` | No | `true` | Listed in `/match` command |
| `show-sidebar` | No | `true` | Shown on scoreboard |
| `show-waypoint` | No | `true` | Locator bar waypoint (1.21.6+) |
| `wool-proximity-metric` | No | `closest kill` | `player` / `closest block` / `closest kill` / `none` |
| `wool-proximity-horizontal` | No | `false` | Horizontal-only proximity |
| `monument-proximity-metric` | No | `closest block` | Same options |
| `monument-proximity-horizontal` | No | `false` | — |

### Currently parsed

`team`, `color`, `location` (x/y/z), `monument` (x/y/z block position).

**Missing:** `id`, `required`, `craftable`, `show-*`, proximity metrics.

---

## 6. Regions

Regions define geometric areas used by spawns, wools, apply rules, filters, and spawners.
They may be declared inside a `<regions>` block (with id for reuse) or inline (anonymous).

### Primitive — block-bounded (3D)

| Element | Key Attributes | Notes |
|---------|----------------|-------|
| `<cuboid>` | `min="X,Y,Z" max="X,Y,Z"` | Axis-aligned box |
| `<cylinder>` | `base="X,Y,Z" radius="R" height="H"` | Upright cylinder |
| `<sphere>` | `origin="X,Y,Z" radius="R"` | Spherical volume |
| `<block>` | text content: `X,Y,Z` | Single block |
| `<point>` | text content: `X,Y,Z`, optional `yaw`, `pitch` | Point with facing direction |

### Primitive — unbounded (2D, extend through all Y)

| Element | Key Attributes |
|---------|----------------|
| `<rectangle>` | `min="X,Z" max="X,Z"` |
| `<circle>` | `center="X,Z" radius="R"` |
| `<half>` | `normal="X,Y,Z" origin="X,Y,Z"` — plane half-space |
| `<above>` | `y="N"` |
| `<below>` | `y="N"` |

### Static

`<everywhere/>` — infinite region. `<nowhere/>` / `<empty/>` — empty region.

### Composite

| Element | Behavior |
|---------|----------|
| `<union>` | All children combined |
| `<intersect>` | Only overlapping areas |
| `<complement>` | First child minus each successive child |
| `<negative>` | Inverse of a single child |

### Transforms

```xml
<mirror id="red-spawn-mirror" normal="0,0,1" origin="0,0,0">
  <region id="blue-spawn"/>
</mirror>
<translate id="red-wool-room" offset="0,0,200">
  <region id="blue-wool-room"/>
</translate>
```

`<mirror>` flips across a plane defined by `normal` and `origin`.
`<translate>` shifts by a fixed offset vector.

### All region types accept `id` for named reuse

Regions without `id` are inline/anonymous and cannot be referenced elsewhere.

### Currently parsed

All region types listed above. Well-covered by `xml_analysis/regions.py`.

---

## 7. Filters

Filters are boolean predicates evaluated against events (block break, player entry, etc.).
They are defined in a `<filters>` block with IDs for reuse, then referenced in `<apply>` rules.

```xml
<filters>
  <team   id="only-blue">blue-team</team>
  <not    id="not-blue"><filter id="only-blue"/></not>
  <all    id="blue-place-wool"><team>blue-team</team><material>wool:14</material></all>
  <any    id="deny-wools">
    <material>wool:0</material><material>wool:1</material><!-- ...all 16 colors -->
  </any>
  <material id="only-iron">iron block</material>
  <material id="only-air">air</material>
  <void   id="in-void"/>
  <always id="allow-all"/>
  <never  id="deny-all"/>
</filters>
```

### Logic combinators

| Element | Behavior |
|---------|----------|
| `<all>` | ALLOW only if ALL children allow |
| `<any>` | ALLOW if ANY child allows |
| `<not>` | Inverts a single child |
| `<one>` | ALLOW only if exactly ONE child allows |
| `<allow/>` | Force ALLOW result |
| `<deny/>` | Force DENY result |

### Common filter types

| Element | Tests |
|---------|-------|
| `<team>team-id</team>` | Player is on this team |
| `<material>name</material>` or `<material>name:damage</material>` | Block/item material match |
| `<void/>` | Block is void (air at Y=0) |
| `<cause>PLAYER</cause>` | Event caused by a player (vs. WORLD, MOB, etc.) |
| `<participating/>` | Player is in the match (not observing) |
| `<observing/>` | Player is observing |
| `<blocks region="id"/>` | Block matches original map state |
| `<players min="1" max="5"/>` | Player count in region |
| `<effect amplifier="2">speed</effect>` | Player has potion effect |
| `<carrying>` / `<holding>` / `<wearing>` | Player inventory checks |
| `<random>0.5</random>` | 50% probability |
| `<after duration="5m">` | Time since match start |
| `<pulse period="0.1s" duration="0.05s">` | Periodic pulsing filter |
| `<offset vector="~0,~-1,~0">` | Offset test position (relative coords with `~`) |
| `<completed>objective-id</completed>` | Objective is complete |

### Currently parsed

**NOT parsed as structured objects.** `<apply>` rules store filter references as plain strings
(e.g. `"only-blue"`). The `<filters>` block is completely ignored during XML parsing.

This is the largest single gap in the current analysis pipeline.

---

## 8. Apply Rules

Apply rules wire regions to filters and actions. They enforce game rules spatially.

```xml
<apply region="blue-base"        enter="only-blue"       message="You may not enter the enemy base!"/>
<apply region="spawn-protection" block-place="deny-all"  block-break="deny-all"/>
<apply region="blue-build"       block="only-blue"/>
<apply region="not-bases"        kit="reset-resistance-kit"/>
<apply                           block-physics="deny-lava"/>
```

### Attributes

| Attribute | Notes |
|-----------|-------|
| `region` | Region reference (or inline region as child element). If omitted, applies globally |
| `enter` | Filter checked when a player enters the region |
| `leave` | Filter checked when a player leaves |
| `block` | Filter for all block interactions (place + break) |
| `block-place` | Filter for block placement only |
| `block-break` | Filter for block breaking only |
| `use` | Filter for right-click use (droppers, buttons, etc.) |
| `kit` | Kit ID to apply to players entering the region |
| `lend-kit` | Kit ID lent to players while in the region (removed on exit) |
| `velocity` | Apply velocity vector `X,Y,Z` to entering players |
| `message` | Message shown when an action is denied |
| `block-physics` | Filter for block physics events (e.g. deny falling sand/gravel) |

### Currently parsed

`region_id`, `block_filter`, `block_place_filter`, `block_break_filter`, `use_filter`, `message`.

**Missing:** `enter`, `leave`, `kit`, `lend-kit`, `velocity`, `block-physics`.

---

## 9. Spawners (Wool Respawn)

Spawners periodically drop items into a region when players are present in an activation zone.
In CTW maps they are used exclusively to respawn wool blocks after they are picked up.

```xml
<spawners>
  <spawner spawn-region="blue-wool-spawn"
           player-region="blue-woolroom"
           delay="3s"
           max-entities="3">
    <item material="wool" damage="11" amount="3"/>
  </spawner>
</spawners>
```

### Attributes

| Attribute | Required | Default | Notes |
|-----------|----------|---------|-------|
| `spawn-region` | Yes | — | Where items appear |
| `player-region` | Yes | — | Must contain ≥1 player for spawner to activate |
| `delay` | No | `10s` | Interval between spawns |
| `min-delay` | No | — | Random delay lower bound (overrides `delay`) |
| `max-delay` | No | — | Random delay upper bound |
| `max-entities` | No | unlimited | Maximum concurrent dropped items |
| `filter` | No | — | Additional activation condition |

### Sub-elements

- `<item material="..." damage="..." amount="..."/>` — item to drop (uses kit item syntax)
- `<potion>` — splash potion

### Relationship to wool

Each wool typically has one corresponding spawner. The `damage` value on the item must match
the wool's color (e.g. `damage="14"` = red wool). The `spawn-region` should be a point or small
area near or above where the wool should land. The `player-region` is typically the entire
wool room so defenders must be present to trigger respawn.

### Currently parsed

**NOT parsed at all.** Completely absent from `map_data.json`.

---

## 10. Block Drops & Renewables

### Block Drops

Custom item drops when a block is broken. In CTW, used to make iron blocks in spawn areas
always drop iron blocks regardless of tool, or to configure wool replacement behavior.

```xml
<block-drops>
  <rule region="woolrooms" filter="only-iron" wrong-tool="false">
    <drops>
      <item material="iron block"/>
    </drops>
    <replacement>iron block</replacement>
  </rule>
</block-drops>
```

### Rule attributes

| Attribute | Default | Notes |
|-----------|---------|-------|
| `filter` | — | Which blocks/events this rule targets |
| `region` | — | Limit rule to this geographic area |
| `kit` | — | Award this kit when rule fires |
| `experience` | 0 | XP amount dropped |
| `replacement` | `air` | Block placed where the broken block was |
| `wrong-tool` | `false` | Apply even if wrong tool used |
| `punch` | `false` | Apply on punch (no break) |
| `trample` | `false` | Apply when walked on |

The `<drops>` child element contains `<item>` elements with an optional `chance="0.0-1.0"` attribute.
If `<drops>` is empty or absent, the block drops nothing.

### Renewables

Renewables automatically regenerate broken blocks in a region. In CTW, used to regenerate
iron/gold blocks at spawns so players always have building materials.

```xml
<renewables>
  <renewable region="spawns"
             rate="1"
             renew-filter="only-iron"
             replace-filter="only-air"
             avoid-players="2"
             grow="false"
             particles="true"
             sound="true"
             avoid-entities="true"/>
</renewables>
```

Nested filter sub-elements (alternative to filter ID references):

```xml
<renewable region="iron-regen" rate="1.5" grow="false" particles="true" sound="true" avoid-entities="true">
  <renew-filter><material>iron block</material></renew-filter>
  <replace-filter><material>air</material></replace-filter>
</renewable>
```

### Renewable attributes

| Attribute | Notes |
|-----------|-------|
| `region` | Area where blocks regenerate |
| `rate` | Blocks regenerated per second |
| `renew-filter` | Filter matching blocks that should regenerate |
| `replace-filter` | Filter matching blocks that can be replaced (usually `only-air`) |
| `avoid-players` | Don't regenerate within N blocks of a player |
| `avoid-entities` | Don't regenerate if entities present |
| `grow` | Regenerate from existing blocks outward (like ice spreading) |
| `particles` | Show particle effect during regeneration |
| `sound` | Play sound during regeneration |

### Currently parsed

**NOT parsed at all.** Both `<block-drops>` and `<renewables>` are completely absent from
`map_data.json`.

---

## Activity → Field Mapping

This section maps each editor activity (rail icon) to the XML fields it should display and allow
editing. Ties the XML reference above to the authoring tool UI defined in `authoring-vision.md`.

---

### Overview (`book-open-text`)

Editable fields:
- Map `<name>`, `<version>`, `<objective>`
- `<phase>`, `<edition>`, `<gamemode>`, `<created>`
- `<max-build-height>`
- Authors list: UUID, role (`author` / `contributor`), contribution text
- `<slug>` (read-only display)
- `<constants>` block (read-only display; not editable in first version)

Currently in `map_data.json`: name, version, objective, max_build_height, authors.
**Need to add:** phase, edition, gamemode, created.

---

### Players & Teams (`users`)

Editable fields:
- Team list: id, display name, color, dye-color, max, min, max-overfill, plural, show-name-tags
- Team spawn per team: region reference + yaw, kit reference
- Observer spawn (`<default>`): region reference + yaw, kit reference
- Respawn config: delay, auto, blackout, spectate, bed

Currently in `map_data.json`: team id/name/color/dye_color/max/min, spawns (team/kit/yaw/region).
**Missing:** max-overfill, plural, show-name-tags, respawn config.

---

### Objective (`goal`)

Editable fields per wool:
- Team, color, location (x/y/z), monument block (x/y/z)
- Optional: required, craftable, show-messages, show-effects, show-sidebar
- Spawner: spawn-region, player-region, delay, max-entities, item (material + damage = color)
- Block-drop rules: region, filter (usually `only-air`), replacement material
- Renewables: region, rate, renew-filter, replace-filter

**`api_query_wool_in_region` integration:**
- Call inline in this activity when the user sets a wool location.
- Show per-wool status: "Wool block found in world ✓" or "No wool block found at this location ✗".
- Result determines whether a spawner is recommended (open area = spawner needed; safe locked room = spawner optional).
- Also called from Validation activity as a batch check across all wools.

Currently in `map_data.json`: wool team/color/location/monument.
**Missing (not parsed):** required, craftable, show-*, spawners, block-drops, renewables.

---

### Regions (`layout-dashboard`)

The current region editor. No new fields needed beyond what is already implemented.

All region types are well-covered in the parser. Future work: region categorization and
linking regions to their usage context (which spawn/wool/apply references a given region).

---

### Rules & Filters (`gavel`)

Editable:
- Named filter definitions: `<team>`, `<material>`, `<all>`, `<any>`, `<not>` combinators
- Apply rules: region + enter/leave/block-place/block-break/use/kit/message/block-physics

**Priority for first implementation:** parse and display named `<team>` and `<material>` filters
as a list. Complex combinators (all/any/not) shown as read-only raw XML in the first version.
Apply rules can be listed with region + filter string references shown as text.

Currently in `map_data.json`: apply rules partially (block filter strings, region ref, message).
Named filter definitions not parsed at all.

---

### Validation (`bug`)

Read-only checklist. Calls validation checks across all activities:

1. Name, version, objective are non-empty
2. At least one author
3. At least one team defined
4. Each team has a spawn
5. Observer spawn exists
6. Each wool has a valid location and monument
7. **Wool world verification** — `api_query_wool_in_region` for all wools; show "N/M wools confirmed in world"
8. Each region referenced in spawns/wools/apply rules is defined
9. Each filter referenced in apply rules is defined
10. Build region exists (from `build_regions` analysis)
11. No unresolved region/filter references

---

### Export (`archive`)

Shows: validation summary, XML preview panel, download/copy button.
Export is blocked if any critical validation errors are present (required fields missing,
unresolved references). Warnings (optional fields missing) do not block export.

---

## Parsing Gaps (Priority Order)

Ranked by importance for the next authoring UI activities to implement:

| Gap | Priority | Activity | Notes |
|-----|----------|----------|-------|
| `<spawners>` | High | Objective | Completely absent from `map_data.json`; needed for wool respawn config |
| `<renewables>` | High | Objective | Completely absent; needed for iron/gold block regeneration display |
| `<block-drops>` | Medium | Objective | Completely absent; needed for wool replacement rules |
| Named filter definitions (`<filters>` block) | Medium | Rules & Filters | Ignored entirely; apply rules only store filter ID strings |
| Apply `enter`/`leave`/`kit`/`lend-kit`/`velocity`/`block-physics` | Medium | Rules & Filters | These attributes on `<apply>` are silently dropped |
| Wool optional flags (`required`, `craftable`, `show-*`) | Low | Objective | Defaulting to true is safe; add when Objective editor is implemented |
| Team `max-overfill`, `plural`, `show-name-tags` | Low | Players & Teams | Uncommon; defaults are fine for most maps |
| Respawn config (`<respawn>`) | Low | Players & Teams | Not common to customize; defaults acceptable |
| Root metadata: `phase`, `edition`, `created`, `gamemode` | Low | Overview | Safe to default/omit |
| Kit conditional sub-kits (`<lend>`, `<give>`, `<take>`) | Low | — | Complex; show as read-only raw XML until kit editor is built |
| Constants and variants | Very low | Overview | Read-only display only; no editing needed |
