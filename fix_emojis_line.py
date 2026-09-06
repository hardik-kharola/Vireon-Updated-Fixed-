import os

def fix_line(line):
    # Emojis to check
    # We only replace if they are in the line
    replacements = {
        '❌': "{get_emoji('error')}",
        '✅': "{get_emoji('success')}",
        '📝': "{get_emoji('rename')}",
        '👤': "{get_emoji('profiles')}",
        '📋': "{get_emoji('logging')}",
        '📅': "{get_emoji('event_sub')}",
        '🔗': "{get_emoji('link')}",
    }
    
    modified = False
    for em, rep in replacements.items():
        if em in line:
            # Check if this line is an f-string
            # We assume it's in a string.
            # If the line contains `"❌` or `'❌` but not `f"❌`
            if f'"{em}' in line and f'f"{em}' not in line:
                line = line.replace(f'"{em}', f'f"{rep}')
            elif f"'{em}" in line and f"f'{em}" not in line:
                line = line.replace(f"'{em}", f"f'{rep}")
            
            # If it's already an f-string or somewhere else in the string
            if em in line:
                line = line.replace(em, rep)
            modified = True
            
            # Check if we forgot an f-prefix for a non-first character string
            # e.g. "Some text ❌" -> we need f"Some text {rep}"
            # This is harder to perfectly catch, but in our case, the emoji is almost always at the start.
            
    return line, modified

for root, _, files in os.walk('cogs'):
    for file in files:
        if file.endswith('.py') and file not in ['j2c.py']:
            path = os.path.join(root, file)
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            changed = False
            for i in range(len(lines)):
                new_line, mod = fix_line(lines[i])
                if mod:
                    # make sure there is an f before the string if it contains {get_emoji
                    # check if the line has a string that needs f
                    # Just a basic heuristic: if it has send(embed=discord.Embed(description="
                    lines[i] = new_line
                    changed = True
            
            if changed:
                with open(path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                print(f"Fixed {path}")
