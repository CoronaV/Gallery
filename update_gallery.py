#!/usr/bin/env python3
"""
Unified gallery pipeline. By default it first auto-deskews any new raw phone
photos in picture_processing/raw_photos/ into picture_processing/cropped/,
then takes every full-resolution corrected painting in cropped/ and produces
everything the website needs in pictures/ — resized hires/web/thumbnail
derivatives, captions.txt stubs, and manifest.json.

Run this every time you add, remove, or re-crop a painting:

    python3 update_gallery.py

Then fill in any empty titles/meta/dates/descriptions this run reports in
pictures/captions.txt, and run it again so manifest.json picks them up.

See README.md for the full add-a-painting workflow.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import time
import json
from datetime import date
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

# Source images are trusted local files (our own photos), never untrusted
# uploads, so it's safe to disable Pillow's decompression-bomb guard.
Image.MAX_IMAGE_PIXELS = None

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
CORRECTED_SUFFIX = '_corrected'

# Raw phone photos accepted by the deskew stage, and the extensions the
# manual-crop tool / deskew.py may save a corrected counterpart as.
RAW_EXTS = {'.jpg', '.jpeg', '.png'}
CORRECTED_EXTS = ('.jpg', '.png')

WEB_MAX_EDGE = 1600
WEB_QUALITY = 85
THUMB_MAX_EDGE = 480
THUMB_QUALITY = 78
HIRES_MAX_EDGE = 2560
HIRES_QUALITY = 83

# Anti-moiré low-pass. The paintings are photos of textured/woven canvas, and
# that fine weave pattern aliases - first against the LANCZOS downscale, then
# again against the browser's/display's own pixel grid - producing moiré.
# A slight Gaussian blur applied right after each downscale strips the
# near-Nyquist frequencies responsible, at a cost in sharpness far smaller
# than the artifact it removes. Smaller derivatives downscale more (more
# aliasing risk), hence the larger radius for thumbs than for hires.
THUMB_BLUR_RADIUS = 0.7
WEB_BLUR_RADIUS = 0.5
HIRES_BLUR_RADIUS = 0.4

KEY_RE = re.compile(r'^(title|meta|date|description)\s*:\s*(.*)$', re.IGNORECASE)
SECTION_RE = re.compile(r'^\[(.+)\]\s*$')

# Accepted `date:` input formats, tried in order. Whitespace around
# separators is tolerated, and a single trailing '.' is allowed.
_DATE_ISO_FULL = re.compile(r'^(\d{4})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})\.?$')       # 2023-05-12
_DATE_ISO_YM = re.compile(r'^(\d{4})\s*-\s*(\d{1,2})\.?$')                        # 2023-05
_DATE_DMY_DOT = re.compile(r'^(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})\.?$')     # 12.5.2023 / 12. 5. 2023
_DATE_MY_SLASH = re.compile(r'^(\d{1,2})\s*/\s*(\d{4})\.?$')                      # 5/2023, 05/2023
_DATE_MY_DOT = re.compile(r'^(\d{1,2})\s*\.\s*(\d{4})\.?$')                       # 5.2023
_DATE_YEAR = re.compile(r'^(\d{4})\.?$')                                          # 2023

CAPTIONS_HEADER = """\
# Captions for the gallery paintings - one file for all of them.
#
# Format:
#   - Lines starting with # are comments and are ignored.
#   - Each painting has a section headed by [source_file_name], e.g.
#     [IMG_1202_corrected.jpg].
#   - The name in brackets MUST exactly match a file in
#     picture_processing/cropped/ (including extension and "_corrected").
#   - "title:", "meta:", and "date:" are single-line fields.
#   - "date:" accepts: 2023 | 2023-05 | 5/2023 or 05/2023 | 5.2023 |
#     12.5.2023 or 12. 5. 2023 (day.month.year) | 2023-05-12. Leave it
#     empty if the date is unknown.
#   - "description:" MUST be the last field in a section - everything
#     after it (across as many lines as you like) becomes the description,
#     until the next [section] starts.
#   - Empty title/meta/date/description are fine - the painting just
#     displays without that piece of info.
#
# After saving changes, re-run:
#     python3 update_gallery.py
"""


def natural_key(name: str):
    """Splits a filename into text/int chunks so e.g. 'obr2' < 'obr10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', name)]


