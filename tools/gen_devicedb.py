#!/usr/bin/env python3
"""Translate libconcord's remote_info.h into structured JSON.

The model, architecture, flash-chip and sector tables that chorus
needs live in libconcord as C initialisers -- 120 models and 18
architectures, far too much to transcribe by hand without errors. This
parses them out so src/chorus/devicedb.py can be generated instead.

Usage:
    curl -O https://raw.githubusercontent.com/jaymzh/concordance/main/libconcord/remote_info.h
    python tools/gen_devicedb.py remote_info.h devicedb.json
    python tools/emit_devicedb.py devicedb.json src/chorus/devicedb.py

libconcord is GPLv3, by Kevin Timmerman and Phil Dibowitz. See NOTICE.md.
"""

import json
import re
import sys

if len(sys.argv) != 3:
    sys.exit(f"usage: {sys.argv[0]} <remote_info.h> <out.json>")

src = open(sys.argv[1]).read()

MFG = {"MFG_UNK":"Unknown","MFG_HAR":"Logitech","MFG_COOL":"Logicool",
       "MFG_HK":"Harman Kardon","MFG_MON":"Monster"}

# ---- models ----
block = re.search(r"ModelList\[\]=\{(.*?)\n\};", src, re.S).group(1)
models = []
for m in re.finditer(r"\{\s*(MFG_\w+)\s*,\s*\"([^\"]*)\"\s*,\s*(NULL|\"[^\"]*\")\s*\}", block):
    mfg, name, skin = m.group(1), m.group(2), m.group(3)
    skin = None if skin == "NULL" else skin.strip('"')
    models.append((MFG[mfg], name, skin))

# ---- sector tables ----
sectors = {}
for m in re.finditer(r"static const uint32_t (sectors\d+)\[\]=\{(.*?)\};", src, re.S):
    vals = [v.strip() for v in m.group(2).replace("\n"," ").split(",") if v.strip()]
    sectors[m.group(1)] = [int(v,16) if v.lower().startswith("0x") else int(v) for v in vals]

# ---- flash list ----
fblock = re.search(r"FlashList\[\]=\{(.*?)\n\};", src, re.S).group(1)
flashes = []
for m in re.finditer(r"\{\s*(0x[0-9A-Fa-f]+|0)\s*,\s*(0x[0-9A-Fa-f]+|0)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(sectors\d+|NULL)\s*,\s*\"([^\"]*)\"\s*\}", fblock):
    mfg, fid, size, bits, sec, name = m.groups()
    if sec == "NULL": continue
    flashes.append((int(mfg,0), int(fid,0), int(size), int(bits), sec, name))

# ---- arch list ----
ablock = re.search(r"ArchList\[\]=\{(.*)\n\};", src, re.S).group(1)
FIELDS = ["serial_location","serial_address","flash_base","firmware_base","config_base",
          "firmware_update_base","firmware_4847_offset","cookie","cookie_size","end_vector",
          "micro","flash_size","ram_size","eeprom_size","usb"]
archs = []
for am in re.finditer(r"/\* arch (\d+)[^*]*\*/\s*\{(.*?)\n\t\},?", ablock, re.S):
    idx, body = int(am.group(1)), am.group(2)
    vals = []
    for line in body.strip().split("\n"):
        line = line.split("//")[0].strip()
        line = re.sub(r"/\*.*?\*/", "", line).strip()
        if not line: continue
        vals.append(line.rstrip(","). strip())
    assert len(vals) == 15, (idx, len(vals), vals)
    d = {}
    for k, v in zip(FIELDS, vals):
        if v.startswith('"'): d[k] = v.strip('"')
        elif v.startswith("SERIAL_LOCATION_"): d[k] = v.replace("SERIAL_LOCATION_","").lower()
        elif v == "REGION_USER_CONFIG": d[k] = "REGION_USER_CONFIG"
        else: d[k] = int(v, 0)
    archs.append((idx, d))

print(
    f"models={len(models)} flashes={len(flashes)} "
    f"archs={len(archs)} sector_tables={len(sectors)}"
)
json.dump({"models":models,"flashes":flashes,"archs":archs,"sectors":sectors},
          open(sys.argv[2],"w"), indent=1)
