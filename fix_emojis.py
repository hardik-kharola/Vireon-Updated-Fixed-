import os

emoji_map = {
    '❌': "{get_emoji('error')}",
    '✅': "{get_emoji('success')}",
    '📝': "{get_emoji('rename')}",
    '👤': "{get_emoji('profiles')}",
    '📋': "{get_emoji('logging')}",
    '📅': "{get_emoji('event_sub')}",
    '🔗': "{get_emoji('link')}",
}

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # Simple replacement approach
    for emoji, replacement in emoji_map.items():
        # First, find occurrences of `"emoji ..."` or `'emoji ...'` and ensure they have f-prefix
        # This is a bit tricky, but since most of these strings are like `"❌ Text"` or `f"❌ {var}"`, 
        # we can just use re to do it safely.
        import re
        # Instead of replacing the emoji itself in regex, let's just replace all instances in the string,
        # but only if it's already an f-string or if we add f-prefix.
        
        # We look for strings containing the emoji
        pattern = re.compile(r'([fF]?)(".*?' + emoji + r'.*?"|\'.*?' + emoji + r'.*?\')', flags=re.DOTALL)
        
        def repl(match):
            prefix = match.group(1)
            string_content = match.group(2)
            if not prefix:
                prefix = 'f'
            new_string = string_content.replace(emoji, replacement)
            return prefix + new_string

        content = pattern.sub(repl, content)

    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated {filepath}")

for root, _, files in os.walk('cogs'):
    for file in files:
        if file.endswith('.py') and file not in ['j2c.py']:
            process_file(os.path.join(root, file))
