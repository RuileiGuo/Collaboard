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

  resize() {
    const rect = this.canvas.getBoundingClientRect();
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
    this.strokes.push(stroke);
    this.drawStroke(stroke);
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
    this.strokes.push(stroke);
  }

  drawStroke(stroke) {
    const points = stroke.points || [];
    if (!points.length) {
      return;
    }
    const ctx = this.ctx;
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = stroke.width || 4;
    ctx.strokeStyle = stroke.tool === "eraser" ? "#ffffff" : stroke.color || "#111111";
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (const point of points.slice(1)) {
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
        byId.set(sid, payload);
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
