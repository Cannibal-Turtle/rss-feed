# tools/audit_dead_host_utils.py
import ast, re, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOST = ROOT / "host_utils.py"  # adjust if you've already moved it

def read(p): return pathlib.Path(p).read_text(encoding="utf-8", errors="replace")

src = read(HOST)
tree = ast.parse(src)

# --- collect top-level function defs
func_nodes = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

# --- grab the two dispatch dicts as text
def extract_dict_text(name: str):
    s = src.find(f"{name} =")
    if s < 0: return ""
    start = src.find("{", s)
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{": depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i+1]
    return ""

drag_text = extract_dict_text("DRAGONHOLIC_UTILS")
mist_text = extract_dict_text("MISTMINT_UTILS")

# --- exported function names (values inside the dicts)
def exported_names(dtext: str):
    return [val for _, val in re.findall(r'"([^"]+)"\s*:\s*([A-Za-z_][A-Za-z0-9_]*)', dtext)]

exported = set(exported_names(drag_text) + exported_names(mist_text))

# --- build a simple call graph inside host_utils.py
def get_called_names(fn: ast.FunctionDef):
    called = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                called.add(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                called.add(n.func.attr)
    return called

graph = {name: get_called_names(node) for name, node in func_nodes.items()}

# --- compute reachable from exported
reachable = set()
stack = list(exported)
while stack:
    f = stack.pop()
    if f in reachable: continue
    reachable.add(f)
    for callee in graph.get(f, ()):
        if callee not in reachable:
            stack.append(callee)

# --- scan the rest of the repo for key usage like utils['x'] or utils.get("x")
used_keys = set()
for path in ROOT.glob("*.py"):
    if path.name == HOST.name: continue
    text = read(path)
    used_keys.update(re.findall(r'utils\[\s*["\']([A-Za-z0-9_]+)["\']\s*\]', text))
    used_keys.update(re.findall(r'utils\.get\(\s*["\']([A-Za-z0-9_]+)["\']', text))

# --- report
all_defs = set(func_nodes)
dead_candidates = sorted(all_defs - reachable - exported - {"get_host_utils"})

print("Exported function objects:", len(exported))
print("Functions reachable from exported:", len(reachable))
print("Total function defs in host_utils:", len(all_defs))
print("\nKeys used by other scripts:", sorted(used_keys))

print("\nLikely dead (not exported, not reachable, not referenced):")
for name in dead_candidates:
    print(" -", name)
