# Gallery

A static single-page art gallery site — plain HTML/CSS/JS, no build step, no
framework, no `package.json`. Site text is in Czech; code and comments are in
English.

Live at: https://coronav.github.io/Gallery/ (GitHub Pages; changes propagate
shortly after pushing to `main`).

## Running locally

Browsers block `fetch()` of local files under `file://`, and `gallery.js`
fetches `pictures/manifest.json`, so the site must be served over HTTP:

```
python3 -m http.server
```

then open `http://localhost:8000/`.

## Adding or updating a painting

1. Take/collect the raw phone photo(s) and drop them in
   `picture_processing/raw_photos/` (gitignored — never committed).
2. Run the pipeline:

   ```
   python3 update_gallery.py
   ```

   By default this first auto-deskews any new raw photos (detecting the
   canvas edges and perspective-warping them to a flat rectangle into
   `picture_processing/cropped/`), then builds the derivatives, captions
   stubs, and manifest from everything in `cropped/`.
3. If a photo couldn't be auto-deskewed, the run prints
   `NO QUAD FOUND` / a failure summary for it. Either:
   - open `picture_processing/manual_corner_crop.html` directly in a
     browser (no server needed), drag the 4 corners by hand, and move the
     downloaded `<name>_corrected.png` into `picture_processing/cropped/`;
     or
   - add the filename to `picture_processing/raw_ignore.txt` (one per
     line, `#` comments allowed) to stop the pipeline from retrying it.

   Then run `python3 update_gallery.py` again.
4. Fill in captions: open `pictures/captions.txt` and add/edit the
   `title:` / `meta:` / `date:` / `description:` fields for any painting
   listed as missing a title. `date:` accepts `2023`, `2023-05`,
   `5/2023` or `05/2023`, `5.2023`, `12.5.2023` (day.month.year), or
   `2023-05-12` — as much precision as you have. The file's header
   documents the full format.
5. Run `python3 update_gallery.py` again so `manifest.json` picks up the
   new captions.
6. Commit and push. `pictures/web/`, `pictures/thumbs/`,
   `pictures/hires/`, `pictures/manifest.json`, and
   `pictures/captions.txt` are all checked in — GitHub Pages serves them
   directly.

## Architecture

- **`index.html` + `gallery.js`** — `index.html` is a static shell with an
  empty `#gallery` div. On load, `gallery.js`'s `loadGallery()` fetches
  `pictures/manifest.json` (an array of `{file, thumb, hires, width,
  height, title, meta, date, description}`) and builds the painting cards
  + lightbox from it entirely client-side. There is no server logic.
- **`update_gallery.py`** — the single pipeline script. It has two
  stages: (1) an on-by-default deskew stage that auto-corrects new raw
  photos from `picture_processing/raw_photos/` into
  `picture_processing/cropped/` (skip with `--skip-deskew`); (2) the
  derivatives stage, which turns everything in `cropped/` into what
  `pictures/` needs: three resized JPEG tiers — `web/` (max 1600px),
  `thumbs/` (max 480px), and `hires/` (max 2560px, for zooming in) —
  `captions.txt` stubs for new paintings, and `manifest.json`. Because
  the paintings are photos of woven canvas, each downscale is followed by
  a small Gaussian blur to suppress the moiré that canvas texture
  otherwise produces against the resample and the display's pixel grid.
  Run it after adding, removing, or re-cropping any image. See
  `python3 update_gallery.py --help` for the `--source`, `--out`, `--raw`,
  `--force`, and `--skip-deskew` flags.
- **`pictures/captions.txt`** — the single source of truth for every
  painting's title/meta/date/description, keyed by the source filename in
  `picture_processing/cropped/` (e.g. `[IMG_1202_corrected.jpg]`). See the
  header comment in the file itself for the exact format.
- **`picture_processing/`** — the image-correction pipeline:
  `raw_photos/` (gitignored originals) → `deskew.py` (automatic
  perspective correction, invoked by `update_gallery.py` itself) or
  `manual_corner_crop.html` (manual fallback) → `cropped/` (flat,
  full-resolution corrected images, the input to `update_gallery.py`'s
  derivatives stage). `raw_ignore.txt` (optional) lists raw filenames to
  never auto-deskew.

## Tests

```
python3 -m unittest discover -s tests
```
