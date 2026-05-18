import {
  normalizeStrokePoints,
  normalizedToScreen,
  pointToNormalized,
  strokePointsToScreen,
  strokeWidthToScreen,
} from "./board-coords.js";

export class CanvasBoard {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.strokes = [];
    this.pixelRatio = window.devicePixelRatio || 1;
    this.cssWidth = 0;
    this.cssHeight = 0;
    this.resize();
    this.clear();
  }

  getBoardRect() {
    const stack = this.canvas.parentElement;
    const rect = (stack || this.canvas).getBoundingClientRect();
    return {
      width: rect.width > 0 ? rect.width : 1,
      height: rect.height > 0 ? rect.height : 1,
    };
  }

  resize() {
    const rect = this.getBoardRect();
    this.pixelRatio = window.devicePixelRatio || 1;
    this.cssWidth = rect.width;
    this.cssHeight = rect.height;
    this.canvas.width = Math.round(rect.width * this.pixelRatio);
    this.canvas.height = Math.round(rect.height * this.pixelRatio);
    this.ctx.setTransform(this.pixelRatio, 0, 0, this.pixelRatio, 0, 0);
    this.redraw();
  }

  clear() {
    this.ctx.save();
    this.ctx.setTransform(1, 0, 0, 1, 0, 0);
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this.ctx.restore();
    this.ctx.save();
    this.ctx.setTransform(this.pixelRatio, 0, 0, this.pixelRatio, 0, 0);
    this.ctx.fillStyle = "#ffffff";
    this.ctx.fillRect(0, 0, this.cssWidth, this.cssHeight);
    this.ctx.restore();
  }

  addStroke(stroke) {
    const normalized = normalizeStrokePoints(stroke);
    this.strokes.push(normalized);
    this.drawStroke(normalized);
  }

  removeStrokeById(strokeId) {
    const i = this.strokes.findIndex((s) => s.stroke_id === strokeId);
    if (i >= 0) {
      this.strokes.splice(i, 1);
      this.redraw();
    }
  }

  /** Record stroke for redraw without painting (optimistic pixels already on canvas). */
  recordStroke(stroke) {
    this.strokes.push(normalizeStrokePoints(stroke));
  }

  /** Draw one segment (normalized coords) without full redraw — for live preview. */
  drawSegment(prevPoint, nextPoint, strokeStyle) {
    const rect = this.getBoardRect();
    const a = pointToNormalized(prevPoint);
    const b = pointToNormalized(nextPoint);
    const p0 = normalizedToScreen(a.x, a.y, rect);
    const p1 = normalizedToScreen(b.x, b.y, rect);
    const ctx = this.ctx;
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = strokeWidthToScreen(strokeStyle.width, rect);
    ctx.strokeStyle = strokeStyle.tool === "eraser" ? "#ffffff" : strokeStyle.color || "#111111";
    ctx.beginPath();
    ctx.moveTo(p0.x, p0.y);
    ctx.lineTo(p1.x, p1.y);
    ctx.stroke();
    ctx.restore();
  }

  drawStroke(stroke) {
    const points = stroke.points || [];
    if (!points.length) {
      return;
    }
    const rect = this.getBoardRect();
    const screenPoints = strokePointsToScreen(stroke, rect);
    const ctx = this.ctx;
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = strokeWidthToScreen(stroke.width, rect);
    ctx.strokeStyle = stroke.tool === "eraser" ? "#ffffff" : stroke.color || "#111111";
    ctx.beginPath();
    ctx.moveTo(screenPoints[0].x, screenPoints[0].y);
    for (const point of screenPoints.slice(1)) {
      ctx.lineTo(point.x, point.y);
    }
    ctx.stroke();
    ctx.restore();
  }

  redraw() {
    this.clear();
    for (const stroke of this.strokes) {
      this.drawStroke(stroke);
    }
    this.ctx.save();
    this.ctx.strokeStyle = "rgba(15, 23, 42, 0.08)";
    this.ctx.strokeRect(0.5, 0.5, this.cssWidth - 1, this.cssHeight - 1);
    this.ctx.restore();
  }

  syncFromEvents(events) {
    const order = [];
    const byId = new Map();
    for (const event of events || []) {
      const payload = event?.payload || {};
      const type = payload.event_type;
      if (type === "draw") {
        const sid = payload.stroke_id;
        if (!byId.has(sid)) {
          order.push(sid);
        }
        byId.set(sid, normalizeStrokePoints(payload));
      } else if (type === "stroke_undone") {
        const sid = payload.stroke_id;
        byId.delete(sid);
        const idx = order.indexOf(sid);
        if (idx >= 0) {
          order.splice(idx, 1);
        }
      } else if (type === "clear") {
        byId.clear();
        order.length = 0;
      }
    }
    this.strokes = order.map((id) => byId.get(id)).filter(Boolean);
    this.redraw();
  }
}
