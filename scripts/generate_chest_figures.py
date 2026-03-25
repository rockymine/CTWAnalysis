"""
Generate 4 matplotlib figures for the chest spatial analysis report.
Run from the repo root: python scripts/generate_chest_figures.py
Output figures are written to docs/figures/.
"""

import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable

# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "figures")
os.makedirs(OUT_DIR, exist_ok=True)

plt.style.use('seaborn-v0_8-whitegrid')

# ---------------------------------------------------------------------------
# Shared size-tier colour palette
# ---------------------------------------------------------------------------
TIER_COLORS = {
    "pico":  "#9b59b6",   # purple
    "nano":  "#3498db",   # blue
    "micro": "#27ae60",   # green
    "milli": "#e67e22",   # orange
    "centi": "#e74c3c",   # red
}

# ---------------------------------------------------------------------------
# Figure 1 – Zone × content_category heatmap
# ---------------------------------------------------------------------------

zones = ["defense", "field", "near_spawn", "spawn", "wool_room"]
categories = ["combat", "defense", "supply", "weapon", "wool"]

# pct_within_zone data (from cross-tab provided)
raw = {
    ("defense",   "defense"):   98.8,
    ("defense",   "weapon"):     1.2,
    ("field",     "defense"):   57.1,
    ("field",     "weapon"):    15.6,
    ("field",     "combat"):    12.2,
    ("field",     "supply"):    10.4,
    ("field",     "wool"):       4.8,
    ("near_spawn","defense"):   64.6,
    ("near_spawn","wool"):      15.4,
    ("near_spawn","combat"):    13.0,
    ("near_spawn","supply"):     5.7,
    ("near_spawn","weapon"):     1.2,
    ("spawn",     "defense"):   77.9,
    ("spawn",     "weapon"):    18.7,
    ("spawn",     "combat"):     2.2,
    ("spawn",     "supply"):     1.1,
    ("wool_room", "combat"):    42.9,
    ("wool_room", "wool"):      21.7,
    ("wool_room", "supply"):    15.8,
    ("wool_room", "weapon"):    13.2,
    ("wool_room", "defense"):    6.3,
}

matrix = np.zeros((len(zones), len(categories)))
for (z, c), v in raw.items():
    matrix[zones.index(z), categories.index(c)] = v

fig1, ax1 = plt.subplots(figsize=(10, 7))
im = ax1.imshow(
    matrix,
    cmap="Blues",
    aspect="auto",
    vmin=0, vmax=100,
    origin="upper",
)

# Grey out zero cells and annotate
for r in range(len(zones)):
    for c in range(len(categories)):
        val = matrix[r, c]
        if val == 0.0:
            ax1.add_patch(
                mpatches.Rectangle(
                    (c - 0.5, r - 0.5), 1, 1,
                    linewidth=0, facecolor="#cccccc", zorder=2
                )
            )
            ax1.text(c, r, "—", ha="center", va="center",
                     fontsize=10, color="#888888", zorder=3)
        else:
            text_color = "white" if val > 55 else "black"
            ax1.text(c, r, f"{val:.1f}%", ha="center", va="center",
                     fontsize=10, fontweight="bold", color=text_color, zorder=3)

ax1.set_xticks(range(len(categories)))
ax1.set_xticklabels(categories, fontsize=11)
ax1.set_yticks(range(len(zones)))
ax1.set_yticklabels(zones, fontsize=11)
ax1.set_title("Chest Content Category by Spatial Zone (% within zone)",
              fontsize=13, fontweight="bold", pad=12)
ax1.set_xlabel("Content Category", fontsize=11)
ax1.set_ylabel("Zone", fontsize=11)

cbar = fig1.colorbar(im, ax=ax1, fraction=0.046, pad=0.04)
cbar.set_label("% of chests in zone", fontsize=10)

fig1.tight_layout()
fig1.savefig(os.path.join(OUT_DIR, "chest_zone_heatmap.png"), dpi=150)
plt.close(fig1)
print("Saved chest_zone_heatmap.png")

# ---------------------------------------------------------------------------
# Figure 2 – Defense chests vs. map size
# ---------------------------------------------------------------------------

