import { AnnotationLayer } from "./annotation-layer.js";
import { CanvasBoard } from "./canvas.js";
import { AppState } from "./state.js";
import {
  buildAnnotation,
  buildAnnotationDelete,
  buildAnnotationRestore,
  buildClearPropose,
  buildClearVote,
  buildDraw,
  buildDrawRedo,
  buildDrawUndo,
  buildJoin,
  buildLeave,
  buildStateSync,
  isAck,
  isBroadcast,
  isError,
} from "./protocol.js";

const state = new AppState();

const els = {
  serverUrl: document.getElementById("server-url"),
  connectionId: document.getElementById("connection-id"),
  roomId: document.getElementById("room-id"),
  userId: document.getElementById("user-id"),
  userName: document.getElementById("user-name"),
  joinBtn: document.getElementById("join-btn"),
  leaveBtn: document.getElementById("leave-btn"),
  syncBtn: document.getElementById("sync-btn"),
  brushSize: document.getElementById("brush-size"),
  brushColor: document.getElementById("brush-color"),
  userList: document.getElementById("user-list"),
  eventLog: document.getElementById("event-log"),
  board: document.getElementById("board"),
  errorText: document.getElementById("error-text"),
  serverStatus: document.getElementById("server-status"),
  connectionPill: document.getElementById("connection-pill"),
  sequenceText: document.getElementById("sequence-text"),
  roomStateText: document.getElementById("room-state-text"),
  boardStack: document.getElementById("board-stack"),
  annotationLayer: document.getElementById("annotation-layer"),
  clearVoteModal: document.getElementById("clear-vote-modal"),
  clearVoteSummary: document.getElementById("clear-vote-summary"),
  clearVoteApprove: document.getElementById("clear-vote-approve"),
  clearVoteReject: document.getElementById("clear-vote-reject"),
  clearProposeBtn: document.getElementById("clear-propose-btn"),
  undoBtn: document.getElementById("undo-btn"),
  redoBtn: document.getElementById("redo-btn"),
  leaveReportModal: document.getElementById("leave-report-modal"),
  leaveReportBody: document.getElementById("leave-report-body"),
  leaveReportClose: document.getElementById("leave-report-close"),
};

const annotations = new AnnotationLayer(els.annotationLayer);
const board = new CanvasBoard(els.board);
let drawing = false;
let currentStroke = null;
let reconnectTimer = null;
let pendingReconnect = false;

function setStatus(text, kind = "") {
  els.serverStatus.textContent = text;
  els.connectionPill.textContent = state.connected ? "connected" : "disconnected";
  els.connectionPill.className = `pill ${kind}`.trim();
}

function setError(text) {
  els.errorText.textContent = text;
}

function addEvent(text) {
  const row = document.createElement("div");
  row.textContent = text;
  els.eventLog.prepend(row);
  while (els.eventLog.childElementCount > 8) {
    els.eventLog.lastElementChild?.remove();
  }
}

function resolveActorName(message, payload) {
  const uid = message.user_id;
  const fromPayload = payload.user_name;
  if (fromPayload) {
    return fromPayload;
  }
  if (uid === "server") {
    return "服务器";
  }
  if (uid === state.userId) {
    return state.userName || state.userId;
  }
  const member = state.activeUsers.find((u) => u.user_id === uid);
  if (member) {
    return member.user_name || member.user_id;
  }
  return uid || "未知";
}

function formatBroadcastLogLine(message) {
  const payload = message.payload || {};
  const who = resolveActorName(message, payload);
  const seq = message.sequence_id;
  switch (payload.event_type) {
    case "draw":
      return `${who} 绘制了一笔（${payload.tool || "pen"}） #${seq}`;
    case "annotation":
      return `${who} 添加了${payload.mode === "formula" ? "公式" : "文字"}标注 #${seq}`;
    case "annotation_removed":
      return `${who} 删除了标注 #${seq}`;
    case "stroke_undone":
      return `${who} 撤销了一笔绘制 #${seq}`;
    case "clear":
      return `${who} 清空了画布${payload.consensus ? "（已表决）" : ""} #${seq}`;
    case "clear_propose":
      return `${payload.proposer_name || who} 发起清空表决 #${seq}`;
    case "clear_rejected":
      return `${payload.rejector_name || payload.rejector_id} 拒绝清空 #${seq}`;
    case "clear_proposal_cancelled":
      return `清空表决已取消（${payload.reason || "unknown"}） #${seq}`;
    case "clear_proposal_expired":
      return `清空表决已超时 #${seq}`;
    case "user_joined":
      return `${payload.user_name || payload.user_id || who} 加入房间 #${seq}`;
    case "user_left":
      return `${payload.user_name || who} 离开房间 #${seq}`;
    case "room_idle":
      return `房间已空，进入空闲（TTL ${payload.ttl_seconds ?? "?"}s） #${seq}`;
    default:
      return `${who} · ${payload.event_type || "broadcast"} #${seq}`;
  }
}

