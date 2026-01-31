# CTW Life Segment Classification System

## Overview

The classification system analyzes player life segments (spawn → death/match_end/team_switch) and categorizes them based on positioning, movement patterns, and combat actions.

## Map Characteristics Detection

The system automatically analyzes each match to determine:

- **Map Midpoint**: Dividing line between team territories (Z=-42.5 for Tumbleweed)
- **Team Sides**: Which team spawns on which side
- **Skybridge Height**: Y-coordinate of build ceiling (Y=29 for Tumbleweed)
- **Ground Level**: Typical ground height (Y=9 for Tumbleweed)
- **Tunnel Threshold**: Underground level (Y≤2 for Tumbleweed)

## Classification Categories

### 1. WOOL_RUNNER (1.5% of segments)
**Definition**: Carries wool from enemy base to own base

**Characteristics**:
- Has wool touch or wool capture events
- Typically high movement speed
- Moves from enemy territory back to own side

**Example Metrics**:
- Speed: 3.09 blocks/s
- 36% time on own side, 59% on enemy side
- Max penetration: 100+ blocks

### 2. SKYBRIDGE_CONTROLLER (0.9% of segments)
**Definition**: Stays on skybridge (high altitude), controls lanes with kills

**Characteristics**:
- 70%+ time at skybridge height (Y≥28)
- 2+ kills while at height
- Controls movement lanes from above

**Example Metrics**:
- 91% time at skybridge
- 2-4 kills per segment
- Low horizontal movement

### 3. ATTACKER_STEALTH (0.2% of segments)
**Definition**: Uses tunnels to infiltrate enemy territory

**Characteristics**:
- 50%+ time below tunnel threshold (Y≤2)
- 60%+ time on enemy side
- Infiltrates without being seen above ground

**Example Metrics**:
- 70%+ time tunneling
- Deep penetration into enemy base
- Low kill counts (stealthy)

### 4. RUSHER (0.1% of segments)
**Definition**: Fast movement to enemy side immediately after spawn

**Characteristics**:
- Speed > 3.0 blocks/s
- 70%+ time on enemy side
- Short duration segments (<120s)

**Example Metrics**:
- Speed: 4-6 blocks/s
- Immediate push after spawn
- High risk, quick death or kill

### 5. ATTACKER_AGGRESSIVE (4.7% of segments)
**Definition**: Pushes enemy side with high kill count

**Characteristics**:
- 60%+ time on enemy territory
- 2+ kills
- Active combat engagement

**Example Metrics**:
- 91% time on enemy side
- 2-3 kills per segment
- Deep penetration with combat

**Team Distribution**:
- Blue team: 8.2% (more aggressive)
- Red team: 1.7% (more defensive)

### 6. ATTACKER_PASSIVE (4.6% of segments)
**Definition**: Moves to enemy side without many kills

**Characteristics**:
- 60%+ time on enemy territory
- <2 kills
- Applies pressure without combat

**Example Metrics**:
- 70-90% time on enemy side
- Scouting or positioning focus
- Medium penetration

### 7. CAMPER (0.1% of segments)
**Definition**: Minimal movement, waits for enemies and gets kills

**Characteristics**:
- Speed < 0.5 blocks/s
- 2+ kills
- Stays in one area

**Example Metrics**:
- Near-zero movement speed
- High kill efficiency
- Trap-based gameplay

### 8. MID_CONTROLLER (8.1% of segments)
**Definition**: Controls the middle area between territories

**Characteristics**:
- Balanced territory split (40-60% each side)
- 1+ kills
- Fights near midpoint

**Example Metrics**:
- 54% own side, 40% enemy side
- 1-2 kills
- Mobile combat style

**Team Distribution**:
- Blue team: 14.1% (pushes mid)
- Red team: 3.1% (more defensive)

### 9. BASE_DEFENDER (47.1% of segments)
**Definition**: Guards own spawn area

**Characteristics**:
- 80%+ time on own side
- Stays within 30 blocks of spawn
- Reactive positioning

**Example Metrics**:
- 90-97% time on own side
- Low penetration depth
- Spawn protection focus

**Team Distribution**:
- Red team: 59.9% (very defensive)
- Blue team: 32.1% (more balanced)

### 10. DEFENDER (18.3% of segments)
**Definition**: Stays primarily on own side

**Characteristics**:
- 60-80% time on own side
- May venture to mid or enemy side occasionally
- Less rigid than base defenders

**Example Metrics**:
- 66-78% time on own side
- Some enemy territory incursions
- Medium mobility

### 11. FLANKER (8.3% of segments)
**Definition**: Moves around map edges with high mobility

