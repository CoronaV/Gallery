# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What this is

A static single-page art gallery site using plain HTML/CSS/JS, no build step, no framework, no `package.json`. Site text is in Czech; code and comments are in English.

## Running the site

Browsers block `fetch()` of local files under `file://`, and `gallery.js` fetches `pictures/manifest.json`, so the site must be served over HTTP, not opened directly:

```
python3 -m http.server
```
then open `http://localhost:8000/`.

The site is currently hosted on Github: `https://coronav.github.io/Gallery/` - changes should propagate shortly after pushing to origin.

## Architecture

**Rendering (`index.html` + `gallery.js`)**: `index.html` is a static shell with an empty `#gallery` div. On load, `gallery.js`'s `loadGallery()` fetches `pictures/manifest.json` (an array of `{file, thumb, hires, width, height, title, meta, date, description}`, paths relative to `pictures/`) and builds painting cards + the lightbox from it entirely client-side. The manifest array order is the display order (see stage 3 below). Cards render in batches of 12 via an IntersectionObserver sentinel (`#gallery-sentinel`); the grid shows `thumb`, the lightbox shows `file` immediately and silently swaps in `hires` once it loads (stale-swap guarded via a token), with prev/next buttons, arrow keys, and touch swipe. There is no server logic — `manifest.json` is a build artifact, not hand-written.

**Pipeline (`update_gallery.py`)**: the single command that goes from raw phone photos to everything `pictures/` serves. Stages, in order:
1. **Deskew** (skippable via `--skip-deskew`): every image in `picture_processing/raw_photos/` (gitignored) without a `<stem>_corrected.jpg|png` counterpart in `picture_processing/cropped/` gets auto-deskewed via `picture_processing/deskew.py` (OpenCV GrabCut, a few seconds per photo). Failures are reported with instructions to use `picture_processing/manual_corner_crop.html` (standalone browser tool; saves `<name>_corrected.png` to move into `cropped/`) or to list the file in `picture_processing/raw_ignore.txt` (one filename per line — used for non-painting reference shots like title-label photos).
2. **Derivatives**: three JPEG tiers per painting — `pictures/thumbs/` (max 480px, grid), `pictures/web/` (max 1600px, initial lightbox), `pictures/hires/` (max 2560px, progressive lightbox upgrade). Output names strip the `_corrected` suffix. Each LANCZOS downscale is followed by a slight Gaussian blur (anti-moiré low-pass; the canvas weave otherwise aliases against browser rescaling — radii in `*_BLUR_RADIUS` constants). Incremental via mtimes (`--force` to rebuild); orphaned derivatives of removed sources are deleted.
3. **Captions + manifest**: `pictures/captions.txt` is ONE file holding every painting's `title:`/`meta:`/`date:`/`description:`, keyed by source filename sections like `[IMG_1202_corrected.jpg]`; the script appends empty stub sections for new images and reports missing titles. `date:` accepts `2023`, `2023-05`, `5/2023`, `12.5.2023`, `2023-05-12` etc. and is stored ISO-truncated (string-sortable). `description:` must be last in a section and runs until the next `[section]`. Then `pictures/manifest.json` is regenerated. **The order of `[section]`s in `captions.txt` is the gallery's display order** — the manifest (and so the site) is sorted to match it; newly stubbed images are appended at the end. Reorder the gallery by moving whole sections in that file.

Run `python3 update_gallery.py` after adding, removing, re-cropping, or re-captioning any image, then commit the changed files under `pictures/`. Full workflow is in `README.md`.

Note: `picture_processing/cropped/` keeps the full-resolution files committed as the archival source; `pictures/` only holds the small generated derivatives. Never put full-res images back into `pictures/`.

## Tests

```
python3 -m unittest discover -s tests
```
Stdlib `unittest` only (pytest is not installed on this machine). Tests cover the caption parser, stub appending, manifest generation (including caption-driven ordering), image conversion, orphan cleanup, and incremental skipping in `update_gallery.py`.

Lint with `python3 -m ruff check .` (config in `pyproject.toml`). A versioned pre-commit hook at `hooks/pre-commit` runs ruff + the tests on every commit; it's enabled per-clone via `git config core.hooksPath hooks`. The hook treats a missing ruff as a warning (skips lint) but always runs the tests.

## Engineering practices
Before working on a feature, look up context and ask questions if unsure. Then plan the implementation in testable steps, and then implement. Write tests, but avoid tests that don't add value. Remove dead code, don't leave technical debt.

Where applicable, suggest ways of improving the user experience of both website manager and website customer.