function resyncAnnotationsFromHistory(events) {
  annotations.clear();
  for (const ev of events || []) {
    const p = ev?.payload || {};
    if (p.event_type === "annotation") {
      const author = ev.user_id || p.user_id || "";
      annotations.addFromPayload(p, author === state.userId ? state.userId : "");
    } else if (p.event_type === "annotation_removed") {
      annotations.removeById(p.annotation_id);
    }
  }
}

function openClearVoteModal() {
  const p = state.pendingClearProposal;
  if (!p) {
    return;
  }
  els.clearVoteSummary.textContent = `${p.proposer_name} 请求清空画布。截止时间：${new Date(p.expires_ms).toLocaleString()}。`;
  els.clearVoteModal.classList.remove("hidden");
}

function closeClearVoteModal() {
  els.clearVoteModal.classList.add("hidden");
  state.pendingClearProposal = null;
}

function resetSessionStats() {
  state.sessionStats = {
    roomJoinedAt: 0,
    draws: 0,
    eraserStrokes: 0,
    annotationsText: 0,
    annotationsFormula: 0,
    annotationDeletes: 0,
    annotationRestores: 0,
    drawUndos: 0,
    drawRedos: 0,
    clearProposals: 0,
    clearVotesApprove: 0,
    clearVotesReject: 0,
    stateSyncs: 0,
  };
}

function formatDuration(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h > 0) {
    return `${h} 小时 ${m % 60} 分 ${s % 60} 秒`;
  }
  if (m > 0) {
    return `${m} 分 ${s % 60} 秒`;
  }
  return `${s} 秒`;
}

function recordSessionAckPayload(payload) {
  if (!payload || payload.status !== "ok" || payload.room_state) {
    return;
  }
  const op = payload.op;
  if (op === "draw" && payload.stroke_id) {
    if (payload.tool === "eraser") {
      state.sessionStats.eraserStrokes += 1;
    } else {
      state.sessionStats.draws += 1;
    }
  } else if (op === "annotation") {
    if (payload.mode === "formula") {
      state.sessionStats.annotationsFormula += 1;
    } else {
      state.sessionStats.annotationsText += 1;
    }
  } else if (op === "annotation_delete") {
    state.sessionStats.annotationDeletes += 1;
  } else if (op === "annotation_restore") {
    state.sessionStats.annotationRestores += 1;
  } else if (op === "draw_undo") {
    state.sessionStats.drawUndos += 1;
  } else if (op === "draw_redo") {
    state.sessionStats.drawRedos += 1;
  } else if (payload.proposal_id != null && payload.expires_ms != null) {
    state.sessionStats.clearProposals += 1;
  } else if (payload.cleared === true && payload.reason === "single_member_room") {
    state.sessionStats.clearProposals += 1;
  } else if (payload.vote === "approve") {
    state.sessionStats.clearVotesApprove += 1;
  } else if (payload.vote === "reject") {
    state.sessionStats.clearVotesReject += 1;
  }
}

