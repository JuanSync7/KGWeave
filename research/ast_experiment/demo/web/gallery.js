// KGWeave AST demo — SA5 use-case gallery.
//
// Renders a grid of rule-family cards from ../data/gallery.json. Each
// card has a title, blurb, and one or more "Run this" buttons that
// dispatch to the host bridge (same shape as tour.js):
//
//   host.selectFile(fileId)
//   host.runCannedQuery(canned)
//   host.runFreeform(text)
//
// Public exports:
//   loadGallery(url)          — fetch spec; resolves to the gallery object
//   renderGallery(container, host, gallery?)
//                              — populate the container with cards; if no
//                                gallery object is passed, loads it first.
//   openGallery(host)         — show the overlay grid; on first call
//                                lazy-loads the spec.

export const galleryState = {
  spec: null,
  rootEl: null,    // overlay element
  hostBridge: null,
};

export async function loadGallery(url = "../data/gallery.json") {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`failed to fetch gallery.json: ${r.status}`);
  const spec = await r.json();
  galleryState.spec = spec;
  return spec;
}

function ensureOverlay() {
  if (galleryState.rootEl) return galleryState.rootEl;
  const overlay = document.createElement("div");
  overlay.className = "gallery-overlay";
  overlay.id = "gallery-overlay";
  overlay.addEventListener("click", (ev) => {
    if (ev.target === overlay) closeGallery();
  });
  const panel = document.createElement("div");
  panel.className = "gallery-panel";
  panel.id = "gallery-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");

  const header = document.createElement("header");
  const title = document.createElement("h2");
  title.textContent = "Use-case gallery";
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "gallery-close";
  closeBtn.textContent = "Close";
  closeBtn.setAttribute("aria-label", "Close gallery");
  closeBtn.addEventListener("click", () => closeGallery());
  header.append(title, closeBtn);

  const grid = document.createElement("div");
  grid.className = "gallery-grid";
  grid.id = "gallery-grid";

  panel.append(header, grid);
  overlay.appendChild(panel);
  document.body.appendChild(overlay);
  galleryState.rootEl = overlay;
  return overlay;
}

export function renderGallery(container, host, gallery) {
  const spec = gallery || galleryState.spec;
  if (!spec || !container) return;
  galleryState.hostBridge = host || galleryState.hostBridge;
  container.innerHTML = "";
  for (const fam of spec.families || []) {
    const card = document.createElement("article");
    card.className = "gallery-card";
    card.dataset.family = fam.family;

    const h = document.createElement("h3");
    h.textContent = fam.title;
    const p = document.createElement("p");
    p.textContent = fam.description || "";

    const exList = document.createElement("ul");
    exList.className = "gallery-examples";
    for (const ex of fam.examples || []) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "gallery-run";
      btn.textContent = ex.label;
      btn.title = ex.canned
        ? `canned: ${ex.canned}`
        : (ex.freeform ? `freeform: ${ex.freeform}` : "");
      btn.addEventListener("click", () => runExample(ex));
      li.appendChild(btn);
      exList.appendChild(li);
    }

    card.append(h, p, exList);
    container.appendChild(card);
  }
}

function runExample(ex) {
  const host = galleryState.hostBridge;
  if (!host) return;
  try { host.clearQuery && host.clearQuery(); } catch (_) { /* */ }
  if (ex.file && host.selectFile) {
    try { host.selectFile(ex.file); } catch (_) { /* */ }
  }
  if (ex.canned && host.runCannedQuery) {
    try { host.runCannedQuery(ex.canned); } catch (_) { /* */ }
  } else if (ex.freeform && host.runFreeform) {
    try { host.runFreeform(ex.freeform); } catch (_) { /* */ }
  }
  // Closing the gallery lets the user see the resulting animation.
  closeGallery();
}

export async function openGallery(host) {
  galleryState.hostBridge = host || galleryState.hostBridge;
  if (!galleryState.spec) {
    try { await loadGallery(); } catch (e) {
      console.error("gallery: failed to load spec", e);
      return;
    }
  }
  ensureOverlay();
  const grid = galleryState.rootEl.querySelector("#gallery-grid");
  renderGallery(grid, galleryState.hostBridge, galleryState.spec);
  galleryState.rootEl.classList.add("visible");
}

export function closeGallery() {
  if (galleryState.rootEl) galleryState.rootEl.classList.remove("visible");
}
