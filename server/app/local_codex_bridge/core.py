from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
from time import monotonic, time
from typing import Literal
from uuid import UUID

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class BridgeError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, retryable: bool = False):
        self.code, self.message, self.status, self.retryable = code, message, status, retryable
        super().__init__(message)


class BridgeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: SecretStr = Field(min_length=32)
    data_dir: Path
    codex_home: Path = Field(default_factory=lambda: Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    executable: str = Field(default_factory=lambda: shutil.which("codex.exe") or shutil.which("codex") or "codex")
    model: Literal["gpt-6.1-terra"] = "gpt-6.1-terra"
    max_concurrency: int = Field(default=1, ge=1, le=12)
    timeout_seconds: int = Field(default=480, ge=30, le=900)
    max_image_bytes: int = Field(default=100 * 1024 * 1024, ge=1024)
    host: str = "127.0.0.1"
    port: int = Field(default=18318, ge=1024, le=65535)


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    data_base64: str = Field(min_length=1, max_length=28 * 1024 * 1024)


class ExecutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID
    model: Literal["gpt-6.1-terra"]
    capability: Literal["image_generation", "image_edit", "multi_image_reference"]
    prompt: str = Field(min_length=1, max_length=60000)
    n: Literal[1] = 1
    size: str | None = Field(default=None, max_length=50)
    quality: str | None = Field(default=None, max_length=50)
    reference_images: list[Reference] = Field(default_factory=list, max_length=5)


def safe_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE",
                 "OPENAI_MODEL", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "CODEX_THREAD_ID"):
        env.pop(name, None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def image_metadata(data: bytes, limit: int) -> dict[str, object]:
    if not data or len(data) > limit:
        raise BridgeError("codex.image_size", "图片为空或超过本机执行服务大小上限")
    try:
        with Image.open(BytesIO(data)) as image:
            width, height, fmt = image.width, image.height, image.format
            if width * height > 40_000_000 or max(width, height) > 12000:
                raise ValueError("image dimensions exceed limit")
            image.verify()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise BridgeError("codex.invalid_image", "参考图或返回文件不是有效图片") from exc
    if fmt not in {"PNG", "JPEG", "WEBP"}:
        raise BridgeError("codex.invalid_image", "仅支持PNG、JPG和WEBP图片")
    return {"width": width, "height": height, "format": fmt, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def write_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def public_state(state: dict) -> dict:
    return {key: state[key] for key in ("job_id", "status", "error", "metadata") if key in state}


def classify_failure(text: str) -> dict:
    lower = text.lower()
    if any(s in lower for s in ("usage_limit", "usage limit", "quota exceeded", "insufficient_quota")):
        code, message = "codex.quota", "ChatGPT/Codex额度不足，请等待额度恢复或切换已授权通道"
    elif any(s in lower for s in ("unauthorized", "not logged in", "authentication failed", "invalid authentication", "login required")) or re.search(
        r"(?:http(?:/\d(?:\.\d)?)?\s+|status(?:\s+code)?\s*[:=]?\s*|response\s*[:=]\s*)401\b", lower
    ):
        code, message = "codex.auth", "本机Codex登录已失效，请在Windows本机重新登录ChatGPT"
    elif any(s in lower for s in ("tls handshake", "connection could not be established", "connection failed", "connection reset")):
        code, message = "codex.connection", "本机Codex连接生图服务失败；未自动重试，请检查网络或降低测试并发"
    else:
        code, message = "codex.no_output", "本机Codex未返回可验证的图片；未自动重试，请查看执行记录"
    return {"code": code, "message": message, "retryable": False}


class ExecutionManager:
    """Execution journal and deduplication only; not another business task queue."""
    def __init__(self, settings: BridgeSettings):
        self.settings = settings
        self.root = settings.data_dir.resolve() / "executions"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = asyncio.Lock()
        self.tasks: dict[str, asyncio.Task] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.login_checked = 0.0
        for path in self.root.glob("*/state.json"):
            state = read_json(path)
            if state.get("status") == "running":
                state.update(status="interrupted", error={"code": "codex.execution_unknown",
                    "message": "本机服务曾中断，远端执行状态未知；不会自动重复生成", "retryable": False})
                write_json(path, state)

    def folder(self, job_id: str | UUID) -> Path:
        try:
            return self.root / str(UUID(str(job_id)))
        except ValueError as exc:
            raise BridgeError("codex.invalid_job_id", "任务ID格式无效") from exc

    def state(self, job_id: str | UUID) -> dict:
        path = self.folder(job_id) / "state.json"
        if not path.is_file():
            raise BridgeError("codex.not_found", "本机执行记录不存在", 404)
        return read_json(path)

    async def ready(self) -> None:
        if monotonic() - self.login_checked < 30:
            return
        if not (self.settings.codex_home / "skills/.system/imagegen/SKILL.md").is_file():
            raise BridgeError("codex.skill_missing", "本机缺少官方imagegen Skill", 503)
        try:
            process = await asyncio.create_subprocess_exec(self.settings.executable, "login", "status",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=safe_environment(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            out, err = await asyncio.wait_for(process.communicate(), 20)
        except (OSError, asyncio.TimeoutError) as exc:
            if "process" in locals() and process.returncode is None:
                process.kill()
                await process.wait()
            raise BridgeError("codex.unavailable", "本机Codex无法启动或登录检查超时", 503) from exc
        if process.returncode or b"logged in using chatgpt" not in (out + err).lower():
            raise BridgeError("codex.auth", "本机Codex必须使用ChatGPT登录，不能使用API Key登录", 503)
        self.login_checked = monotonic()

    async def submit(self, payload: ExecutionInput) -> dict:
        job_id = str(payload.job_id)
        references = []
        for image in payload.reference_images:
            try:
                data = base64.b64decode(image.data_base64, validate=True)
            except ValueError as exc:
                raise BridgeError("codex.invalid_reference", "参考图编码无效") from exc
            meta = image_metadata(data, 20 * 1024 * 1024)
            expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[image.mime_type]
            if meta["format"] != expected:
                raise BridgeError("codex.invalid_reference", "参考图内容与声明格式不一致")
            references.append((image, data, meta))
        if payload.capability != "image_generation" and not references:
            raise BridgeError("codex.missing_reference", "图片编辑必须提供参考图")
        if payload.capability == "multi_image_reference" and len(references) < 2:
            raise BridgeError("codex.missing_reference", "多图编辑至少需要两张参考图")
        snapshot = payload.model_dump(mode="json", exclude={"reference_images"})
        snapshot["reference_images"] = [{"filename": r.filename, "sha256": m["sha256"]} for r, _, m in references]
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        async with self.lock:
            folder = self.folder(job_id)
            if (folder / "state.json").is_file():
                state = self.state(job_id)
                if state["input_hash"] != digest:
                    raise BridgeError("codex.idempotency_conflict", "相同任务ID的输入内容不一致", 409)
                return public_state(state)
            if any(read_json(p).get("status") == "interrupted" for p in self.root.glob("*/state.json")):
                raise BridgeError("codex.execution_unknown", "存在中断且状态未知的执行，请先人工核对本机记录", 409)
            if len(self.tasks) >= self.settings.max_concurrency:
                raise BridgeError("codex.busy", "本机执行槽已满，请在平台队列等待", 429, True)
            await self.ready()
            folder.mkdir(exist_ok=False)
            staged = []
            for index, (image, data, _) in enumerate(references, 1):
                suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[image.mime_type]
                path = folder / f"reference-{index:02d}{suffix}"
                path.write_bytes(data)
                staged.append(path)
            write_json(folder / "request.json", snapshot)
            state = {"job_id": job_id, "input_hash": digest, "status": "running",
                     "metadata": {"controller_model": self.settings.model, "reference_count": len(staged)}}
            write_json(folder / "state.json", state)
            task = asyncio.create_task(self.execute(job_id, payload.prompt, staged))
            self.tasks[job_id] = task
            return public_state(state)

    def command(self, folder: Path, images: list[Path]) -> list[str]:
        args = [self.settings.executable, "--no-daemon", "-a", "never", "exec", "--ignore-user-config", "--ignore-rules",
                "--skip-git-repo-check", "--ephemeral", "--sandbox", "workspace-write", "--json"]
        for feature in ("shell_tool", "unified_exec", "multi_agent", "apps", "plugins", "hooks", "memories",
                        "skill_search", "computer_use", "browser_use", "unbounded_connection_retries"):
            args.extend(["--disable", feature])
        args.extend(["--enable", "image_generation", "-c", 'model_provider="openai"', "-c", 'web_search="disabled"',
                     "-c", "agents.enabled=false", "-c", "project_doc_max_bytes=0", "-c", 'model_reasoning_effort="low"',
                     "--model", self.settings.model, "--cd", str(folder),
                     "--output-last-message", str(folder / "agent-result.txt")])
        for path in images:
            args.extend(["--image", str(path)])
        return args + ["-"]

    async def kill(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(killer.wait(), 10)
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        await process.wait()

    async def execute(self, job_id: str, prompt: str, images: list[Path]) -> None:
        folder, started = self.folder(job_id), time()
        state = self.state(job_id)
        process = None
        try:
            instructions = Path(__file__).with_name("execution_instructions.txt").read_text(encoding="utf-8")
            skill = (self.settings.codex_home / "skills/.system/imagegen/SKILL.md").read_text(encoding="utf-8")
            text = (instructions + "\n<business_prompt>\n" + prompt + "\n</business_prompt>\n"
                    + "Official skill instructions (built-in mode only):\n" + skill
                    + "\nThe user forbids all API/CLI fallbacks. Only the built-in image tool is authorized.\n")
            process = await asyncio.create_subprocess_exec(*self.command(folder, images),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=safe_environment(), creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0,
                start_new_session=os.name != "nt")
            self.processes[job_id] = process
            state["pid"] = process.pid
            write_json(folder / "state.json", state)
            try:
                out, err = await asyncio.wait_for(process.communicate(text.encode("utf-8")), self.settings.timeout_seconds)
            except asyncio.TimeoutError:
                await self.kill(process)
                raise BridgeError("codex.execution_unknown", "Codex执行超时，远端消耗未知；未自动重试")
            stdout, stderr = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
            for name, content in (("events.jsonl", stdout), ("stderr.txt", stderr)):
                clean = re.sub(r"(?i)(Bearer\s+)[^\s\"']+|\bsk-[A-Za-z0-9_-]{10,}", "[REDACTED]", content)
                (folder / name).write_text(clean, encoding="utf-8")
            events = []
            for line in stdout.splitlines():
                with suppress(ValueError):
                    events.append(json.loads(line))
            threads = [e.get("thread_id") for e in events if e.get("type") == "thread.started"]
            complete = any(e.get("type") == "turn.completed" for e in events)
            if process.returncode or not complete or len(threads) != 1 or not re.fullmatch(r"[0-9a-fA-F-]{36}", str(threads[0])):
                error = classify_failure(stdout + stderr)
                raise BridgeError(error["code"], error["message"])
            candidates = []
            generated = self.settings.codex_home / "generated_images" / str(threads[0])
            if generated.is_symlink() or generated.resolve().parent != (self.settings.codex_home / "generated_images").resolve():
                raise BridgeError("codex.invalid_output_path", "生图输出路径不属于当前执行会话")
            for path in generated.glob("*.png"):
                if path.is_symlink() or path.stat().st_mtime < started - 2:
                    continue
                if path.resolve().parent != generated.resolve():
                    continue
                if path.stat().st_size > self.settings.max_image_bytes:
                    raise BridgeError("codex.image_size", "返回图片超过本机执行服务大小上限")
                data = path.read_bytes()
                meta = image_metadata(data, self.settings.max_image_bytes)
                if meta["format"] == "PNG":
                    candidates.append((data, meta))
            if len(candidates) != 1:
                error = classify_failure(stdout + stderr)
                raise BridgeError(error["code"], error["message"])
            data, meta = candidates[0]
            (folder / "output.png").write_bytes(data)
            state.update(status="succeeded", metadata={**state["metadata"], **meta,
                         "elapsed_seconds": round(time() - started, 2), "output_count": 1})
        except asyncio.CancelledError:
            if process:
                await self.kill(process)
            state.update(status="cancelled", error={"code": "codex.cancelled",
                "message": "本机执行已取消；已发到云端的消耗可能仍然发生", "retryable": False})
        except BridgeError as exc:
            state.update(status="failed", error={"code": exc.code, "message": exc.message, "retryable": False})
        except Exception:
            if process and process.returncode is None:
                await self.kill(process)
            state.update(status="failed", error={"code": "codex.execution_error",
                "message": "本机执行失败，请检查本机日志；未自动重复生成", "retryable": False})
        finally:
            write_json(folder / "state.json", state)
            self.processes.pop(job_id, None)
            self.tasks.pop(job_id, None)

    async def cancel(self, job_id: str) -> dict:
        state = self.state(job_id)
        task = self.tasks.get(str(UUID(job_id)))
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            state = self.state(job_id)
            if state["status"] == "running":
                state.update(status="cancelled", error={"code": "codex.cancelled",
                    "message": "本机执行已取消", "retryable": False})
                write_json(self.folder(job_id) / "state.json", state)
                self.tasks.pop(str(UUID(job_id)), None)
        # An interrupted execution is intentionally not cleared automatically:
        # its orphan/remote status must be checked by the local operator.
        return public_state(state)

    async def shutdown(self) -> None:
        job_ids = list(self.tasks)
        if job_ids:
            await asyncio.gather(*(self.cancel(job_id) for job_id in job_ids), return_exceptions=True)


def initialize_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {"access_token": secrets.token_urlsafe(48), "data_dir": str(path.parent / "data")}
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
    with suppress(OSError):
        path.chmod(0o600)