function showLeaveReportModal(stats, durationMs, roomLabel) {
  if (!els.leaveReportBody || !els.leaveReportModal) {
    return;
  }
  const totalAnnot = stats.annotationsText + stats.annotationsFormula;
  const lines = [
    `房间：${roomLabel || "—"}`,
    `停留时长：${formatDuration(durationMs)}`,
    `绘制：笔划 ${stats.draws}，橡皮 ${stats.eraserStrokes}`,
    `标注：文字 ${stats.annotationsText}，公式 ${stats.annotationsFormula}（合计 ${totalAnnot}）`,
    `删除标注 ${stats.annotationDeletes} 次，恢复标注 ${stats.annotationRestores} 次`,
    `撤销绘制 ${stats.drawUndos} 次，恢复绘制 ${stats.drawRedos} 次`,
    `清空表决：发起 ${stats.clearProposals}，同意票 ${stats.clearVotesApprove}，拒绝 ${stats.clearVotesReject}`,
    `手动同步 ${stats.stateSyncs} 次`,
  ];
  els.leaveReportBody.replaceChildren(
    ...lines.map((line) => {
      const p = document.createElement("p");
      p.textContent = line;
      return p;
    }),
  );
  els.leaveReportModal.classList.remove("hidden");
}

function closeLeaveReportModal() {
  els.leaveReportModal?.classList.add("hidden");
}

function updateBoardInteractionClass() {
  els.boardStack.classList.remove("mode-text", "mode-formula");
  if (state.activeTool === "text") {
    els.boardStack.classList.add("mode-text");
  }
  if (state.activeTool === "formula") {
    els.boardStack.classList.add("mode-formula");
  }
}

function proposeClearCanvas() {
  if (!state.joined) {
    setError("先加入房间。");
    return;
  }
  const note = window.prompt("申请清空画布（将请求房间内所有人同意）。可选说明：", "") ?? "";
  try {
    send(buildClearPropose(state, note));
  } catch (error) {
    setError(String(error.message || error));
  }
}

function placeAnnotationAt(point) {
  const mode = state.activeTool === "formula" ? "formula" : "text";
  const label = mode === "formula" ? "输入 LaTeX（如 E=mc^2 或 \\frac{a}{b}）" : "输入文字";
  const raw = window.prompt(label, "");
  if (raw == null || String(raw).trim() === "") {
    return;
  }
  const fs = Math.min(72, Math.max(8, Number(state.brushSize) * 3));
  try {
    send(
      buildAnnotation(state, {
        annotation_id: crypto.randomUUID(),
        mode,
        content: String(raw).trim(),
        x: point.x,
        y: point.y,
        font_size: fs,
        color: state.color,
      }),
    );
  } catch (error) {
    setError(String(error.message || error));
  }
}

function renderUsers(users) {
  els.userList.innerHTML = "";
  for (const user of users || []) {
    const chip = document.createElement("div");
    chip.className = "user-chip";
    chip.textContent = user.user_name || user.user_id;
    els.userList.appendChild(chip);
  }
}

function updateRoomMeta() {
  els.sequenceText.textContent = `sequence: ${state.currentSequence}`;
  els.roomStateText.textContent = `room state: ${state.roomState}`;
}

function socketUrlForConnection() {
  const base = els.serverUrl.value.replace(/\/ws\/?$/, "").replace(/\/$/, "");
  return `${base}/ws/${encodeURIComponent(state.connectionId)}`;
}

function send(message) {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
    throw new Error("WebSocket is not open");
  }
  state.socket.send(JSON.stringify(message));
}

function connect() {
  if (!state.connectionId || !state.roomId || !state.userId) {
    setError("Connection ID, Room ID, and User ID are required.");
    return;
  }
  disconnect(false);
  const url = socketUrlForConnection();
  state.socket = new WebSocket(url);
  state.socket.onopen = () => {
    state.connected = true;
    setStatus(`Connected to ${url}`, "connected");
    setError("Connected.");
    send(buildJoin(state));
  };
  state.socket.onmessage = (event) => {
    try {
      handleMessage(JSON.parse(event.data));
    } catch (error) {
      setError(`Bad server message: ${String(error.message || error)}`);
    }
  };
  state.socket.onerror = () => {
    setError("Socket error.");
    setStatus("Socket error", "error");
  };
  state.socket.onclose = () => {
    const shouldReconnect = state.joined && pendingReconnect;
    state.connected = false;
    state.socket = null;
    setStatus("Disconnected.", "");
    if (shouldReconnect) {
      scheduleReconnect();
    }
  };
}

function disconnect(manual = true) {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (state.socket && state.socket.readyState === WebSocket.OPEN && manual && state.joined) {
    try {
      send(buildLeave(state, "manual"));
    } catch {}
  }
  state.socket?.close();
  state.socket = null;
  state.connected = false;
  if (manual) {
    state.joined = false;
    pendingReconnect = false;
  }
  updateRoomMeta();
}