def out_stem(source_name: str) -> str:
    """Derivative basename (no extension) for a source filename, with any
    trailing '_corrected' suffix stripped, e.g. 'IMG_1202_corrected' -> 'IMG_1202'."""
    stem = Path(source_name).stem
    if stem.endswith(CORRECTED_SUFFIX):
        stem = stem[: -len(CORRECTED_SUFFIX)]
    return stem


# --- image processing -------------------------------------------------

def to_rgb(img: Image.Image) -> Image.Image:
    """Flattens images with transparency/palettes onto a white background,
    returning a plain RGB image ready to save as JPEG."""
    if img.mode == 'RGB':
        return img
    if img.mode in ('RGBA', 'LA', 'P'):
        rgba = img.convert('RGBA')
        background = Image.new('RGB', rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return img.convert('RGB')


def fit(img: Image.Image, max_edge: int, blur_radius: float = 0.0) -> Image.Image:
    """Downscales img so its longest edge is at most max_edge, preserving
    aspect ratio, never upscaling. When downscaling actually happens, applies
    a slight Gaussian blur afterwards to suppress moiré from the resample
    (see THUMB/WEB/HIRES_BLUR_RADIUS above). Skipped when the source is
    already at or below max_edge - there's no fresh aliasing to suppress."""
    width, height = img.size
    longest = max(width, height)
    if longest <= max_edge:
        return img.copy()
    scale = max_edge / longest
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    resized = img.resize(new_size, Image.LANCZOS)
    if blur_radius:
        resized = resized.filter(ImageFilter.GaussianBlur(blur_radius))
    return resized


def process_image(src: Path, web_path: Path, thumb_path: Path, hires_path: Path) -> tuple[int, int]:
    """Builds the hires, web, and thumbnail JPEG derivatives for one source
    image. Returns the (width, height) of the web derivative (that's what
    the manifest's width/height describe)."""
    with Image.open(src) as raw:
        transposed = ImageOps.exif_transpose(raw)
        rgb = to_rgb(transposed if transposed is not None else raw)

        hires_img = fit(rgb, HIRES_MAX_EDGE, HIRES_BLUR_RADIUS)
        hires_img.save(hires_path, 'JPEG', quality=HIRES_QUALITY, optimize=True, progressive=True)

        web_img = fit(rgb, WEB_MAX_EDGE, WEB_BLUR_RADIUS)
        web_img.save(web_path, 'JPEG', quality=WEB_QUALITY, optimize=True, progressive=True)

        thumb_img = fit(rgb, THUMB_MAX_EDGE, THUMB_BLUR_RADIUS)
        thumb_img.save(thumb_path, 'JPEG', quality=THUMB_QUALITY, optimize=True, progressive=True)

        return web_img.size


def is_up_to_date(src: Path, web_path: Path, thumb_path: Path, hires_path: Path) -> bool:
    if not (web_path.exists() and thumb_path.exists() and hires_path.exists()):
        return False
    src_mtime = src.stat().st_mtime
    return (web_path.stat().st_mtime > src_mtime
            and thumb_path.stat().st_mtime > src_mtime
            and hires_path.stat().st_mtime > src_mtime)


def cleanup_orphans(directory: Path, keep_names: set[str]) -> list[str]:
    """Deletes files in directory whose name isn't in keep_names. Returns
    the names removed."""
    removed = []
    if not directory.is_dir():
        return removed
    for f in directory.iterdir():
        if f.is_file() and f.name not in keep_names:
            f.unlink()
            removed.append(f.name)
    return removed


# --- date parsing --------------------------------------------------------

def parse_date(value: str, section_name: str) -> str:
    """Parses a `date:` field value into an ISO-truncated string that
    preserves the input's precision ("2023", "2023-05", or "2023-05-12") -
    these sort correctly as plain strings. Accepts: 2023 | 2023-05 |
    5/2023 or 05/2023 | 5.2023 | 12.5.2023 or 12. 5. 2023 (day.month.year) |
    2023-05-12. Empty input returns ''. Unparseable or out-of-range input
    prints a warning naming the section and returns ''."""
    value = value.strip()
    if not value:
        return ''

    def invalid():
        print(f"Warning: unparseable date '{value}' in section [{section_name}]; storing empty date.")
        return ''

    m = _DATE_ISO_FULL.match(value)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            date(year, month, day)
        except ValueError:
            return invalid()
        return f"{year:04d}-{month:02d}-{day:02d}"

    m = _DATE_DMY_DOT.match(value)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            date(year, month, day)
        except ValueError:
            return invalid()
        return f"{year:04d}-{month:02d}-{day:02d}"

    m = _DATE_ISO_YM.match(value)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            return invalid()
        return f"{year:04d}-{month:02d}"

    m = _DATE_MY_SLASH.match(value)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            return invalid()
        return f"{year:04d}-{month:02d}"

    m = _DATE_MY_DOT.match(value)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            return invalid()
        return f"{year:04d}-{month:02d}"

    m = _DATE_YEAR.match(value)
    if m:
        return f"{int(m.group(1)):04d}"

    return invalid()


# --- captions.txt -------------------------------------------------------

def parse_captions(text: str) -> dict:
    """Parses captions.txt content into {source_filename: {title, meta,
    date, description}}. Every [section] encountered is included (even if
    all its fields are empty), so callers can tell "has a section" from
    "has content"."""
    sections: dict[str, dict] = {}
    current = None
    in_description = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip('\n')
        stripped = line.strip()

        section_match = SECTION_RE.match(stripped)
        if section_match:
            current = section_match.group(1).strip()
            sections[current] = {'title': '', 'meta': '', 'date': '', 'description_lines': []}
            in_description = False
            continue

        if current is None:
            continue  # header/comment lines before the first section

        if in_description:
            sections[current]['description_lines'].append(stripped)
            continue

        if not stripped or stripped.startswith('#'):
            continue

        key_match = KEY_RE.match(stripped)
        if not key_match:
            continue  # ignore unrecognized lines rather than error out

        key, value = key_match.group(1).lower(), key_match.group(2).strip()
        if key == 'title':
            sections[current]['title'] = value
        elif key == 'meta':
            sections[current]['meta'] = value
        elif key == 'date':
            sections[current]['date'] = parse_date(value, current)
        elif key == 'description':
            in_description = True
            if value:
                sections[current]['description_lines'].append(value)

    result = {}
    for name, data in sections.items():
        description = ' '.join(l for l in data['description_lines'] if l)
        description = re.sub(r'\s+', ' ', description).strip()
        result[name] = {
            'title': data['title'],
            'meta': data['meta'],
            'date': data['date'],
            'description': description,
        }
    return result


def ensure_captions_file(path: Path) -> None:
    if not path.exists():
        path.write_text(CAPTIONS_HEADER + '\n', encoding='utf-8')


def append_missing_sections(path: Path, missing_names: list[str]) -> None:
    if not missing_names:
        return
    existing = path.read_text(encoding='utf-8') if path.exists() else ''
    prefix = '' if (not existing or existing.endswith('\n')) else '\n'
    stub = ''.join(f"\n[{name}]\ntitle:\nmeta:\ndate:\ndescription:\n" for name in missing_names)
    with path.open('a', encoding='utf-8') as f:
        f.write(prefix + stub)


# --- deskew stage ---------------------------------------------------------

def load_ignore_list(path: Path) -> set[str]:
    """Reads an optional raw_ignore.txt: one filename per line, '#' comments
    and blank lines ignored, matched case-insensitively. Missing file -> no
    ignores (the file is never auto-created)."""
    if not path.exists():
        return set()
    names = set()
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.split('#', 1)[0].strip()
        if line:
            names.add(line.lower())
    return names


def has_corrected_counterpart(stem: str, cropped_dir: Path) -> bool:
    """True if <stem>_corrected.jpg or <stem>_corrected.png already exists in
    cropped_dir (deskew.py writes .jpg; the manual browser tool saves .png)."""
    return any((cropped_dir / f"{stem}{CORRECTED_SUFFIX}{ext}").exists() for ext in CORRECTED_EXTS)


def import_deskew_module():
    """Loads picture_processing/deskew.py as a standalone module (there's no
    package __init__.py, so it can't be imported normally). Returns None -
    after printing a one-line note - if the file or its cv2 dependency can't
    be imported, so the caller can skip the stage and carry on."""
    try:
        deskew_path = Path(__file__).resolve().parent / 'picture_processing' / 'deskew.py'
        spec = importlib.util.spec_from_file_location('gallery_deskew', deskew_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as exc:
        print(f"Note: deskew stage unavailable ({exc}); skipping it and continuing.")
        return None


def run_deskew_stage(raw_dir: Path, cropped_dir: Path, skip: bool, deskew_module=None) -> None:
    """Auto-corrects new raw photos from raw_dir into cropped_dir before the
    derivatives stage runs. No-ops (cheaply) when skip is True, when raw_dir
    doesn't exist, or when the deskew module/cv2 can't be loaded - a missing
    or broken deskew stage should never prevent the rest of the pipeline
    from running. Pass deskew_module to inject a stub for testing; leave it
    None to import the real picture_processing/deskew.py."""
    if skip:
        return

    if not raw_dir.is_dir():
        print(f"Note: raw photos folder not found ({raw_dir}); skipping deskew stage.")
        return

    deskew = deskew_module if deskew_module is not None else import_deskew_module()
    if deskew is None:
        return

    ignore_path = raw_dir.parent / 'raw_ignore.txt'
    ignored_names = load_ignore_list(ignore_path)

    cropped_dir.mkdir(parents=True, exist_ok=True)

    raw_images = [p for p in raw_dir.iterdir()
                  if p.is_file() and p.suffix.lower() in RAW_EXTS]
    raw_images.sort(key=lambda p: natural_key(p.name))

    already = ignored = 0
    succeeded: list[str] = []
    failed: list[str] = []

    for raw_path in raw_images:
        if raw_path.name.lower() in ignored_names:
            ignored += 1
            continue
        if has_corrected_counterpart(raw_path.stem, cropped_dir):
            already += 1
            continue
        result = deskew.process(str(raw_path), str(cropped_dir))
        if result:
            succeeded.append(raw_path.name)
        else:
            failed.append(raw_path.name)

    print(f"Deskew stage: {len(raw_images)} raw photo(s) in {raw_dir}/")
    print(f"  already corrected: {already}, ignored: {ignored}, "
          f"newly deskewed: {len(succeeded)}, failed: {len(failed)}")
    if failed:
        print("  Auto-deskew failed for:")
        for name in failed:
            print(f"    - {name}")
        print("  For each: open picture_processing/manual_corner_crop.html in a browser and")
        print("  hand-crop it (it downloads <name>_corrected.png - move that file into")
        print(f"  {cropped_dir}/), or add the filename to {ignore_path} to stop retrying it.")


# --- pipeline -------------------------------------------------------

def gather_source_images(source_dir: Path) -> list[Path]:
    images = [p for p in source_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    images.sort(key=lambda p: natural_key(p.name))
    return images


def run(source_dir: Path, out_dir: Path, force: bool,
        raw_dir: Path | None = None, skip_deskew: bool = True) -> None:
    """Runs the full pipeline: deskew stage, then derivatives, then
    captions/manifest.

    skip_deskew defaults to True so that programmatic/test callers that
    don't pass it get the old (no deskew stage) behavior with no cv2
    dependency and no risk of invoking real GrabCut; the CLI entry point
    below wires up --skip-deskew to explicitly pass False by default, which
    is what makes the deskew stage "on by default" for real runs."""
    start = time.perf_counter()

    if raw_dir is None:
        raw_dir = Path('picture_processing/raw_photos')
    run_deskew_stage(raw_dir, source_dir, skip_deskew)

    if not source_dir.is_dir():
        sys.exit(f"Source folder not found: {source_dir}")

    web_dir = out_dir / 'web'
    thumb_dir = out_dir / 'thumbs'
    hires_dir = out_dir / 'hires'
    web_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir.mkdir(parents=True, exist_ok=True)
    hires_dir.mkdir(parents=True, exist_ok=True)

    images = gather_source_images(source_dir)
    if not images:
        print(f"No images found in {source_dir} (looking for {sorted(IMAGE_EXTS)}).")

    processed = 0
    skipped = 0
    expected_names = set()
    raw_entries = []  # {src_name, file, thumb, hires, width, height}

    for src in images:
        name = out_stem(src.name) + '.jpg'
        expected_names.add(name)
        web_path = web_dir / name
        thumb_path = thumb_dir / name
        hires_path = hires_dir / name

        if not force and is_up_to_date(src, web_path, thumb_path, hires_path):
            skipped += 1
            with Image.open(web_path) as existing:
                width, height = existing.size
        else:
            width, height = process_image(src, web_path, thumb_path, hires_path)
            processed += 1

        raw_entries.append({
            'src_name': src.name,
            'file': f'web/{name}',
            'thumb': f'thumbs/{name}',
            'hires': f'hires/{name}',
            'width': width,
            'height': height,
        })

    removed = (cleanup_orphans(web_dir, expected_names)
               + cleanup_orphans(thumb_dir, expected_names)
               + cleanup_orphans(hires_dir, expected_names))

    print(f"Scanned {len(images)} image(s) in {source_dir}/")
    print(f"  processed: {processed}, skipped (up to date): {skipped}")
    if removed:
        print(f"  removed {len(removed)} orphaned derivative file(s): {', '.join(sorted(set(removed)))}")

    # --- captions ---
    captions_path = out_dir / 'captions.txt'
    ensure_captions_file(captions_path)
    captions = parse_captions(captions_path.read_text(encoding='utf-8'))

    missing_sections = [e['src_name'] for e in raw_entries if e['src_name'] not in captions]
    if missing_sections:
        append_missing_sections(captions_path, missing_sections)
        # re-parse so the freshly appended (empty) stubs are reflected below
        captions = parse_captions(captions_path.read_text(encoding='utf-8'))

    manifest = []
    missing_titles = []
    for e in raw_entries:
        caption = captions.get(e['src_name'], {'title': '', 'meta': '', 'date': '', 'description': ''})
        if not caption['title']:
            missing_titles.append(e['src_name'])
        manifest.append({
            'file': e['file'],
            'thumb': e['thumb'],
            'hires': e['hires'],
            'width': e['width'],
            'height': e['height'],
            'title': caption['title'],
            'meta': caption['meta'],
            'date': caption['date'],
            'description': caption['description'],
        })

    manifest_path = out_dir / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Wrote {manifest_path} with {len(manifest)} entry(ies).")

    if missing_titles:
        print(f"\n{len(missing_titles)} painting(s) still need a title in {captions_path}:")
        for name in missing_titles:
            print(f"  - {name}")

    elapsed = time.perf_counter() - start
    print(f"\nDone in {elapsed:.1f}s. Review {captions_path}, then commit & push.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('--source', type=Path, default=Path('picture_processing/cropped'),
                         help="folder with full-resolution corrected paintings (default: %(default)s)")
    parser.add_argument('--out', type=Path, default=Path('pictures'),
                         help="folder the website serves from (default: %(default)s)")
    parser.add_argument('--raw', type=Path, default=Path('picture_processing/raw_photos'),
                         help="folder with raw phone photos to auto-deskew (default: %(default)s)")
    parser.add_argument('--force', action='store_true',
                         help="reprocess every image even if derivatives look up to date")
    parser.add_argument('--skip-deskew', action='store_true',
                         help="don't auto-deskew new raw photos before building derivatives")
    args = parser.parse_args()

    run(args.source, args.out, args.force, raw_dir=args.raw, skip_deskew=args.skip_deskew)


if __name__ == '__main__':
    main()