# Full query result (map_slug, size_tier, total_blocks, max_players_per_team,
#                   wools_per_team, defense_chests, defense_item_total,
#                   redstone_blocks, fences, pistons, cobwebs, glass,
#                   water_buckets, tools)
defense_data = [
    ("nyxis","micro",21881,20,1,326,40242,0,1536,0,128,0,4,14),
    ("nextgen","milli",9000,24,2,288,497664,0,0,0,0,248832,0,0),
    ("blocks_ctw","centi",33099,32,2,288,479232,18432,0,18432,0,110592,0,0),
    ("madness_on_rails","centi",21432,36,2,168,282240,27648,28672,0,0,55296,0,16),
    ("fall_of_babylon","centi",46904,34,2,164,83388,0,3072,0,256,0,232,44),
    ("race_for_victory_3","centi",17952,35,3,160,276480,0,0,36864,0,55296,0,0),
    ("split_strata","milli",12062,24,2,116,172596,768,1280,0,0,0,16,24),
    ("exitium","milli",12472,24,2,112,166824,0,0,0,0,0,0,0),
    ("ad_infinitum","milli",33479,30,1,108,6364,386,512,0,46,0,24,6),
    ("summertime_at_browns_farms","nano",22356,8,7,104,156096,0,0,0,0,0,0,0),
    ("gridlock_2","milli",7774,28,2,96,165888,0,0,27648,0,0,0,0),
    ("apocalypse_ctw","centi",28976,32,2,82,118476,6912,6912,0,0,0,324,0),
    ("ruedigers_octawool","pico",28556,5,7,72,124416,0,23040,0,0,0,0,0),
    ("corrupted_paradise_ctw","micro",23462,20,6,68,67436,3072,2048,0,128,0,452,12),
    ("war_of_the_acres","micro",25224,16,2,66,2652,0,216,0,0,0,0,9),
    ("lupa","centi",19707,32,2,66,77414,2304,0,0,0,512,0,20),
    ("mexico","micro",16199,16,2,65,107569,15360,12288,12288,0,15360,48,0),
    ("super_happy_fun_world","milli",15773,24,2,64,6300,512,512,0,56,0,0,24),
    ("circus_ctw","centi",12104,32,2,64,95210,0,0,0,0,0,0,0),
    ("golden_drought","centi",12386,35,2,60,83164,0,9216,13824,0,0,0,0),
    ("celestial_islands","micro",13834,16,2,60,26774,632,1152,0,32,0,0,18),
    ("jungle_beat","centi",15544,32,2,56,85608,0,0,23040,360,6144,0,0),
    ("nextrace","nano",5956,12,1,56,86272,0,0,0,0,41984,0,0),
    ("welcome_to_wool_square","centi",24986,40,3,50,42122,0,0,0,0,0,0,0),
    ("bloom","micro",17920,16,2,49,82947,0,0,0,0,0,0,0),
    ("renegade","milli",20508,24,2,48,51840,0,0,0,0,0,0,0),
    ("peloponnesia","milli",19629,30,2,48,24520,1536,3072,0,432,0,48,6),
    ("kingdom","centi",38937,40,2,44,69204,4608,4608,0,0,0,24,36),
    ("cyril","micro",6318,18,1,40,53604,0,0,1536,0,0,0,36),
    ("ad_astra","milli",30884,28,2,40,64056,1536,3072,0,0,0,0,48),
    ("comb_conquest","milli",7493,24,2,36,59656,256,512,4096,0,0,0,8),
    ("vesuvius","milli",9601,25,2,33,55297,0,6144,0,0,0,0,1),
    ("harbor_ctw","centi",46292,45,2,32,14460,0,1024,0,128,0,20,0),
    ("shroom_galaxy","milli",24795,28,2,32,33466,4096,1536,2048,0,2048,32,64),
    ("canyon_ii","micro",12548,20,2,32,51880,0,1536,0,48,0,0,24),
    ("keipha_ctw","centi",17987,35,2,32,36752,3072,4096,3072,0,256,148,0),
    ("oaken_meadow","centi",18862,35,2,32,40944,0,1344,0,672,0,16,0),
    ("wholething","milli",17136,24,2,32,49920,0,1536,0,0,15360,0,0),
    ("mushroom_gorge","centi",14359,35,2,32,53760,0,0,18432,0,7168,0,0),
    ("two_tier","centi",8118,32,2,32,55148,0,0,13676,0,0,0,0),
    ("araxa","milli",17818,24,2,32,36912,4608,4608,4608,0,4608,0,36),
    ("green_gem_ctw","centi",17712,32,3,30,41553,4608,4608,6912,0,0,0,0),
    ("golden_drought_iii","micro",8802,20,2,30,41582,0,2304,2304,0,0,0,0),
    ("annealing_iv","micro",14284,18,3,28,27716,2304,1024,0,1024,0,32,32),
    ("golden_drought_iv","centi",16796,35,3,28,27972,0,0,0,0,0,0,0),
    ("outback_outback_edition","centi",17994,32,2,28,22072,2048,0,0,0,0,32,64),
    ("infernal_shadow","nano",4941,12,1,28,34592,0,0,0,0,0,0,0),
    ("factorio_mainbus","centi",20660,32,1,26,40482,2304,2304,2304,0,6912,0,16),
    ("feel_good_inc","milli",15485,24,2,25,38947,256,512,1024,0,0,0,8),
    ("thornwood","centi",15027,32,2,25,21337,256,448,0,56,0,0,24),
    ("simplicity_ctw","micro",10814,15,1,24,39696,1024,1024,0,256,0,16,0),
    ("mahatma","micro",14333,14,3,24,10092,0,2048,0,0,4096,0,76),
    ("philosophers_stone","micro",16657,16,6,24,30152,7168,6144,0,0,0,32,32),
    ("fairy_tales_2_a_tale_or_two","centi",12624,32,3,24,41472,0,0,20736,0,0,0,0),
    ("fairy_tales_metamorphose","micro",14256,20,2,24,41472,12288,12288,0,0,0,0,0),
    ("appalachia","milli",9353,24,2,24,32548,0,1024,0,0,0,0,28),
    ("rind_rushers_ii","nano",14593,8,3,24,32776,512,512,0,0,0,0,8),
    ("standstill","centi",13540,32,3,24,21744,2304,0,0,0,0,48,96),
    ("mini_drought","pico",3189,5,2,24,41472,0,0,0,0,0,0,0),
    ("race_for_victory","nano",9299,12,2,24,15080,0,0,0,0,0,0,0),
    ("wits_end","milli",8400,24,2,24,27864,0,0,0,0,0,0,0),
    ("icecream_sandwiched_ii","milli",20389,24,2,22,33308,0,1024,0,0,15872,0,20),
    ("gobi","centi",15873,32,2,22,11120,0,256,0,0,0,0,12),
    ("oasis_ctw","milli",13077,24,1,20,11184,1024,1024,0,0,864,16,24),
    ("tohjo_falls_ii","micro",11678,20,2,20,18224,256,512,1536,0,0,0,8),
    ("station_x","milli",19002,28,2,20,29456,0,1024,0,0,0,0,16),
    ("outback","centi",16808,32,2,20,6840,0,512,0,0,512,0,8),
    ("autumn_breeze","micro",19571,20,2,20,26200,768,2048,512,256,2048,32,48),
    ("duality","micro",10069,20,2,20,12556,512,1024,0,0,0,0,12),
    ("pineium_ctw","centi",13775,32,2,20,15792,1024,1024,0,0,5184,16,24),
    ("desert_country","micro",9904,20,2,18,11071,0,2304,0,0,0,6,0),
    ("deepwind_jungle","micro",5742,16,2,18,24428,0,0,9216,0,4608,0,0),
    ("ringpull","nano",5140,8,1,18,16002,128,256,0,0,0,0,2),
    ("townside","milli",13947,30,1,16,7858,288,768,0,0,0,6,12),
    ("garf","micro",13064,18,2,16,10012,0,256,0,0,0,12,16),
    ("emergency_meeting","nano",6041,6,3,16,1604,0,0,0,0,0,0,8),
    ("thunder","nano",11205,12,3,16,5188,0,0,0,0,0,0,0),
    ("underpass","micro",5880,16,1,16,15504,0,0,0,144,0,0,0),
    ("levels","micro",5157,16,2,16,20736,0,0,0,0,0,0,0),
    ("empire","micro",6490,16,2,16,16896,0,0,0,0,0,0,0),
    ("ring_race","centi",15415,32,2,16,27648,0,0,0,0,3456,0,0),
    ("citadel","micro",24856,16,0,16,2497,0,0,0,64,0,0,2),
    ("tuscany","milli",12239,30,2,16,11540,0,256,0,0,128,0,8),
    ("hotel_overcast","centi",30976,32,2,16,26496,1152,3072,4608,0,0,0,0),
    ("when_men_cried","micro",9657,20,2,16,7894,0,1024,256,0,0,0,16),
    ("frost","centi",40353,35,2,16,16432,0,2560,0,0,0,32,16),
    ("goo_lagoon","centi",14203,35,2,16,404,0,0,0,20,0,0,0),
    ("persisto","nano",5223,12,2,16,27648,0,0,0,0,0,0,0),
    ("wintertime","nano",9479,12,1,16,2604,0,512,0,0,0,8,24),
    ("vegas","centi",27917,32,2,14,4946,512,512,0,0,0,16,0),
    ("gongua_ctw","centi",23131,32,1,14,23118,0,256,0,0,0,8,6),
    ("hello_world","centi",13954,32,2,14,16836,3456,0,0,0,0,24,24),
    ("pixelmix","centi",14852,35,2,14,8210,0,0,1152,0,0,0,22),
    ("tusho_ctw","micro",10508,20,2,14,18454,0,512,0,0,0,8,8),
    ("huanxiang","nano",5128,12,2,14,17186,0,512,0,0,0,0,14),
    ("banana_split","micro",7469,16,2,14,378,0,0,0,0,0,0,0),
    ("columbia_ctw","centi",19267,32,2,13,14473,1024,0,6912,256,0,0,8),
    ("nobles_district","milli",17544,24,2,12,10840,1024,1024,0,0,0,0,48),
    ("paddos","micro",7072,16,2,12,13200,0,256,0,0,0,8,8),
    ("clearcut","micro",15669,20,2,12,8776,0,896,0,28,2432,0,24),
    ("thunderbolt","nano",15473,10,5,12,7320,0,1152,0,0,0,24,0),
    ("belvedere","milli",12169,24,2,12,3460,0,1152,0,0,0,0,0),
    ("nether_war_ctw","micro",16361,16,3,12,10760,0,2048,0,0,128,0,0),
    ("firum_ctw","milli",22249,24,1,12,17100,1024,2048,0,0,0,16,24),
    ("downforce","nano",2729,10,1,12,1536,0,0,0,0,0,0,0),
    ("colorado","micro",10846,18,2,12,9072,1536,512,512,0,256,16,0),
    ("snow_level","nano",6460,8,3,12,1092,0,256,0,0,0,0,8),
    ("xion","centi",11237,32,2,12,12,0,0,0,0,0,0,0),
    ("sheep_ctw","micro",6856,20,2,12,13782,3456,1536,0,288,0,54,0),
    ("lotus","micro",10385,20,2,12,10996,0,1024,0,30,2304,0,24),
    ("pigland","micro",7586,16,2,12,19980,3840,3072,0,0,0,0,12),
    ("tulip_mania_ii","micro",10240,16,2,12,18180,256,512,0,0,0,0,4),
    ("mame_i_shrunk_the_pvpers","centi",25012,32,2,12,4626,256,512,0,0,0,0,0),
    ("istana_ctw","centi",16253,32,2,12,17556,512,512,0,0,0,12,8),
    ("fourchette","milli",16228,28,3,12,20544,0,3328,6912,0,0,0,0),
    ("placid_spring","nano",4348,13,2,12,20736,0,5120,0,0,0,0,0),
    ("steel_valley","milli",20727,26,2,12,5672,0,1280,16,0,0,0,16),
    ("sakura_garden","milli",19042,30,2,12,10756,256,1536,0,0,0,0,24),
    ("la_bataille_de_lepee","pico",2219,5,1,12,5052,0,508,0,0,0,0,0),
    ("sunbliss","micro",11946,20,1,12,6702,768,512,0,0,1456,4,12),
    ("xunkohtli","centi",13658,32,2,12,8548,512,1024,512,0,0,16,16),
    ("yermo","nano",4073,12,1,10,14476,0,256,0,0,4736,0,8),
    ("tulip_mania","nano",4548,8,1,10,16002,128,256,0,0,0,0,2),
    ("constellation","nano",4917,12,1,10,6816,0,1344,0,0,0,12,12),
    ("smashcap","nano",5942,12,1,10,8458,128,256,0,0,0,0,10),
    ("green_gem_ctw_mini","micro",4976,16,3,10,4828,192,0,0,0,0,0,12),
    ("pirates_i","pico",1456,5,1,9,937,0,120,0,0,0,0,0),
    ("boulders","nano",4420,12,2,8,4424,0,1536,0,256,0,24,32),
    ("jupiter","micro",6935,14,2,8,3904,0,0,0,0,0,40,24),
    ("lupain","micro",7252,16,1,8,6672,0,512,0,0,1536,4,12),
    ("race_for_victory_2","milli",6666,24,2,8,13824,0,0,9216,0,0,0,0),
    ("villa_ii","milli",13082,24,1,8,9420,256,512,0,0,3456,0,12),
    ("twisted","centi",14002,35,2,8,13824,0,0,0,0,0,0,0),
    ("sakura_garden_ii","nano",6606,12,1,8,5920,2048,1024,0,0,0,0,12),
    ("gloomwald","nano",7016,12,2,8,4576,0,256,0,0,0,8,24),
    ("clayclay","nano",3872,13,1,8,2700,256,256,0,0,0,8,4),
    ("kanto","milli",12552,24,2,8,5448,0,512,0,0,256,0,24),
    ("epsilon","centi",18447,32,2,8,5272,1408,0,0,0,768,0,24),
    ("rocky_top","milli",17460,28,2,8,5840,0,1024,0,0,0,8,8),
    ("agrostid","milli",10602,24,2,8,4448,576,512,0,512,0,16,16),
    ("hallows","micro",12887,18,2,8,13824,0,2048,0,0,0,0,0),
    ("winter_wakening","centi",27802,32,2,8,12552,0,1280,0,0,0,0,8),
    ("witchs_potions","milli",16047,24,2,8,11304,3072,1024,0,0,0,16,24),
    ("acapulco","milli",14952,24,2,8,12312,4096,0,0,0,0,0,24),
    ("aequabilis","centi",22281,32,2,8,5664,0,1024,0,0,0,0,0),
    ("sanctum_wasser","milli",17675,24,2,8,7184,1024,1024,0,0,768,8,8),
    ("tumbleweed","centi",21679,35,2,8,8376,0,384,0,0,0,32,16),
    ("brittlebush_ii","micro",6676,20,2,8,6416,256,0,0,0,0,0,16),
    ("xinx","micro",17667,20,2,8,10800,2560,0,0,0,0,0,48),
    ("winterbane","nano",5014,10,1,8,1904,0,128,0,0,320,0,8),
    ("enchanted","nano",7763,12,3,8,2832,0,256,0,128,0,8,4),
    ("oceano_ctw","milli",8636,24,1,8,12048,0,2048,0,256,0,16,0),
    ("level_up","milli",19955,24,1,8,5052,0,512,0,0,0,0,36),
    ("agrorythe","centi",23004,36,2,8,6968,1024,0,0,0,0,0,8),
    ("edo","micro",7426,16,2,7,8089,0,512,0,0,0,0,12),
    ("rotten","nano",5810,12,1,6,2004,0,0,0,0,0,4,12),
    ("santorini","nano",2286,10,1,6,1550,128,256,0,0,0,0,4),
    ("aether","micro",5278,16,1,6,6292,256,256,0,0,0,4,16),
    ("arabia","micro",7206,18,2,6,5352,0,0,0,0,0,0,8),
    ("sweetopia","micro",7820,18,1,6,6286,256,128,0,0,128,0,0),
    ("coconut_mald","micro",7192,16,1,6,4198,0,256,0,0,448,0,6),
    ("discovery","nano",4572,10,1,6,2706,128,256,0,0,0,10,8),
    ("golden_drought_v","nano",5738,8,1,5,2699,0,384,0,0,0,0,0),
    ("apostle","milli",26632,24,2,4,1804,0,256,0,0,0,0,4),
    ("chestnut","nano",2437,8,1,4,1792,0,0,0,0,0,0,0),
    ("jurassic","centi",16972,32,2,4,4896,0,1280,0,0,0,0,24),
    ("brittlebush","micro",9216,16,2,4,3208,128,0,0,0,0,0,8),
    ("outback_mini","micro",4316,16,2,4,3208,128,0,0,0,0,0,8),
    ("tangier","nano",4862,12,1,4,1734,256,256,0,0,0,0,4),
    ("tranquility","nano",6491,10,2,4,2196,0,0,0,24,0,0,16),
    ("hillside_daydream","micro",13676,16,3,4,4620,512,1024,0,0,0,0,12),
    ("veld","nano",5298,12,2,4,6912,0,0,0,0,0,0,0),
    ("oumuamua","pico",23496,5,3,4,3208,128,0,0,0,0,0,8),
    ("timbered","nano",6392,8,3,4,3076,256,512,0,0,0,0,4),
    ("raceway","micro",11706,14,2,4,5640,512,1024,0,0,0,0,8),
    ("java_ii","milli",11667,24,2,4,4896,0,1280,0,0,0,0,24),
    ("kerskyn","micro",8486,14,2,4,3340,256,512,0,0,0,0,12),
    ("oaken_meadow_mini","micro",5304,14,2,4,1584,0,160,0,272,0,0,0),
    ("long_distance","nano",6732,8,3,4,3208,128,0,0,0,0,0,8),
    ("onier","nano",6159,8,1,4,1722,256,256,0,0,0,0,4),
    ("dromedary","nano",1418,7,1,4,1488,192,256,0,0,0,0,6),
    ("curly_pride","pico",2114,5,1,4,6408,1024,1536,0,0,0,8,0),
    ("vertex","nano",4444,7,1,4,1728,0,256,0,0,0,0,0),
    ("bamboo_valley_v","milli",12252,24,2,4,6408,0,1024,0,0,256,0,0),
    ("amphitheater","nano",2044,6,1,4,1542,128,256,0,0,0,0,4),
    ("desolate_gully_ctw","nano",2638,6,1,4,1486,0,384,0,0,0,0,8),
    ("dead_noon","micro",5212,16,1,4,4392,512,512,0,0,0,16,24),
    ("hobbit_ctw","nano",3959,8,1,4,1566,0,256,0,0,0,4,12),
    ("rice","nano",2979,8,1,2,1604,64,256,0,0,0,0,4),
    ("townside_mini","nano",3620,12,1,2,1604,64,0,0,0,0,0,4),
    ("villa_i","micro",5171,16,1,2,2312,256,512,0,0,0,0,8),
    ("dynamo","nano",2933,8,1,2,46,0,0,0,0,0,0,0),
    ("hauoli_mau_lanui","nano",5306,10,1,2,2434,0,0,0,0,0,0,2),
    ("krager","nano",3370,9,1,2,1670,128,256,0,0,0,0,6),
    ("honeycombed","pico",1706,5,1,2,1158,128,128,0,0,0,0,6),
    ("exogrid","nano",1549,8,1,2,1794,128,256,0,0,0,0,2),
    ("flush_vibes_ii","pico",2658,5,1,2,576,0,0,0,32,0,0,0),
    ("expedition","nano",2300,7,1,2,1860,192,256,0,0,0,0,4),
    ("gethsemane","nano",4320,8,1,2,1670,128,256,0,0,0,0,6),
    ("deciduous_nights","nano",3817,8,1,2,2178,128,256,0,0,0,0,2),
    ("after_hours","micro",8123,14,1,2,1170,256,256,0,0,0,4,12),
    ("research_base","nano",2668,8,1,2,1604,192,256,0,0,0,0,4),
]