function scheduleReconnect() {
  if (reconnectTimer) {
    return;
  }
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 1500);
}

function performUndo() {
  if (!state.joined || !state.connected) {
    setError("加入房间后可撤销本人上一笔或恢复刚删标注。");
    return;
  }
  const entry = state.undoStack.pop();
  if (!entry) {
    setError("没有可撤销的操作。");
    return;
  }
  state.pendingUndoEntry = entry;
  try {
    if (entry.kind === "draw") {
      send(buildDrawUndo(state, entry.strokeId));
    } else {
      send(buildAnnotationRestore(state, entry.annotationId));
    }
  } catch (error) {
    state.undoStack.push(entry);
    state.pendingUndoEntry = null;
    setError(String(error.message || error));
  }
}

function performRedo() {
  if (!state.joined || !state.connected) {
    setError("加入房间后可恢复上一步撤销（Ctrl+Y）。");
    return;
  }
  const entry = state.redoStack.pop();
  if (!entry) {
    setError("没有可恢复的操作。");
    return;
  }
  state.pendingRedoEntry = entry;
  try {
    if (entry.kind === "draw") {
      send(buildDrawRedo(state, entry.strokeId));
    } else {
      send(buildAnnotationDelete(state, entry.annotationId));
    }
  } catch (error) {
    state.redoStack.push(entry);
    state.pendingRedoEntry = null;
    setError(String(error.message || error));
  }
}

function handleMessage(message) {
  if (isError(message)) {
    if (state.pendingUndoEntry) {
      state.undoStack.push(state.pendingUndoEntry);
      state.pendingUndoEntry = null;
    }
    if (state.pendingRedoEntry) {
      state.redoStack.push(state.pendingRedoEntry);
      state.pendingRedoEntry = null;
    }
    const code = message.payload?.error_code || "ERROR";
    const hint =
      code === "RATE_LIMIT"
        ? "（建议稍后重试或降低发送频率；协议要求指数退避。）"
        : "";
    setError(`${code}: ${message.payload?.message || "unknown"}${hint}`);
    addEvent(`error ${code}`.trim());
    if (code === "ROOM_NOT_FOUND") {
      pendingReconnect = false;
      disconnect(false);
      state.joined = false;
      refreshJoinedControls();
      setStatus("房间不存在或已销毁。", "error");
    }
    if (code === "CLEAR_PROPOSAL_ACTIVE") {
      setError("已有进行中的清空表决，请等待结束后再申请。");
    }
    const rollbackCanvas = ["INVALID_MESSAGE", "UNAUTHORIZED", "RATE_LIMIT"].includes(code);
    if (rollbackCanvas && state.optimisticStrokeIds.size) {
      state.optimisticStrokeIds.clear();
      board.redraw();
    }
    return;
  }
  if (isAck(message)) {
    if (state.pendingUndoEntry && (message.payload?.op === "draw_undo" || message.payload?.op === "annotation_restore")) {
      state.pendingUndoEntry = null;
    }
    let completedRedo = false;
    if (state.pendingRedoEntry && (message.payload?.op === "draw_redo" || message.payload?.op === "annotation_delete")) {
      state.pendingRedoEntry = null;
      completedRedo = true;
    }
    if (Number.isFinite(message.sequence_id)) {
      state.currentSequence = message.sequence_id;
    }
    if (message.payload?.room_state) {
      const roomState = message.payload.room_state;
      const isJoinSnapshot = message.payload?.reason === "joined";
      state.roomState = "active";
      state.currentSequence = roomState.current_sequence ?? state.currentSequence;
      if (isJoinSnapshot) {
        resetSessionStats();
        state.sessionStats.roomJoinedAt = Date.now();
        state.undoStack = [];
        state.redoStack = [];
        state.pendingUndoEntry = null;
        state.pendingRedoEntry = null;
        state.lastReceivedSequence = roomState.current_sequence ?? state.lastReceivedSequence;
        state.joined = true;
        state.activeUsers = roomState.active_users || [];
        renderUsers(state.activeUsers);
        const history = roomState.canvas_history ?? roomState.canvas_events ?? [];
        board.syncFromEvents(history);
        resyncAnnotationsFromHistory(history);
      } else {
        state.sessionStats.stateSyncs += 1;
        state.activeUsers = roomState.active_users || state.activeUsers;
        renderUsers(state.activeUsers);
        const deltas = roomState.canvas_events || [];
        for (const ev of deltas) {
          enqueueBroadcast(ev);
        }
        flushBroadcastQueue();
        state.currentSequence = roomState.current_sequence ?? state.currentSequence;
      }
    } else if (message.payload?.status === "ok" && message.payload?.reason === "joined") {
      state.joined = true;
    } else if (message.payload?.status === "ok" && !message.payload?.room_state) {
      const op = message.payload?.op;
      const p = message.payload;
      if (op === "draw" && p.stroke_id) {
        state.redoStack = [];
        state.undoStack.push({ kind: "draw", strokeId: p.stroke_id });
      } else if (op === "annotation") {
        state.redoStack = [];
      } else if (op === "annotation_delete" && p.annotation_id) {
        if (!completedRedo) {
          state.redoStack = [];
        }
        state.undoStack.push({ kind: "annotation", annotationId: p.annotation_id });
      } else if (op === "draw_redo" && p.stroke_id) {
        state.undoStack.push({ kind: "draw", strokeId: p.stroke_id });
      } else if (op === "draw_undo" && p.stroke_id) {
        state.redoStack.push({ kind: "draw", strokeId: p.stroke_id });
      } else if (op === "annotation_restore" && p.annotation_id) {
        state.redoStack.push({ kind: "annotation", annotationId: p.annotation_id });
      }
      recordSessionAckPayload(p);
    }
    updateRoomMeta();
    refreshJoinedControls();
    addEvent(`ack ${message.msg_id}`);
    return;
  }
  if (isBroadcast(message)) {
    enqueueBroadcast(message);
    return;
  }
  addEvent(`message ${message.type || "unknown"}`);
}

