export class AppState {
  constructor() {
    this.connectionId = "";
    this.userId = "";
    this.userName = "";
    this.roomId = "";
    this.serverUrl = "";
    this.connected = false;
    this.joined = false;
    this.roomState = "idle";
    this.currentSequence = -1;
    this.lastReceivedSequence = -1;
    this.activeTool = "pen";
    /** @type {{ proposal_id: string, proposer_id: string, proposer_name: string, expires_ms: number, required_voters: string[] } | null} */
    this.pendingClearProposal = null;
    this.color = "#111111";
    this.brushSize = 4;
    this.pendingStrokes = new Map();
    this.optimisticStrokeIds = new Set();
    this.orderedBroadcasts = [];
    /** @type {{ kind: 'draw' | 'annotation', strokeId?: string, annotationId?: string }[]} */
    this.undoStack = [];
    /** @type {{ kind: 'draw' | 'annotation', strokeId?: string, annotationId?: string } | null} */
    this.pendingUndoEntry = null;
    /** @type {{ kind: 'draw' | 'annotation', strokeId?: string, annotationId?: string }[]} */
    this.redoStack = [];
    /** @type {{ kind: 'draw' | 'annotation', strokeId?: string, annotationId?: string } | null} */
    this.pendingRedoEntry = null;
    /** 本会话统计（离开房间时汇总报告） */
    this.sessionStats = {
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
    this.activeUsers = [];
    this.socket = null;
  }
}
