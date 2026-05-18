/**
 * Shared normalized board coordinates (0–1 relative to drawable area).
 * x=0 left, x=1 right; y=0 top, y=1 bottom — same on every device.
 */

/** Legacy virtual board size (for migrating old room history). */
export const LEGACY_VIRTUAL_WIDTH = 1400;
export const LEGACY_VIRTUAL_HEIGHT = 900;

export function clamp01(value) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.min(1, Math.max(0, value));
}

export function screenToNormalized(screenX, screenY, rect) {
  const w = rect.width > 0 ? rect.width : 1;
  const h = rect.height > 0 ? rect.height : 1;
  return {
    x: clamp01(screenX / w),
    y: clamp01(screenY / h),
  };
}

export function normalizedToScreen(normX, normY, rect) {
  const w = rect.width > 0 ? rect.width : 1;
  const h = rect.height > 0 ? rect.height : 1;
  return {
    x: clamp01(normX) * w,
    y: clamp01(normY) * h,
  };
}

/** Accept 0–1 normalized points or legacy virtual / pixel coordinates from history. */
export function pointToNormalized(point) {
  let x = Number(point.x);
  let y = Number(point.y);
  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    return { x: 0, y: 0 };
  }
  if (x >= 0 && x <= 1 && y >= 0 && y <= 1) {
    return { x, y };
  }
  if (x > 1 || y > 1) {
    return {
      x: clamp01(x / LEGACY_VIRTUAL_WIDTH),
      y: clamp01(y / LEGACY_VIRTUAL_HEIGHT),
    };
  }
  return { x: clamp01(x), y: clamp01(y) };
}

export function strokePointsToScreen(stroke, rect) {
  const points = stroke.points || [];
  return points.map((p) => {
    const norm = pointToNormalized(p);
    return {
      ...p,
      ...normalizedToScreen(norm.x, norm.y, rect),
    };
  });
}

/**
 * Scale protocol brush width (0.5–50 px on virtual board) to local screen pixels.
 * Width is NOT normalized on the wire — only point x/y use 0–1.
 */
export function strokeWidthToScreen(width, rect) {
  const w = rect.width > 0 ? rect.width : 1;
  const raw = Number(width);
  if (!Number.isFinite(raw)) {
    return 4;
  }
  if (raw > 0 && raw <= 1) {
    return raw * w;
  }
  return (raw / LEGACY_VIRTUAL_WIDTH) * w;
}

/** Normalize only point coordinates for sync; keep width in protocol range. */
export function normalizeStrokePoints(stroke) {
  const points = (stroke.points || []).map((p) => {
    const norm = pointToNormalized(p);
    return { ...p, x: norm.x, y: norm.y };
  });
  return { ...stroke, points };
}