function enqueueBroadcast(message) {
  state.orderedBroadcasts.push(message);
  state.orderedBroadcasts.sort((a, b) => a.sequence_id - b.sequence_id);
  flushBroadcastQueue();
}

function flushBroadcastQueue() {
  while (state.orderedBroadcasts.length) {
    const next = state.orderedBroadcasts[0];
    const sid = next.sequence_id;
    if (!Number.isFinite(sid)) {
      state.orderedBroadcasts.shift();
      continue;
    }
    if (sid <= state.lastReceivedSequence) {
      state.orderedBroadcasts.shift();
      continue;
    }
    if (state.lastReceivedSequence === -1 && sid !== 0) {
      if (sid > 0) {
        break;
      }
      state.orderedBroadcasts.shift();
      continue;
    }
    if (state.lastReceivedSequence !== -1 && sid !== state.lastReceivedSequence + 1) {
      if (sid > state.lastReceivedSequence + 1) {
        break;
      }
      state.orderedBroadcasts.shift();
      continue;
    }
    state.orderedBroadcasts.shift();
    applyBroadcast(next);
    state.lastReceivedSequence = sid;
    state.currentSequence = Math.max(state.currentSequence, sid);
  }
  updateRoomMeta();
}

function applyBroadcast(message) {
  const payload = message.payload || {};
  const eventType = payload.event_type;
  if (eventType === "annotation") {
    const author = message.user_id || payload.user_id || "";
    annotations.addFromPayload(payload, author === state.userId ? state.userId : "");
  } else if (eventType === "annotation_removed") {
    annotations.removeById(payload.annotation_id);
  } else if (eventType === "draw") {
    const strokeId = payload.stroke_id;
    if (strokeId && state.optimisticStrokeIds.has(strokeId)) {
      state.optimisticStrokeIds.delete(strokeId);
      board.recordStroke(payload);
    } else {
      board.addStroke(payload);
    }
  } else if (eventType === "stroke_undone") {
    state.optimisticStrokeIds.delete(payload.stroke_id);
    board.removeStrokeById(payload.stroke_id);
  } else if (eventType === "clear") {
    board.strokes = [];
    board.clear();
    annotations.clear();
    state.optimisticStrokeIds.clear();
    state.undoStack = [];
    state.redoStack = [];
    state.pendingUndoEntry = null;
    state.pendingRedoEntry = null;
    closeClearVoteModal();
  } else if (eventType === "clear_propose") {
    if (
      payload.proposer_id !== state.userId &&
      Array.isArray(payload.required_voters) &&
      payload.required_voters.includes(state.userId)
    ) {
      state.pendingClearProposal = {
        proposal_id: payload.proposal_id,
        proposer_id: payload.proposer_id,
        proposer_name: payload.proposer_name || payload.proposer_id,
        expires_ms: payload.expires_ms,
        required_voters: payload.required_voters,
      };
      openClearVoteModal();
    }
  } else if (
    eventType === "clear_rejected" ||
    eventType === "clear_proposal_cancelled" ||
    eventType === "clear_proposal_expired"
  ) {
    closeClearVoteModal();
  } else if (eventType === "user_joined" || eventType === "user_left") {
    if (payload.user_id && eventType === "user_joined") {
      state.activeUsers = [
        ...state.activeUsers.filter((u) => u.user_id !== payload.user_id),
        { user_id: payload.user_id, user_name: payload.user_name || payload.user_id },
      ];
    }
    if (payload.user_id && eventType === "user_left") {
      state.activeUsers = state.activeUsers.filter((u) => u.user_id !== payload.user_id);
    }
    renderUsers(state.activeUsers);
    state.roomState = state.activeUsers.length === 0 ? "idle" : "active";
  } else if (eventType === "room_idle") {
    state.roomState = "idle";
  }
  addEvent(formatBroadcastLogLine(message));
}

