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

**Rendering (`index.html` + `gallery.js`)**: `index.html` is a static shell with an empty `#gallery` div. On load, `gallery.js`'s `loadGallery()` fetches `pictures/manifest.json` (an array of `{file, title, meta, description}`) and builds painting cards + the lightbox from it entirely client-side. There is no server logic — `manifest.json` is a build artifact, not hand-written.

**Manifest generation (`generate_manifest.py`)**: run this after adding/removing/re-captioning any image in `pictures/`. It scans `pictures/`, and for each image `foo.jpg` looks for a sibling `foo.txt` (format documented in `TEMPLATE.txt` at repo root — `title:`/`meta:` are single-line, `description:` must be the last key and swallows the rest of the file). `TEMPLATE.txt` itself is just a sample/reference, not consumed directly — no per-image `.txt` files exist in `pictures/` yet, so every painting currently renders as "Unnamed" with no metadata or description. Output is written to `pictures/manifest.json`, which must be regenerated and committed whenever the picture set changes — it's not generated automatically.

```
python3 generate_manifest.py pictures
```
(the script takes the target folder as `argv[1]`; there's no default).

**Image processing pipeline (`picture_processing/`)**: raw phone photos of paintings go through perspective correction before they become gallery-ready images in `pictures/`:
1. `picture_processing/raw_photos/` — original photos (gitignored, not in the repo).
2. `picture_processing/deskew.py <indir> <outdir> [debugdir]` — auto-detects the canvas edges in each photo via OpenCV GrabCut + contour approximation, iteratively refines the 4 corners against the sampled background color, and perspective-warps to a flat rectangle. Prints `NO QUAD FOUND - needs manual crop` for photos it can't handle automatically.
3. `picture_processing/manual_corner_crop.html` — a standalone browser tool (open directly, no server needed) for manually dragging the 4 corners and warping when `deskew.py` fails on a photo. Pure vanilla JS (own homography/DLT solver + canvas warp), no dependencies.
4. Corrected images land in `picture_processing/cropped/`, then get promoted into `pictures/` at the repo root — the top-level `pictures/` folder is what `index.html`/`gallery.js` actually serve. Note `picture_processing/cropped/` currently keeps its own committed copy of `manifest.json` too; the two `pictures` directories are not symlinked, so re-copy files into the top-level `pictures/` when promoting new images.

## Engineering practices
Before working on a feature, look up context and ask questions if unsure. Then plan the implementation in testable steps, and then implement. Write tests, but avoid tests that don't add value. Remove dead code, don't leave technical debt.

TODO: if any good fits exist for this project add commit hooks for type annotations, lint and tests for all languages - python, js, html.

Where applicable, suggest ways of improving the user experience of both website manager and website customer.
