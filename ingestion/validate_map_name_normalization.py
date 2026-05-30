import re
import unicodedata

from map_slugs import MAP_SLUGS


def normalize_map_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = name.lower()
    name = name.replace(" ", "_")
    name = re.sub(r"[^a-z0-9_]", "", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


mismatches = []
for slug, display_name in MAP_SLUGS.items():
    normalized = normalize_map_name(display_name)
    if normalized != slug:
        mismatches.append((slug, display_name, normalized))

if mismatches:
    print(f"{len(mismatches)} mismatch(es) found:\n")
    for slug, display_name, got in mismatches:
        print(f"  DB slug:    {slug}")
        print(f"  Display:    {display_name}")
        print(f"  Normalized: {got}")
        print()
else:
    print(f"All {len(MAP_SLUGS)} map names normalize correctly.")