function joinRoom() {
  state.connectionId = els.connectionId.value.trim() || `conn-${Math.random().toString(16).slice(2, 8)}`;
  state.roomId = els.roomId.value.trim();
  state.userId = els.userId.value.trim();
  state.userName = els.userName.value.trim() || state.userId;
  state.serverUrl = els.serverUrl.value.trim();
  state.color = els.brushColor.value;
  state.brushSize = Number(els.brushSize.value);
  if (!state.roomId || !state.userId) {
    setError("Room ID and User ID are required.");
    return;
  }
  pendingReconnect = true;
  connect();
}

function leaveRoom() {
  const roomLabel = state.roomId;
  const joinedAt = state.sessionStats.roomJoinedAt;
  const durationMs = joinedAt > 0 ? Date.now() - joinedAt : 0;
  const statsSnapshot = { ...state.sessionStats };
  pendingReconnect = false;
  closeClearVoteModal();
  disconnect(true);
  state.joined = false;
  state.undoStack = [];
  state.redoStack = [];
  state.pendingUndoEntry = null;
  state.pendingRedoEntry = null;
  state.optimisticStrokeIds.clear();
  annotations.clear();
  state.roomState = "idle";
  state.activeUsers = [];
  renderUsers([]);
  setStatus("Disconnected.", "");
  updateRoomMeta();
  refreshJoinedControls();
  if (joinedAt > 0) {
    showLeaveReportModal(statsSnapshot, durationMs, roomLabel);
  }
}

function syncRoom() {
  if (!state.connected) {
    setError("Connect first.");
    return;
  }
  send(buildStateSync(state));
}

function pointerPos(event) {
  const rect = els.board.getBoundingClientRect();
  let p = typeof event.pressure === "number" ? event.pressure : 1;
  if (!Number.isFinite(p) || p < 0) {
    p = 1;
  }
  if (p > 1) {
    p = 1;
  }
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
    pressure: p,
  };
}

function beginStroke(event) {
  if (!state.joined) {
    setError("Join a room before drawing.");
    return;
  }
  if (state.activeTool === "text" || state.activeTool === "formula") {
    placeAnnotationAt(pointerPos(event));
    return;
  }
  drawing = true;
  const point = pointerPos(event);
  currentStroke = {
    stroke_id: crypto.randomUUID(),
    tool: state.activeTool,
    color: state.color,
    width: state.brushSize,
    points: [point],
  };
  els.board.setPointerCapture(event.pointerId);
}

function moveStroke(event) {
  if (!drawing || !currentStroke) {
    return;
  }
  const point = pointerPos(event);
  currentStroke.points.push(point);
  board.drawStroke(currentStroke);
}

