const CLIENT_VERSION = "1.0.0";

export function uuid() {
  if (crypto?.randomUUID) {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function nowMs() {
  return Date.now();
}

export function buildClientMessage(type, state, payload) {
  const message = {
    msg_id: uuid(),
    type,
    timestamp: nowMs(),
    user_id: state.userId,
    room_id: state.roomId,
    sequence_id: null,
    payload,
  };
  if (state.securityContext && typeof state.securityContext === "object") {
    message.security = { ...state.securityContext };
  }
  return message;
}

export function buildJoin(state) {
  return buildClientMessage("join", state, {
    client_version: CLIENT_VERSION,
    metadata: {
      user_name: state.userName || state.userId,
      client_type: "web",
    },
  });
}

export function buildLeave(state, reason = "manual") {
  return buildClientMessage("leave", state, { reason, message: "leaving room" });
}

export function buildDraw(state, stroke) {
  return buildClientMessage("draw", state, stroke);
}

export function buildClear(state) {
  return buildClientMessage("clear", state, { clear_type: "full" });
}

export function buildAnnotation(state, payload) {
  return buildClientMessage("annotation", state, payload);
}

export function buildAnnotationDelete(state, annotationId) {
  return buildClientMessage("annotation_delete", state, {
    annotation_id: annotationId,
  });
}

export function buildAnnotationDeleteRequest(state, annotationId, message = "") {
  const payload = {
    annotation_id: annotationId,
  };
  if (message) {
    payload.message = message;
  }
  return buildClientMessage("annotation_delete_request", state, payload);
}

export function buildAnnotationDeleteVote(state, requestId, annotationId, vote) {
  return buildClientMessage("annotation_delete_vote", state, {
    request_id: requestId,
    annotation_id: annotationId,
    vote,
  });
}

export function buildAnnotationRestore(state, annotationId) {
  return buildClientMessage("annotation_restore", state, {
    annotation_id: annotationId,
  });
}

export function buildDrawUndo(state, strokeId) {
  return buildClientMessage("draw_undo", state, {
    stroke_id: strokeId,
  });
}

export function buildDrawRedo(state, strokeId) {
  return buildClientMessage("draw_redo", state, {
    stroke_id: strokeId,
  });
}

export function buildClearPropose(state, message = "") {
  return buildClientMessage("clear_propose", state, message ? { message } : {});
}

export function buildClearVote(state, proposalId, vote) {
  return buildClientMessage("clear_vote", state, {
    proposal_id: proposalId,
    vote,
  });
}

export function buildStateSync(state) {
  return buildClientMessage("state_sync", state, {
    last_received_sequence: state.lastReceivedSequence,
  });
}

export function isBroadcast(message) {
  return message?.type === "broadcast" && typeof message.sequence_id === "number";
}

export function isAck(message) {
  return message?.type === "ack";
}

export function isError(message) {
  return message?.type === "error";
}