cols = ["map_slug","size_tier","total_blocks","max_players_per_team","wools_per_team",
        "defense_chests","defense_item_total","redstone_blocks","fences","pistons",
        "cobwebs","glass","water_buckets","tools"]

import pandas as pd
df = pd.DataFrame(defense_data, columns=cols)

fig2, ax2 = plt.subplots(figsize=(10, 7))

for tier, group in df.groupby("size_tier"):
    ax2.scatter(
        group["total_blocks"], group["defense_chests"],
        c=TIER_COLORS.get(tier, "grey"),
        label=tier, alpha=0.75, s=55, zorder=3
    )

# Trend line on log values
log_x = np.log10(df["total_blocks"].clip(lower=1))
log_y = np.log10(df["defense_chests"].clip(lower=1))
m, b = np.polyfit(log_x, log_y, 1)
x_range = np.linspace(df["total_blocks"].min(), df["total_blocks"].max(), 200)
y_trend = 10 ** (m * np.log10(x_range) + b)
ax2.plot(x_range, y_trend, color="grey", linewidth=1.5, linestyle="--",
         alpha=0.6, zorder=2, label="log-log trend")

# Label top 8 by defense_chests
top8 = df.nlargest(8, "defense_chests")
for _, row in top8.iterrows():
    ax2.annotate(
        row["map_slug"],
        xy=(row["total_blocks"], row["defense_chests"]),
        xytext=(6, 3), textcoords="offset points",
        fontsize=7.5, alpha=0.9
    )