function endStroke(event) {
  if (!drawing || !currentStroke) {
    return;
  }
  drawing = false;
  const finalStroke = currentStroke;
  currentStroke = null;
  state.optimisticStrokeIds.add(finalStroke.stroke_id);
  try {
    send(buildDraw(state, finalStroke));
  } catch (error) {
    state.optimisticStrokeIds.delete(finalStroke.stroke_id);
    setError(String(error.message || error));
  }
  els.board.releasePointerCapture?.(event.pointerId);
}

function toggleJoinAvailability(isJoined) {
  els.joinBtn.disabled = isJoined;
  els.leaveBtn.disabled = !isJoined;
  els.syncBtn.disabled = !isJoined;
  if (els.undoBtn) {
    els.undoBtn.disabled = !isJoined;
  }
  if (els.redoBtn) {
    els.redoBtn.disabled = !isJoined;
  }
}

function refreshJoinedControls() {
  toggleJoinAvailability(state.joined);
}

els.joinBtn.addEventListener("click", joinRoom);
els.leaveBtn.addEventListener("click", leaveRoom);
els.syncBtn.addEventListener("click", syncRoom);
els.brushSize.addEventListener("input", () => {
  state.brushSize = Number(els.brushSize.value);
});
els.brushColor.addEventListener("input", () => {
  state.color = els.brushColor.value;
});
document.querySelectorAll("[data-tool]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-tool]").forEach((btn) => btn.classList.remove("active"));
    button.classList.add("active");
    state.activeTool = button.dataset.tool;
    updateBoardInteractionClass();
  });
});
els.clearProposeBtn.addEventListener("click", () => proposeClearCanvas());
els.undoBtn?.addEventListener("click", () => performUndo());
els.redoBtn?.addEventListener("click", () => performRedo());
els.leaveReportClose?.addEventListener("click", () => closeLeaveReportModal());
els.leaveReportModal?.addEventListener("click", (e) => {
  if (e.target === els.leaveReportModal) {
    closeLeaveReportModal();
  }
});
els.clearVoteApprove.addEventListener("click", () => {
  const p = state.pendingClearProposal;
  if (!p || !state.connected) {
    return;
  }
  try {
    send(buildClearVote(state, p.proposal_id, "approve"));
  } catch (error) {
    setError(String(error.message || error));
  }
  closeClearVoteModal();
});
els.clearVoteReject.addEventListener("click", () => {
  const p = state.pendingClearProposal;
  if (!p || !state.connected) {
    return;
  }
  try {
    send(buildClearVote(state, p.proposal_id, "reject"));
  } catch (error) {
    setError(String(error.message || error));
  }
  closeClearVoteModal();
});
window.addEventListener("resize", () => board.resize());
els.board.addEventListener("pointerdown", beginStroke);
els.board.addEventListener("pointermove", moveStroke);
els.board.addEventListener("pointerup", endStroke);
els.board.addEventListener("pointercancel", endStroke);
els.annotationLayer.addEventListener("click", (event) => {
  const target = event.target?.closest?.(".board-annotation--mine");
  if (!target || !state.joined) {
    return;
  }
  event.stopPropagation();
  const id = target.dataset.annotationId;
  if (!id) {
    return;
  }
  if (!window.confirm("删除此标注？")) {
    return;
  }
  try {
    send(buildAnnotationDelete(state, id));
  } catch (error) {
    setError(String(error.message || error));
  }
});
window.addEventListener("keydown", (event) => {
  const t = event.target;
  const tag = t?.tagName;
  const inField = tag === "INPUT" || tag === "TEXTAREA" || t?.isContentEditable;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    if (inField) {
      return;
    }
    event.preventDefault();
    if (event.shiftKey) {
      performRedo();
    } else {
      performUndo();
    }
    return;
  }
  if ((event.ctrlKey && event.key.toLowerCase() === "y") || (event.metaKey && event.shiftKey && event.key.toLowerCase() === "z")) {
    if (inField) {
      return;
    }
    event.preventDefault();
    performRedo();
    return;
  }
  if (event.key === "Escape") {
    if (!els.clearVoteModal.classList.contains("hidden")) {
      closeClearVoteModal();
      return;
    }
    proposeClearCanvas();
  }
});

updateBoardInteractionClass();
refreshJoinedControls();
setStatus("Ready to connect.");
updateRoomMeta();
