"""
Explore map characteristics to inform classification system.
"""

import pandas as pd
import numpy as np
from match_analysis import load_map_data, load_match_data, detect_life_segments, assign_teams

# Load data
print("Loading data...")
map_data = load_map_data('Tumbleweed')
match_data = load_match_data('2026-01-24_22-24-17_75.parquet')

# Process
life_segments = detect_life_segments(match_data)
life_segments = assign_teams(life_segments)

# Get all position events
position_events = match_data[match_data['event_type'] == 5].copy()

print("\n" + "="*70)
print("MAP CHARACTERISTICS ANALYSIS")
print("="*70)

# Y-coordinate analysis
print("\nY-COORDINATE DISTRIBUTION:")
print(f"  Min Y: {position_events['y'].min()}")
print(f"  Max Y: {position_events['y'].max()}")
print(f"  Mean Y: {position_events['y'].mean():.2f}")
print(f"  Median Y: {position_events['y'].median():.2f}")
print(f"  Std Dev: {position_events['y'].std():.2f}")

# Find build height (most common max Y value)
y_value_counts = position_events['y'].value_counts()
top_y_values = y_value_counts.head(20)
print(f"\n  Top 20 Y-values by frequency:")
for y_val, count in top_y_values.items():
    print(f"    Y={y_val}: {count} events")

# Detect build height cap (high Y with many events)
high_y_threshold = position_events['y'].quantile(0.95)
high_y_events = position_events[position_events['y'] >= high_y_threshold]
if not high_y_events.empty:
    build_height = high_y_events['y'].mode()[0] if len(high_y_events) > 0 else high_y_threshold
    print(f"\n  Estimated build height (skybridge level): Y={build_height}")
    print(f"  Events at build height: {len(high_y_events)} ({len(high_y_events)/len(position_events)*100:.1f}%)")

# Ground level detection
low_y_threshold = position_events['y'].quantile(0.25)
print(f"\n  Ground level (25th percentile): Y={low_y_threshold:.1f}")

# Tunnel level detection (very low Y)
tunnel_threshold = position_events['y'].quantile(0.05)
tunnel_events = position_events[position_events['y'] <= tunnel_threshold]
print(f"\n  Tunnel level (5th percentile): Y={tunnel_threshold:.1f}")
print(f"  Events in tunnels: {len(tunnel_events)} ({len(tunnel_events)/len(position_events)*100:.1f}%)")

# X and Z coordinate analysis
print("\n" + "="*70)
print("HORIZONTAL POSITIONING:")
print(f"  X range: [{position_events['x'].min():.1f}, {position_events['x'].max():.1f}]")
print(f"  Z range: [{position_events['z'].min():.1f}, {position_events['z'].max():.1f}]")
print(f"  X mean: {position_events['x'].mean():.1f}")
print(f"  Z mean: {position_events['z'].mean():.1f}")

# Team spawn analysis
print("\n" + "="*70)
print("TEAM TERRITORY ANALYSIS:")
red_segments = [seg for seg in life_segments if seg.team == 'red']
blue_segments = [seg for seg in life_segments if seg.team == 'blue']

if red_segments and blue_segments:
    # Get spawn coordinates
    red_spawns = np.array([seg.spawn_coords for seg in red_segments])
    blue_spawns = np.array([seg.spawn_coords for seg in blue_segments])

    red_center = red_spawns.mean(axis=0)
    blue_center = blue_spawns.mean(axis=0)

    print(f"\n  Red team spawn center: X={red_center[0]:.1f}, Y={red_center[1]:.1f}, Z={red_center[2]:.1f}")
    print(f"  Blue team spawn center: X={blue_center[0]:.1f}, Y={blue_center[1]:.1f}, Z={blue_center[2]:.1f}")

    # Determine map split axis
    x_diff = abs(red_center[0] - blue_center[0])
    z_diff = abs(red_center[2] - blue_center[2])

    if z_diff > x_diff:
        # Teams separated by Z coordinate
        midpoint_z = (red_center[2] + blue_center[2]) / 2
        print(f"\n  Teams separated primarily by Z coordinate")
        print(f"  Map midpoint: Z={midpoint_z:.1f}")
        print(f"  Red side: Z > {midpoint_z:.1f}" if red_center[2] > blue_center[2] else f"  Red side: Z < {midpoint_z:.1f}")
        print(f"  Blue side: Z < {midpoint_z:.1f}" if red_center[2] > blue_center[2] else f"  Blue side: Z > {midpoint_z:.1f}")
    else:
        # Teams separated by X coordinate
        midpoint_x = (red_center[0] + blue_center[0]) / 2
        print(f"\n  Teams separated primarily by X coordinate")
        print(f"  Map midpoint: X={midpoint_x:.1f}")
        print(f"  Red side: X > {midpoint_x:.1f}" if red_center[0] > blue_center[0] else f"  Red side: X < {midpoint_x:.1f}")
        print(f"  Blue side: X < {midpoint_x:.1f}" if red_center[0] > blue_center[0] else f"  Blue side: X > {midpoint_x:.1f}")

# Movement analysis
print("\n" + "="*70)
print("MOVEMENT PATTERNS:")

# Sample a few life segments to analyze
sample_segments = [seg for seg in life_segments if len(seg.events) > 10][:10]

for i, segment in enumerate(sample_segments):
    positions = segment.events[segment.events['event_type'] == 5]
    if len(positions) < 2:
        continue

    # Calculate movement metrics
    distances = []
    for j in range(1, len(positions)):
        prev_pos = positions.iloc[j-1]
        curr_pos = positions.iloc[j]
        dist = np.sqrt(
            (curr_pos['x'] - prev_pos['x'])**2 +
            (curr_pos['y'] - prev_pos['y'])**2 +
            (curr_pos['z'] - prev_pos['z'])**2
        )
        distances.append(dist)

    if distances:
        total_distance = sum(distances)
        avg_speed = total_distance / (segment.end_time - segment.spawn_time)
        max_y = positions['y'].max()
        min_y = positions['y'].min()
        y_range = max_y - min_y

        kills = segment.to_dict()['kills']
        deaths = segment.to_dict()['deaths']

        print(f"\n  Segment {i+1} (Player {segment.player_id}, {segment.team} team):")
        print(f"    Duration: {segment.end_time - segment.spawn_time:.1f}s")
        print(f"    Total distance: {total_distance:.1f} blocks")
        print(f"    Avg speed: {avg_speed:.2f} blocks/s")
        print(f"    Y range: [{min_y:.1f}, {max_y:.1f}] (range: {y_range:.1f})")
        print(f"    Kills: {kills}, Deaths: {deaths}")
        print(f"    End reason: {segment.end_reason}")

print("\n" + "="*70)
