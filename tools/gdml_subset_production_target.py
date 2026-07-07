#!/usr/bin/env python3
"""Extract a standalone GDML of ONLY the PS production target assembly.

The as-built preflight GDML (asbuilt_<config>.gdml) contains the full Mu2e
world (~13.7k volumes); a viewer then buries the 35 thin Stickman plates
inside DS/PS/dirt. This pulls ProductionTargetMother and everything it
contains (35 ProductionTargetPlate* + rods + spacers + support rings + spoke
wires + support wheel) into a minimal GDML whose top (setup/world) volume IS
ProductionTargetMother — so a viewer shows the target assembly and nothing
else.

This is the prodtarget analog of gdml_subset_stopping_target.py (foils), but
generalized: it walks the volume tree recursively (not just direct leaves),
closes over boolean-solid first/second refs, and carries the whole materials
block so composite materials (e.g. Inconel718 -> element fractions) keep their
referenced elements.

Volumes are emitted post-order (daughters before mother) so ROOT's TGDMLParse
(which segfaults on forward <volume> refs — see
wiki/incidents/root-gdml-forward-volume-ref.md) reads it cleanly. Geant4's
reader is order-tolerant either way.

Usage:
  python3 tools/gdml_subset_production_target.py <asbuilt.gdml> [out.gdml]
                                                 [--mother NAME] [--plates-only]
"""
import sys
import xml.etree.ElementTree as ET

NS = "http://www.w3.org/2001/XMLSchema-instance"


def _local(e):
    return e.tag.split("}")[-1]


def extract(in_path, out_path, mother_sub="ProductionTargetMother",
            daughter_sub=None):
    """Generic subset extractor. mother_sub picks the world volume by name
    substring; daughter_sub (optional) keeps only the mother's DIRECT
    daughters whose name contains it (descendants of kept daughters are
    always carried). tools/gdml_subset_stopping_target.py wraps this."""
    tree = ET.parse(in_path)
    root = tree.getroot()
    sect = {_local(c): c for c in root}

    vols = {v.get("name"): v for v in sect["structure"]
            if _local(v) == "volume"}
    solids = {s.get("name"): s for s in sect["solids"]}

    # 1. Locate the mother volume by name substring (GDML appends 0x… ptrs).
    mother_name = next((n for n in vols if n and mother_sub in n), None)
    if mother_name is None:
        sys.exit(f"no volume matching '{mother_sub}' found")

    # 2. Post-order traversal from the mother: daughters before parents.
    #    daughter_sub: drop non-matching daughters of the mother but still
    #    keep the mother as the world wrapper.
    order, seen = [], set()

    def dfs(name):
        if name in seen or name not in vols:
            return
        seen.add(name)
        for pv in vols[name].findall("{*}physvol"):
            ref = pv.find("{*}volumeref")
            if ref is None:
                continue
            child = ref.get("ref")
            if (daughter_sub and name == mother_name
                    and daughter_sub not in (child or "")):
                continue
            dfs(child)
        order.append(name)

    dfs(mother_name)
    keep_vols = order                       # leaves … mother (post-order)

    # 3. Solid refs from kept volumes, then close over boolean first/second.
    solid_refs = set()
    for vn in keep_vols:
        sr = vols[vn].find("{*}solidref")
        if sr is not None:
            solid_refs.add(sr.get("ref"))
    closed, stack = set(), list(solid_refs)
    while stack:
        s = stack.pop()
        if s in closed or s not in solids:
            continue
        closed.add(s)
        for sub in solids[s].iter():        # boolean: <first/second ref=…>
            r = sub.get("ref")
            if r and r in solids and r not in closed:
                stack.append(r)
    solid_refs = closed

    # 4. Build output. Carry whole define + whole materials (cheap, and keeps
    #    composite-material element refs intact); filter solids; reorder vols.
    gdml = ET.Element("gdml")
    gdml.set(f"{{{NS}}}noNamespaceSchemaLocation",
             "http://service-spi.web.cern.ch/service-spi/app/releases/"
             "GDML/schema/gdml.xsd")
    gdml.append(sect["define"])
    gdml.append(sect["materials"])

    out_solids = ET.SubElement(gdml, "solids")
    for s in sect["solids"]:
        if s.get("name") in solid_refs:
            out_solids.append(s)

    out_struct = ET.SubElement(gdml, "structure")
    for vn in keep_vols:                     # already post-order
        out_struct.append(vols[vn])

    setup = ET.SubElement(gdml, "setup")
    setup.set("name", "Default")
    setup.set("version", "1.0")
    ET.SubElement(setup, "world").set("ref", mother_name)

    ET.ElementTree(gdml).write(out_path, encoding="UTF-8",
                               xml_declaration=True)

    tag = daughter_sub or "ProductionTargetPlate"
    n_match = sum(1 for v in keep_vols if tag in v)
    n_other = len(keep_vols) - n_match - 1   # minus the mother
    print(f"wrote {out_path}: world={mother_name.split('0x')[0]}  "
          f"{n_match} {tag}* + {n_other} other vols + mother, "
          f"{len(solid_refs)} solids "
          f"({'filtered to ' + daughter_sub + '*' if daughter_sub else 'full assembly'})")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        sys.exit(__doc__)
    src = args[0]
    dst = args[1] if len(args) > 1 else src.replace(".gdml", "_prodtarget.gdml")
    mother = "ProductionTargetMother"
    if "--mother" in sys.argv:
        mother = sys.argv[sys.argv.index("--mother") + 1]
    extract(src, dst, mother_sub=mother,
            daughter_sub="ProductionTargetPlate" if "--plates-only" in flags else None)
