#!/usr/bin/env python3
"""
Scans the pictures/ folder next to this script and rebuilds
pictures/manifest.json, which index.html loads to display the gallery.

Run this every time you add, remove, or re-caption a painting:

    python3 generate_manifest.py

For an image named e.g. "sunset.jpg", if a file "sunset.txt" exists next
to it, its title / meta / description are read from there (see
pictures/TEMPLATE.txt for the file format). If there's no .txt file, the
painting is labelled "Unnamed" with no metadata or description.

Images are listed in natural filename order (so "obr2.jpg" sorts before
"obr10.jpg").
"""
import json
import os
import re
import sys

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
KEY_RE = re.compile(r'^(title|meta|description)\s*:\s*(.*)$', re.IGNORECASE)


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', name)]


def parse_info_file(path):
    """Parses the simple key: value format described in TEMPLATE.txt.

    - Blank lines and lines starting with # are ignored.
    - 'title:' and 'meta:' are single-line fields.
    - 'description:' is special: everything from there to the end of the
      file is treated as the description (so it can safely span multiple
      lines, and can itself contain colons, dashes, etc). Because of this,
      description should always be the last field in the file.
    """
    title, meta = None, None
    description_lines = []
    in_description = False

    with open(path, encoding='utf-8') as f:
        for raw_line in f:
            line = raw_line.rstrip('\n')

            if in_description:
                description_lines.append(line.strip())
                continue

            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue

            m = KEY_RE.match(stripped)
            if not m:
                continue  # ignore unrecognized lines rather than error out

            key, value = m.group(1).lower(), m.group(2).strip()
            if key == 'title':
                title = value
            elif key == 'meta':
                meta = value
            elif key == 'description':
                in_description = True
                if value:
                    description_lines.append(value)

    description = ' '.join(l for l in description_lines if l)
    description = re.sub(r'\s+', ' ', description).strip()
    return title, meta, description


def build_manifest(folder):
    entries = []
    missing_txt = []

    for name in sorted(os.listdir(folder), key=natural_key):
        base, ext = os.path.splitext(name)
        if ext.lower() not in IMAGE_EXTS:
            continue

        txt_path = os.path.join(folder, base + '.txt')
        title = meta = description = None
        if os.path.isfile(txt_path):
            title, meta, description = parse_info_file(txt_path)
        else:
            missing_txt.append(name)

        entries.append({
            'file': name,
            'title': title or 'Unnamed',
            'meta': meta or '',
            'description': description or '',
        })

    return entries, missing_txt


def main():
    #script_dir = os.path.dirname(os.path.abspath(__file__))
    folder = sys.argv[1] # if len(sys.argv) > 1 else os.path.join(script_dir, 'pictures')

    if not os.path.isdir(folder):
        sys.exit(f"Folder not found: {folder}")

    entries, missing_txt = build_manifest(folder)

    out_path = os.path.join(folder, 'manifest.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    print(f"Wrote {out_path} with {len(entries)} image(s).")
    if missing_txt:
        print("No .txt info found for (will show as 'Unnamed'):")
        for name in missing_txt:
            print(f"  - {name}")


if __name__ == '__main__':
    main()
