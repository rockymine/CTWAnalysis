import ast
import json
import os
from pathlib import Path

IGNORE_DIRS = {
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".claude",
    "site-packages",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "output",
    "map_folders",
}

OUTPUT_FILE = Path("docs/api_index.json")

api = []

for root, dirs, files in os.walk("."):
    # Prevent os.walk from descending into ignored directories.
    dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

    for filename in files:
        if not filename.endswith(".py"):
            continue

        path = Path(root) / filename

        try:
            source = path.read_text(encoding="utf8")
            tree = ast.parse(source)
        except Exception:
            continue

        entry = {
            "file": path.as_posix(),
            "functions": [],
            "classes": [],
        }

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                entry["functions"].append({
                    "name": node.name,
                    "args": [a.arg for a in node.args.args],
                    "returns": ast.unparse(node.returns) if node.returns else None,
                })

            elif isinstance(node, ast.ClassDef):
                cls = {
                    "name": node.name,
                    "methods": [],
                }

                for method in node.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        cls["methods"].append({
                            "name": method.name,
                            "args": [a.arg for a in method.args.args],
                            "returns": ast.unparse(method.returns) if method.returns else None,
                        })

                entry["classes"].append(cls)

        if entry["functions"] or entry["classes"]:
            api.append(entry)

OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

with OUTPUT_FILE.open("w", encoding="utf8") as f:
    json.dump(api, f, indent=2)

print(f"Wrote {OUTPUT_FILE}")