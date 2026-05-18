# CollabBoard Frontend

Vanilla ES-module client aligned with `01_PROTOCOL_SPECIFICATION.md` (ordered replay, STATE_SYNC deltas, optimistic draw reconciled against broadcast, annotation replay including `annotation_removed`, `stroke_undone`, local undo/redo stacks, leave-room session summary modal).

## Run (recommended)

Start the FastAPI backend from the repo root; it serves `/` and `/frontend/*`:

```powershell
cd d:\Vscode_python\Collaboard
backend\run.bat
```

Open `http://127.0.0.1:8000/`.

When the frontend is served by the backend, the **Server URL** field auto-detects the current host and uses `/ws` on that same origin. If you deploy the app to `https://your-domain.example`, the browser will default to `wss://your-domain.example/ws`.

## Run (static only)

For UI-only debugging without the API:

```powershell
cd d:\Vscode_python\Collaboard\frontend
python -m http.server 5173
```

Set **Server URL** in the UI to your backend websocket base such as `ws://127.0.0.1:8000/ws` or `wss://your-domain.example/ws` (the client expands this to `/ws/{connection_id}`).
