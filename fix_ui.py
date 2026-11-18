#!/usr/bin/env python3
"""Fix the broken resize method in ui.py"""
import re

with open('ui.py', 'r') as f:
    content = f.read()

# Pattern: the broken resize method has extra code after the runJavaScript call
# Find: runJavaScript(f""" ... """)) followed by extra if (window.earth) block
pattern = r'(self\._webview\.page\(\)\.runJavaScript\(f"""[^"]*?window\.camera\.updateProjectionMatrix\(\);\s*\n\s*\}\s*\n\s*\}\s*\n\s*}\s*""")\)\s*\n\s*if \(window\.earth\) \{[\s\S]*?\n\s*"""\)'

replacement = r'\1)'

new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

if new_content != content:
    with open('ui.py', 'w') as f:
        f.write(new_content)
    print("Fixed!")
else:
    print("No match found - trying alternative approach")
    # Try a simpler line-by-line fix
    lines = content.split('\n')
    new_lines = []
    skip = False
    for i, line in enumerate(lines):
        if 'if (window.earth)' in line:
            skip = True
            print(f"Skipping line {i+1}: {line.strip()}")
            continue
        if skip:
            if '"""")' in line:
                skip = False
                print(f"End skip at line {i+1}: {line.strip()}")
                continue
            print(f"Skipping line {i+1}: {line.strip()}")
            continue
        new_lines.append(line)
    
    new_content = '\n'.join(new_lines)
    with open('ui.py', 'w') as f:
        f.write(new_content)
    print("Fixed via line-by-line!")

print("Done")