"""
Generates a PNG class-hierarchy diagram of the ontology by reading
om_n_om/aiact_ontology.ttl and walking rdfs:subClassOf edges. Colours
nodes by source namespace (our classes, AIRO, DPV, DPV-AIAct) and shells
out to graphviz `dot` to render the PNG.

Output: om_n_om/aiact_ontology.png
"""

import subprocess
import sys
from rdflib import Graph, RDFS, OWL, BNode

TTL_FILE = "om_n_om/aiact_ontology.ttl"
PNG_FILE = "om_n_om/aiact_ontology.png"

# Check graphviz is available
try:
    subprocess.run(["dot", "-V"], capture_output=True, check=True)
except (FileNotFoundError, subprocess.CalledProcessError):
    print("Error: graphviz not found.")
    print("Install with: brew install graphviz  (Mac) or sudo apt install graphviz  (Linux)")
    sys.exit(1)

# Load ontology
g = Graph()
g.parse(TTL_FILE, format="turtle")

EX_NS    = "https://example.org/eu-ai-act-compliance#"
AIRO_NS  = "https://w3id.org/airo#"
AIACT_NS = "https://w3id.org/dpv/legal/eu/aiact#"
DPV_NS   = "https://w3id.org/dpv#"


def short(uri):
    s = str(uri)
    for prefix, ns in [(":", EX_NS), ("airo:", AIRO_NS),
                       ("eu-aiact:", AIACT_NS), ("dpv:", DPV_NS)]:
        if s.startswith(ns):
            return prefix + s[len(ns):]
    return s.split("#")[-1] if "#" in s else s.split("/")[-1]


def colour_for(uri):
    s = str(uri)
    if s.startswith(EX_NS):
        return "#B3D9FF"  # blue — our class
    if s.startswith(AIRO_NS):
        return "#FFD6B3"  # orange — AIRO class
    if s.startswith(DPV_NS):
        return "#FFB3D9"  # pink — DPV core class
    if s.startswith(AIACT_NS):
        return "#D5FFB3"  # green — DPV-AIAct 
    return "#EEEEEE"


dot_lines = [
    'digraph OntologyHierarchy {',
    '  rankdir=LR;',
    '  node [shape=box, style=filled, fontname="Helvetica", fontsize=10];',
    '  edge [arrowhead=empty];',
    '',
    '  subgraph cluster_legend {',
    '    label="Legend"; style=rounded; fontsize=9;',
    '    leg_our [label="Our class" fillcolor="#B3D9FF"];',
    '    leg_airo [label="AIRO class" fillcolor="#FFD6B3"];',
    '    leg_dpv [label="DPV class" fillcolor="#FFB3D9"];',
    '    leg_aiact [label="DPV-AIAct class" fillcolor="#D5FFB3"];',
    '  }',
]

edges = set()
nodes = {}

for s, _, o in g.triples((None, RDFS.subClassOf, None)):
    if isinstance(o, BNode) or isinstance(s, BNode):
        continue
    sn, on = short(s), short(o)
    nodes.setdefault(sn, colour_for(s))
    nodes.setdefault(on, colour_for(o))
    edges.add((sn, on))

for name, colour in nodes.items():
    dot_lines.append(f'  "{name}" [fillcolor="{colour}"];')

for child, parent in edges:
    dot_lines.append(f'  "{child}" -> "{parent}";')

dot_lines.append("}")

dot_src = "\n".join(dot_lines)

proc = subprocess.run(
    ["dot", "-Tpng", "-Gdpi=100"],
    input=dot_src.encode(), capture_output=True
)

if proc.returncode != 0:
    print(f"Graphviz error: {proc.stderr.decode()}")
    sys.exit(1)

with open(PNG_FILE, "wb") as f:
    f.write(proc.stdout)

print(f"Class hierarchy diagram: {PNG_FILE}")
print(f"  {len(nodes)} nodes, {len(edges)} edges")