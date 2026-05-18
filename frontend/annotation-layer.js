/**
 * Overlays text / KaTeX formula annotations (canvas coordinates, CSS px).
 * Server enforces content limits and XSS-oriented substring bans; UI still uses textContent / KaTeX only.
 */

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

    div.style.left = `${Number(payload.x)}px`;
    div.style.top = `${Number(payload.y)}px`;
    div.style.fontSize = `${Number(payload.font_size)}px`;
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
}