ax2.set_xscale("log")
ax2.set_yscale("log")
ax2.set_xlabel("Total Blocks (log scale)", fontsize=11)
ax2.set_ylabel("Defense Chests (log scale)", fontsize=11)
ax2.set_title("Defense Chests vs. Map Size", fontsize=13, fontweight="bold")
ax2.legend(title="Size Tier", fontsize=9, title_fontsize=9)
fig2.tight_layout()
fig2.savefig(os.path.join(OUT_DIR, "defense_chests_vs_size.png"), dpi=150)
plt.close(fig2)
print("Saved defense_chests_vs_size.png")

# ---------------------------------------------------------------------------
# Figure 3 – Defense item density per wool vs. team size
# ---------------------------------------------------------------------------

df3 = df[df["wools_per_team"] > 0].copy()
df3["items_per_wool"] = df3["defense_item_total"] / df3["wools_per_team"]

fig3, ax3 = plt.subplots(figsize=(10, 7))

for tier, group in df3.groupby("size_tier"):
    ax3.scatter(
        group["max_players_per_team"], group["items_per_wool"],
        c=TIER_COLORS.get(tier, "grey"),
        label=tier, alpha=0.75, s=55, zorder=3
    )

# Label top 8 by items_per_wool
top8_density = df3.nlargest(8, "items_per_wool")
for _, row in top8_density.iterrows():
    ax3.annotate(
        row["map_slug"],
        xy=(row["max_players_per_team"], row["items_per_wool"]),
        xytext=(6, 3), textcoords="offset points",
        fontsize=7.5, alpha=0.9
    )

