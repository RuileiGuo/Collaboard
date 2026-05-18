/**
 * Overlays text / KaTeX formula annotations (virtual board coordinates).
 * Server enforces content limits and XSS-oriented substring bans; UI still uses textContent / KaTeX only.
 */

import { clamp01, pointToNormalized } from "./board-coords.js";

export class AnnotationLayer {
  constructor(containerEl) {
    this.container = containerEl;
    this.byId = new Map();
  }

  clear() {
    this.container.innerHTML = "";
    this.byId.clear();
  }

  removeById(id) {
    if (!id) {
      return;
    }
    const el = this.byId.get(id);
    if (el) {
      el.remove();
      this.byId.delete(id);
    }
  }

  addFromPayload(payload, currentUserId = "") {
    const id = payload.annotation_id;
    if (!id || this.byId.has(id)) {
      return;
    }
    const div = document.createElement("div");
    div.className = "board-annotation";
    div.dataset.annotationId = id;

    const authorUserId = String(payload.user_id || "");
    if (authorUserId) {
      div.dataset.authorUserId = authorUserId;
    }
    if (authorUserId && currentUserId && authorUserId === currentUserId) {
      div.classList.add("board-annotation--mine");
      div.title = "Click to delete your annotation";
    } else if (authorUserId) {
      div.classList.add("board-annotation--remote");
      div.title = "Click to request deletion from the author";
    }

    const norm = pointToNormalized(payload);
    const vfs = Number(payload.font_size);
    div.dataset.normX = String(norm.x);
    div.dataset.normY = String(norm.y);
    div.dataset.fontSize = String(vfs);
    this._applyLayout(div, norm.x, norm.y, vfs);
    div.style.color = payload.color || "#111111";
    const mode = payload.mode || "text";
    const content = String(payload.content ?? "");
    if (mode === "formula" && typeof window.katex !== "undefined") {
      try {
        window.katex.render(content, div, { throwOnError: false, displayMode: false });
      } catch {
        div.textContent = content;
      }
    } else {
      div.textContent = content;
    }
    this.container.appendChild(div);
    this.byId.set(id, div);
  }

  _applyLayout(el, normX, normY, fontSize) {
    const rect = this.container.getBoundingClientRect();
    const h = rect.height > 0 ? rect.height : 1;
    el.style.left = `${clamp01(normX) * 100}%`;
    el.style.top = `${clamp01(normY) * 100}%`;
    const fs = Number(fontSize);
    if (Number.isFinite(fs)) {
      if (fs > 0 && fs <= 1) {
        el.style.fontSize = `${fs * h}px`;
      } else {
        el.style.fontSize = `${Math.min(72, Math.max(8, (fs / 900) * h))}px`;
      }
    }
  }

  /** Re-position all annotations after board resize (normalized 0–1 coords). */
  relayout() {
    for (const el of this.byId.values()) {
      const nx = Number(el.dataset.normX ?? el.dataset.virtualX);
      const ny = Number(el.dataset.normY ?? el.dataset.virtualY);
      const vfs = Number(el.dataset.fontSize ?? el.dataset.virtualFontSize);
      if (Number.isFinite(nx) && Number.isFinite(ny)) {
        const norm = pointToNormalized({ x: nx, y: ny });
        this._applyLayout(el, norm.x, norm.y, vfs);
      }
    }
  }
}
