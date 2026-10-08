import asyncio
import json
import secrets
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver

from .agent import Agent
from .config import Settings
from .fixtures import FIXTURES
from .schemas import CreateRun, Decision
from .store import Store


def create_app(settings=None, model=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        settings.prepare()
        with ExitStack() as stack:
            store = Store(settings.database_url)
            stack.callback(store.engine.dispose)
            if settings.checkpoint_url.startswith("postgres"):
                saver = stack.enter_context(PostgresSaver.from_conn_string(settings.checkpoint_url))
            else:
                saver = stack.enter_context(SqliteSaver.from_conn_string(settings.checkpoint_url))
            saver.setup()
            app.state.store = store
            app.state.agent = Agent(store, settings, saver, model=model)
            store.recover()
            yield

    app = FastAPI(title="Trace Incident Agent", version="0.1.0", lifespan=lifespan)

    def auth(authorization: str | None = Header(default=None)):
        if settings.console_token and not secrets.compare_digest(authorization or "", "Bearer " + settings.console_token):
            raise HTTPException(401, "需要 CONSOLE_TOKEN")

    def require_run(run_id):
        row = app.state.store.get(run_id)
        if row is None:
            raise HTTPException(404, "任务不存在")
        return row

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": "0.1.0"}

    @app.get("/api/config", dependencies=[Depends(auth)])
    def config():
        return {"mode": settings.app_mode, "model": settings.llm_model if settings.app_mode == "live" else None, "storage": "postgresql" if settings.database_url.startswith("postgres") else "sqlite", "retrieval": "lexical", "ticket_target": "local", "max_model_rounds": settings.max_model_rounds, "max_tool_calls": settings.max_tool_calls}

    @app.get("/api/examples", dependencies=[Depends(auth)])
    def examples():
        return list(FIXTURES.values())

    @app.get("/api/runs", dependencies=[Depends(auth)])
    def list_runs():
        return app.state.store.list()

    @app.post("/api/runs", status_code=202, dependencies=[Depends(auth)])
    def create_run(data: CreateRun, tasks: BackgroundTasks):
        payload = data.model_dump()
        if data.fixture_id:
            if data.fixture_id not in FIXTURES:
                raise HTTPException(422, "未知演示案例")
            if data.logs or data.diff:
                raise HTTPException(422, "演示案例与自定义证据不能混用")
            payload.update({k: FIXTURES[data.fixture_id][k] for k in ("logs", "diff")})
        run_id = app.state.store.create(payload, settings.app_mode)
        app.state.store.transition(run_id, ["queued"], "running")
        tasks.add_task(app.state.agent.execute, run_id)
        return {"id": run_id}

    @app.get("/api/runs/{run_id}", dependencies=[Depends(auth)])
    def get_run(run_id: str):
        return require_run(run_id)

    @app.get("/api/runs/{run_id}/events", dependencies=[Depends(auth)])
    def get_events(run_id: str):
        require_run(run_id)
        return app.state.store.get_events(run_id)

    @app.get("/api/runs/{run_id}/stream", dependencies=[Depends(auth)])
    async def stream(run_id: str, request: Request):
        require_run(run_id)

        async def generate():
            while not await request.is_disconnected():
                row = await asyncio.to_thread(app.state.store.get, run_id)
                log = await asyncio.to_thread(app.state.store.get_events, run_id)
                yield "event: snapshot\ndata: " + json.dumps(jsonable_encoder({"run": row, "events": log}), ensure_ascii=False) + "\n\n"
                if row["status"] not in ["queued", "running", "approving"]:
                    break
                await asyncio.sleep(0.6)
        return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/runs/{run_id}/decision", dependencies=[Depends(auth)])
    def decide(run_id: str, data: Decision, tasks: BackgroundTasks):
        row = require_run(run_id)
        decision = data.model_dump()
        if row["decision"] is not None:
            if row["decision"] == decision:
                return {"id": run_id, "status": row["status"], "idempotent": True}
            raise HTTPException(409, "该任务已经记录了不同的审批决定")
        if not app.state.store.transition(run_id, ["awaiting_approval"], "approving", decision=decision):
            raise HTTPException(409, "任务当前不可审批，请刷新状态")
        app.state.store.event(run_id, "approval", "人工同意创建工单" if data.approved else "人工拒绝创建工单", {"note": data.note})
        tasks.add_task(app.state.agent.execute, run_id, True)
        return {"id": run_id, "status": "approving"}

    @app.post("/api/runs/{run_id}/retry", status_code=202, dependencies=[Depends(auth)])
    def retry(run_id: str, tasks: BackgroundTasks):
        row = require_run(run_id)
        if row["mode"] != settings.app_mode:
            raise HTTPException(409, "请恢复原运行模式，或新建任务")
        if not app.state.store.transition(run_id, ["failed", "interrupted"], "running", error=None):
            raise HTTPException(409, "仅失败或中断任务可重试")
        tasks.add_task(app.state.agent.execute, run_id, True)
        return {"id": run_id}

    @app.get("/api/runs/{run_id}/export", dependencies=[Depends(auth)])
    def export(run_id: str):
        return {"run": require_run(run_id), "events": app.state.store.get_events(run_id), "notice": "Demo outputs are deterministic fixtures, not model evaluation results."}

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")
    return app


app = create_app()