ax3.set_yscale("log")
ax3.set_xlabel("Max Players per Team", fontsize=11)
ax3.set_ylabel("Defense Items per Wool (log scale)", fontsize=11)
ax3.set_title("Defense Item Density per Wool vs. Team Size",
              fontsize=13, fontweight="bold")
ax3.legend(title="Size Tier", fontsize=9, title_fontsize=9)
fig3.tight_layout()
fig3.savefig(os.path.join(OUT_DIR, "defense_density_per_wool.png"), dpi=150)
plt.close(fig3)
print("Saved defense_density_per_wool.png")

# ---------------------------------------------------------------------------
# Figure 4 – Material composition of top 15 maps by defense_item_total
# ---------------------------------------------------------------------------

top15 = df.nlargest(15, "defense_item_total").copy()
top15 = top15.sort_values("defense_item_total", ascending=True)  # bottom→top for barh

material_cols = ["glass", "fences", "redstone_blocks", "pistons",
                 "cobwebs", "water_buckets", "tools"]
material_labels = ["Glass", "Fences", "Redstone Blocks", "Pistons",
                   "Cobwebs", "Water Buckets", "Tools"]

tracked_totals = top15[material_cols].sum(axis=1)
top15["other"] = (top15["defense_item_total"] - tracked_totals).clip(lower=0)

