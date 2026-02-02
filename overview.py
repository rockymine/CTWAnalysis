import ast, os, json

IGNORE = (".venv", "__pycache__", ".git", "site-packages")

api = []

for root, _, files in os.walk("."):
    if any(x in root for x in IGNORE):
        continue
    for f in files:
        if not f.endswith(".py"):
            continue
        path = os.path.join(root, f)

        try:
            tree = ast.parse(open(path, "r", encoding="utf8").read())
        except Exception:
            continue

        entry = {
            "file": path.replace("\\", "/"),
            "functions": [],
            "classes": []
        }

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                entry["functions"].append({
                    "name": node.name,
                    "args": [a.arg for a in node.args.args],
                    "returns": ast.unparse(node.returns) if node.returns else None
                })

            elif isinstance(node, ast.ClassDef):
                cls = {
                    "name": node.name,
                    "methods": []
                }
                for m in node.body:
                    if isinstance(m, ast.FunctionDef):
                        cls["methods"].append({
                            "name": m.name,
                            "args": [a.arg for a in m.args.args],
                            "returns": ast.unparse(m.returns) if m.returns else None
                        })
                entry["classes"].append(cls)

        if entry["functions"] or entry["classes"]:
            api.append(entry)

with open("docs/api_index.json", "w", encoding="utf8") as f:
    json.dump(api, f, indent=2)

print("Wrote docs/api_index.json")