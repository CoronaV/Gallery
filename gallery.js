/*
 * gallery.js — builds the gallery from pictures/manifest.json.
 *
 * A plain webpage can't list the files in a folder on its own (browsers
 * block that for security reasons), so pictures/manifest.json holds the
 * list instead. Run `python3 update_gallery.py` any time you add, remove,
 * or re-caption a painting, then refresh the page.
 *
 * IMPORTANT: fetch() of local files is blocked under file://. Serve this
 * folder over http:// — even just `python3 -m http.server` run inside it,
 * then open http://localhost:8000/ — or upload it to any static host.
 */

const BATCH_SIZE = 12;

let paintings = [];
let renderedCount = 0;
let galleryEl = null;
let sentinelObserver = null;
let currentIndex = -1;
let touchStartX = null;
let lightboxToken = 0;

async function loadGallery() {
  galleryEl = document.getElementById('gallery');

  try {
    const res = await fetch('pictures/manifest.json', { cache: 'no-store' });
    if (!res.ok) throw new Error('manifest.json not found (' + res.status + ')');
    paintings = await res.json();
  } catch (err) {
    galleryEl.innerHTML =
      '<p class="gallery-status">Couldn’t load the picture list. ' +
      'Run <code>python3 update_gallery.py</code> after adding images, and make ' +
      'sure this page is served over http:// (not opened directly as a file) — ' +
      'e.g. run <code>python3 -m http.server</code> in this folder.</p>';
    console.error('Gallery load failed:', err);
    return;
  }

  if (!paintings.length) {
    galleryEl.innerHTML = '<p class="gallery-status">No paintings in pictures/ yet.</p>';
    return;
  }

  galleryEl.innerHTML = '';
  renderedCount = 0;

  if (typeof IntersectionObserver === 'undefined') {
    // No lazy-batching support — just render everything up front.
    renderNextBatch(paintings.length);
  } else {
    renderNextBatch(BATCH_SIZE);
    setupSentinel();
  }
}

function buildCard(p, i) {
  const card = document.createElement('div');
  card.className = 'painting';
  card.style.animationDelay = (Math.min(i, 8) * 0.08) + 's';
  card.addEventListener('click', () => openLightbox(i));

  const title = p.title || 'Bez názvu';
  const metaLine = p.meta
    ? '<div class="painting-meta">' + escapeHtml(p.meta) + '</div>'
    : '';

  card.innerHTML =
    '<div class="painting-frame">' +
      '<img src="pictures/' + encodeURI(p.thumb) + '" alt="' + escapeHtml(title) + '" loading="lazy" />' +
    '</div>' +
    '<div class="painting-info">' +
      '<div class="painting-title">' + escapeHtml(title) + '</div>' +
      metaLine +
    '</div>';

  return card;
}

function renderNextBatch(count) {
  const end = Math.min(renderedCount + (count || BATCH_SIZE), paintings.length);
  const frag = document.createDocumentFragment();
  for (let i = renderedCount; i < end; i++) {
    frag.appendChild(buildCard(paintings[i], i));
  }
  galleryEl.appendChild(frag);
  renderedCount = end;

  if (renderedCount >= paintings.length && sentinelObserver) {
    sentinelObserver.disconnect();
  }
}

function setupSentinel() {
  const sentinel = document.getElementById('gallery-sentinel');
  if (!sentinel || renderedCount >= paintings.length) return;

  sentinelObserver = new IntersectionObserver((entries) => {
    if (renderedCount >= paintings.length) {
      sentinelObserver.disconnect();
      return;
    }
    if (entries.some(entry => entry.isIntersecting)) {
      renderNextBatch();
    }
  }, { rootMargin: '600px 0px' });

  sentinelObserver.observe(sentinel);
}

function openLightbox(i) {
  currentIndex = wrapIndex(i);
  renderLightbox();
  document.getElementById('lightbox').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function showPrev() {
  currentIndex = wrapIndex(currentIndex - 1);
  renderLightbox();
}

function showNext() {
  currentIndex = wrapIndex(currentIndex + 1);
  renderLightbox();
}

function wrapIndex(i) {
  return ((i % paintings.length) + paintings.length) % paintings.length;
}

function renderLightbox() {
  const p = paintings[currentIndex];
  const title = p.title || 'Bez názvu';
  const index = currentIndex;
  const token = ++lightboxToken;

  const img = document.getElementById('lb-img');
  img.src = 'pictures/' + encodeURI(p.file);
  img.alt = title;
  img.style.aspectRatio = (p.width && p.height) ? (p.width + ' / ' + p.height) : '';

  document.getElementById('lb-title').textContent = title;

  const metaEl = document.getElementById('lb-meta');
  metaEl.textContent = p.meta || '';
  metaEl.style.display = p.meta ? '' : 'none';

  document.getElementById('lb-desc').textContent = p.description || '';
  document.getElementById('lb-counter').textContent = (currentIndex + 1) + ' / ' + paintings.length;

  preloadNeighbors();
  loadHiRes(p, index, token);
}

// Loads the hi-res version of painting `index` in the background and swaps
// it into the lightbox <img> once ready — but only if the lightbox is still
// open and still showing that same painting (guards against stale loads
// from quick prev/next stepping).
function loadHiRes(p, index, token) {
  if (!p.hires) return;

  const hiRes = new Image();
  hiRes.onload = () => {
    if (token !== lightboxToken || index !== currentIndex) return;
    if (!document.getElementById('lightbox').classList.contains('open')) return;
    document.getElementById('lb-img').src = 'pictures/' + encodeURI(p.hires);
  };
  hiRes.src = 'pictures/' + encodeURI(p.hires);
}

function preloadNeighbors() {
  [currentIndex - 1, currentIndex + 1].forEach(i => {
    const p = paintings[wrapIndex(i)];
    if (p) new Image().src = 'pictures/' + encodeURI(p.file);
  });
}

document.addEventListener('keydown', e => {
  if (!document.getElementById('lightbox').classList.contains('open')) return;
  if (e.key === 'ArrowLeft') showPrev();
  else if (e.key === 'ArrowRight') showNext();
});

document.addEventListener('touchstart', e => {
  if (!document.getElementById('lightbox').classList.contains('open')) return;
  touchStartX = e.changedTouches[0].clientX;
});

document.addEventListener('touchend', e => {
  if (touchStartX === null || !document.getElementById('lightbox').classList.contains('open')) {
    touchStartX = null;
    return;
  }
  const dx = e.changedTouches[0].clientX - touchStartX;
  const SWIPE_THRESHOLD = 40;
  if (dx > SWIPE_THRESHOLD) showPrev();
  else if (dx < -SWIPE_THRESHOLD) showNext();
  touchStartX = null;
});

function escapeHtml(str) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return String(str).replace(/[&<>"']/g, c => map[c]);
}