all_cols = material_cols + ["other"]
all_labels = material_labels + ["Other"]

palette = plt.cm.Set3.colors  # 12 distinct colours

fig4, ax4 = plt.subplots(figsize=(12, 8))

lefts = np.zeros(len(top15))
for i, (col, label) in enumerate(zip(all_cols, all_labels)):
    vals = top15[col].values
    bars = ax4.barh(
        top15["map_slug"],
        vals,
        left=lefts,
        color=palette[i % len(palette)],
        label=label,
        edgecolor="white",
        linewidth=0.5,
    )
    lefts = lefts + vals

ax4.set_xlabel("Total Defense Items", fontsize=11)
ax4.set_title("Defense Material Composition — Top 15 Maps",
              fontsize=13, fontweight="bold")
ax4.legend(loc="lower right", fontsize=9, title="Material", title_fontsize=9)
ax4.tick_params(axis="y", labelsize=9)

# Annotate total at end of each bar
for idx, (_, row) in enumerate(top15.iterrows()):
    total = row["defense_item_total"]
    ax4.text(total + total * 0.005, idx, f"{total:,.0f}",
             va="center", fontsize=8, color="black")

ax4.set_xlim(right=top15["defense_item_total"].max() * 1.12)
fig4.tight_layout()
fig4.savefig(os.path.join(OUT_DIR, "defense_material_composition.png"), dpi=150)
plt.close(fig4)
print("Saved defense_material_composition.png")

