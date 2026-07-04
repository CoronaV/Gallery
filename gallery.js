/*
 * gallery.js — builds the gallery from pictures/manifest.json.
 *
 * A plain webpage can't list the files in a folder on its own (browsers
 * block that for security reasons), so pictures/manifest.json holds the
 * list instead. Run `python3 generate_manifest.py` any time you add,
 * remove, or re-caption a painting, then refresh the page.
 *
 * IMPORTANT: fetch() of local files is blocked under file://. Serve this
 * folder over http:// — even just `python3 -m http.server` run inside it,
 * then open http://localhost:8000/ — or upload it to any static host.
 */

let paintings = [];

async function loadGallery() {
  const galleryEl = document.getElementById('gallery');

  try {
    const res = await fetch('pictures/manifest.json', { cache: 'no-store' });
    if (!res.ok) throw new Error('manifest.json not found (' + res.status + ')');
    paintings = await res.json();
  } catch (err) {
    galleryEl.innerHTML =
      '<p class="gallery-status">Couldn\u2019t load the picture list. ' +
      'Run <code>python3 generate_manifest.py</code> after adding images, and make ' +
      'sure this page is served over http:// (not opened directly as a file) \u2014 ' +
      'e.g. run <code>python3 -m http.server</code> in this folder.</p>';
    console.error('Gallery load failed:', err);
    return;
  }

  if (!paintings.length) {
    galleryEl.innerHTML = '<p class="gallery-status">No paintings in pictures/ yet.</p>';
    return;
  }

  galleryEl.innerHTML = '';
  paintings.forEach((p, i) => {
    const card = document.createElement('div');
    card.className = 'painting';
    card.style.animationDelay = (Math.min(i, 8) * 0.08) + 's';
    card.addEventListener('click', () => openLightbox(i));

    const title = p.title || 'Unnamed';

    card.innerHTML =
      '<div class="painting-frame">' +
        '<img src="pictures/' + encodeURI(p.file) + '" alt="' + escapeHtml(title) + '" loading="lazy" />' +
      '</div>' +
      '<div class="painting-info">' +
        '<div class="painting-title">' + escapeHtml(title) + '</div>' +
        '<div class="painting-meta">' + escapeHtml(p.meta || '') + '</div>' +
      '</div>';

    galleryEl.appendChild(card);
  });
}

function openLightbox(i) {
  const p = paintings[i];
  const title = p.title || 'Unnamed';

  document.getElementById('lb-img').src = 'pictures/' + encodeURI(p.file);
  document.getElementById('lb-img').alt = title;
  document.getElementById('lb-title').textContent = title;
  document.getElementById('lb-meta').textContent = p.meta || '';
  document.getElementById('lb-desc').textContent = p.description || '';
  document.getElementById('lightbox').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function escapeHtml(str) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return String(str).replace(/[&<>"']/g, c => map[c]);
}