**Characteristics**:
- Total distance > 200 blocks
- Territory split 30-70% (crosses sides frequently)
- High movement speed

**Example Metrics**:
- 300-350 blocks traveled
- 2.5-3.5 blocks/s speed
- Crosses territories multiple times

### 12. ROAMER (4.6% of segments)
**Definition**: General roaming without clear pattern

**Characteristics**:
- Doesn't fit other categories
- Mixed behavior
- No dominant strategy

## Secondary Role Tags

Players can have secondary characteristics:

- **skybridge_user**: Spends 30%+ time at skybridge height
- **tunneler**: Spends 20%+ time underground
- **high_kills**: 3+ kills with >1.0 kills/minute
- **mobile**: Speed > 2.5 blocks/s

## Team-Specific Playstyles

### Red Team (More Defensive)
1. BASE_DEFENDER: 59.9%
2. DEFENDER: 19.2%
3. FLANKER: 5.6%
4. ROAMER: 5.0%
5. MID_CONTROLLER: 3.1%

**Overall**: Red team focuses heavily on defense, with 79% of segments in defensive roles.

### Blue Team (More Aggressive)
1. BASE_DEFENDER: 32.1%
2. DEFENDER: 17.3%
3. MID_CONTROLLER: 14.1%
4. FLANKER: 11.6%
5. ATTACKER_AGGRESSIVE: 8.2%

**Overall**: Blue team shows more balanced play, with 30% in mid-control and attacking roles.

## Usage

### Run Classification Analysis

```bash
py classify_segments.py
```

### Generate Role-Based Visualizations

You can also generate plots showing only segments from specific roles by enabling them in [config.json](config.json):

```json
"role_settings": {
  "wool_runner": true,
  "attacker_aggressive": true,
  "rusher": true,
  ...
}
```

Then run:
```bash
py generate_plots.py
```

This will create separate PNG files for each enabled role (e.g., `wool_runner.png`, `rusher.png`) showing all life segments classified as that role.

### Output Files

1. **classification_report.txt**: Detailed text report with:
   - Map characteristics
   - Role distribution
   - Role definitions
   - Team-specific statistics
   - Top players by role
   - Detailed segment examples

2. **segment_classifications.csv**: CSV export with all segments and metrics:
   - segment_id, player_id, team
   - Timing metrics (time on own/enemy side, skybridge, tunneling)
   - Movement metrics (distance, speed, penetration)
   - Combat metrics (kills, deaths)
   - Wool interactions
   - Primary and secondary roles

## Key Insights from Sample Match

### Most Common Playstyles
1. **Base Defense** (47%): Players prioritize protecting their spawn
2. **General Defense** (18%): Players stay on their side but roam
3. **Flanking** (8%): High mobility players crossing territories
4. **Mid Control** (8%): Fighting for map center

### Rare Specialist Roles
- Wool Runners: Only 25 segments (1.5%) - wool captures are rare!
- Skybridge Controllers: 16 segments (0.9%)
- Stealth Tunnelers: 4 segments (0.2%)
- Rushers: 2 segments (0.1%)

### Combat Patterns
- **Aggressive Attackers** average 2-3 kills with 91% enemy territory time
- **Mid Controllers** average 1-2 kills at the map midpoint
- **Campers** get 2+ kills while barely moving

### Movement Speed Ranges
- Campers: <0.5 blocks/s
- Base Defenders: 1.5-2.5 blocks/s
- Flankers: 2.5-3.5 blocks/s
- Rushers: 3.0-6.0 blocks/s

## Algorithm Details

The classification system uses a rule-based approach with priority ordering:

1. **Wool Priority**: Wool interactions = immediate WOOL_RUNNER classification
2. **Skybridge Check**: 70%+ skybridge time + kills = SKYBRIDGE_CONTROLLER
3. **Tunnel Check**: 50%+ tunnel time + enemy territory = ATTACKER_STEALTH
4. **Speed Check**: High speed + enemy territory + short duration = RUSHER
5. **Combat Check**: Enemy territory + kill count determines attacker type
6. **Position Check**: Territory ratios determine defender types
7. **Mobility Check**: High distance traveled = FLANKER
8. **Default**: ROAMER

Each classification includes confidence scores (50-100) based on how well the segment matches the role criteria.

## Future Enhancements

Potential additions to the classification system:

1. **Temporal Analysis**: Early game vs late game behavior shifts
2. **Player Archetypes**: Aggregate classifications across all segments per player
3. **Team Coordination**: Detect coordinated attacks or defenses
4. **Wool Route Analysis**: Map common wool running paths
5. **Kill Location Heatmaps**: Where do different roles get kills?
6. **Effectiveness Metrics**: Which roles have highest K/D ratios?