# ---------------------------------------------------------------------------
# Figure 5 – Top items per content category (chest-slot occurrences)
# ---------------------------------------------------------------------------
# Data: top 10 items per category sorted by chest_slots (number of slots
# across all maps, i.e. how universally the item appears in that category).
# Item names translated from Minecraft 1.8.9 IDs.  Legacy numeric IDs (e.g.
# 322 = golden_apple, 262 = arrow) are merged into their canonical equivalents
# before ranking so that older maps and newer maps are counted together.

CATEGORY_ITEMS = {
    'combat': [
        ('Golden Apple',        21100),
        ('Diamond Chestplate',  15478),
        ('Bow',                 11205),
        ('Diamond Helmet',       5796),
        ('Diamond Leggings',     4691),
        ('Potion',               3936),
        ('Diamond Boots',        2136),
        ('Iron Chestplate',      1614),
        ('Arrow',                1162),
        ('Planks',                961),
    ],
    'defense': [
        ('Planks',              26356),
        ('Wood Log',            13102),
        ('Glass',               10326),
        ('Crafting Table',       9076),
        ('Redstone Block',       3570),
        ('Stained Clay',         3445),
        ('Redstone Dust',        3170),
        ('Water Bucket',         3016),
        ('Fence',                2890),
        ('Piston',               2718),
    ],
    'supply': [
        ('Potion',               9612),
        ('Golden Apple',         6885),
        ('Planks',               3221),
        ('Stained Glass',         464),
        ('Milk Bucket',           420),
        ('Wood Log (acacia)',      312),
        ('Stained Clay',          300),
        ('Wheat',                 288),
        ('Stone',                 288),
        ('Minecart',              288),
    ],
    'weapon': [
        ('Arrow',                9575),
        ('Bow',                  9464),
        ('Golden Apple',         2910),
        ('Wood Log',             1996),
        ('Iron Sword',           1856),
        ('Iron Pickaxe',         1712),
        ('Glass',                1710),
        ('Potion',               1668),
        ('Planks',               1071),
        ('Ladder',                884),
    ],
}

