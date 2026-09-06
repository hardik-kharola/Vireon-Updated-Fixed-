import re

with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if i >= 461 and i <= 469:
        if lines[i].startswith("        "):
            lines[i] = "    " + lines[i]

with open("scratch/main_fixed.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
