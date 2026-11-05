from contextlib import asynccontextmanager
import hmac

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from .core import BridgeError, BridgeSettings, ExecutionInput, ExecutionManager, public_state


def create_bridge_app(settings: BridgeSettings) -> FastAPI:
    manager = ExecutionManager(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await manager.shutdown()

    app = FastAPI(title="Local Codex image execution bridge", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.manager = manager

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.url.path != "/healthz":
            expected = "Bearer " + settings.access_token.get_secret_value()
            if not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected.encode()):
                return JSONResponse({"error": {"code": "codex.auth", "message": "本机执行服务鉴权失败"}}, 401)
        if request.method == "POST":
            length = request.headers.get("content-length")
            if length is None or not length.isdigit() or int(length) > 150 * 1024 * 1024:
                return JSONResponse({"error": {"code": "codex.body_size", "message": "请求体大小无效或超限"}}, 413)
        return await call_next(request)

    @app.exception_handler(BridgeError)
    async def bridge_error(request, error):
        return JSONResponse({"error": {"code": error.code, "message": error.message,
                                      "retryable": error.retryable}}, error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # Never echo base64 image payloads or untrusted input in validation errors.
        return JSONResponse({"error": {"code": "codex.invalid_request",
                                      "message": "本机生成请求参数无效，请检查模型、参考图和任务ID"}}, 422)

    @app.get("/healthz")
    async def health():
        return {"ok": True, "service": "codex-native-image-bridge", "active": len(manager.tasks), "max_concurrency": settings.max_concurrency}

    @app.get("/v1/models")
    async def models():
        await manager.ready()
        return {"object": "list", "data": [{"id": settings.model, "object": "model", "owned_by": "local-codex"}]}

    @app.post("/v1/executions")
    async def execute(payload: ExecutionInput):
        return await manager.submit(payload)

    @app.get("/v1/executions/{job_id}")
    async def state(job_id: str):
        return public_state(manager.state(job_id))

    @app.post("/v1/executions/{job_id}/cancel")
    async def cancel(job_id: str):
        return await manager.cancel(job_id)

    @app.get("/v1/executions/{job_id}/output")
    async def output(job_id: str):
        state = manager.state(job_id)
        if state["status"] != "succeeded":
            raise BridgeError("codex.not_ready", "任务尚无可下载结果", 409)
        path = manager.folder(job_id) / "output.png"
        if not path.is_file() or path.is_symlink():
            raise BridgeError("codex.output_missing", "本机结果文件不存在", 410)
        return FileResponse(path, media_type="image/png", filename="generated.png")

    return app