CATEGORY_COLORS = {
    'combat':  '#e74c3c',
    'defense': '#2980b9',
    'supply':  '#27ae60',
    'weapon':  '#e67e22',
}

fig5, axes = plt.subplots(2, 2, figsize=(14, 10))
axes_flat = axes.flatten()

for ax, (cat, items) in zip(axes_flat, CATEGORY_ITEMS.items()):
    labels = [name for name, _ in reversed(items)]
    values = [val for _, val in reversed(items)]
    color = CATEGORY_COLORS[cat]
    max_val = max(values)
    bars = ax.barh(labels, values, color=color, alpha=0.82, edgecolor='white', linewidth=0.5)
    ax.set_title(f'{cat.capitalize()} chests — top 10 items',
                 fontsize=11, fontweight='bold', color=color)
    ax.set_xlabel('Chest-slot occurrences (all maps)', fontsize=9)
    ax.tick_params(axis='y', labelsize=9)
    ax.tick_params(axis='x', labelsize=9)
    for bar, val in zip(bars, values):
        ax.text(val + max_val * 0.015, bar.get_y() + bar.get_height() / 2,
                f'{val:,}', va='center', fontsize=8)
    ax.set_xlim(right=max_val * 1.18)

fig5.suptitle(
    'Most Common Items by Chest Category\n'
    '(chest-slot occurrences across all maps; sorted by prevalence)',
    fontsize=13, fontweight='bold',
)
fig5.tight_layout()
fig5.savefig(os.path.join(OUT_DIR, 'chest_category_contents.png'), dpi=150)
plt.close(fig5)
print('Saved chest_category_contents.png')

print("All figures saved to", OUT_DIR)
