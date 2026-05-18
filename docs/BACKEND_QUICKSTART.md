# CollabBoard Backend Quickstart

## Install

```powershell
cd d:\Vscode_python\Collaboard
python -m pip install -r backend\requirements.txt
```

## Run

```powershell
cd d:\Vscode_python\Collaboard
backend\run.bat
```

By default `backend\run.bat` binds to `0.0.0.0:8000`, so other devices can reach it if your firewall, router, and deployment network allow inbound access. To keep it local-only, override the host before starting:

```powershell
$env:COLLABOARD_HOST = "127.0.0.1"
$env:COLLABOARD_PORT = "8000"
backend\run.bat
```

The backend serves:

- `GET /health`
- `WS /ws/{connection_id}`

## Test

```powershell
cd d:\Vscode_python\Collaboard
python -m pytest backend\tests -q
```

## Notes

- `sequence_id` is broadcast-driven and starts at `0` for the first broadcast event in a room.
- `ACK.sequence_id` mirrors the room's current sequence after the request has been processed.
- `STATE_SYNC` replies use `sequence_id = null` and return `current_sequence` inside `payload.room_state`.
- Per-room broadcast/event throughput is capped (`ROOM_RATE_LIMIT_EVENTS_PER_SECOND` in `config.py`, default 1000); exceeding it returns `RATE_LIMIT` on that request.
- Full canvas clear uses `clear_propose` + `clear_vote` (unanimous consent; single-user rooms clear immediately). Raw `clear` returns `CLEAR_REQUIRES_CONSENSUS`.
- Text/formula overlays use `annotation`; single-item removal uses `annotation_delete` → `annotation_removed`; restore via `annotation_restore` → another `annotation` event. Drawing undo/redo: `draw_undo` → `stroke_undone`; `draw_redo` → `draw` (see `01_PROTOCOL_SPECIFICATION.md` §3.2.1–3.2.5). `ANNOTATION_CONTENT_MAX_CHARS` and font bounds are in `config.py`.
