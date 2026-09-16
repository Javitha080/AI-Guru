"""Async task-based video-generation adapter.

Text-to-video providers don't share a synchronous standard. The common shape —
used by Volcengine Ark (Seedance) and most others — is a task lifecycle::

    POST {base}/contents/generations/tasks        -> {"id": ...}
    GET  {base}/contents/generations/tasks/{id}   -> {"status": ..., "content": {"video_url": ...}}

This adapter submits the task, polls until it reaches a terminal state, then
downloads the resulting video to bytes. Provider-specific request shaping and
result extraction are isolated in ``_build_submit_payload`` / ``_extract_*`` so
other task-style providers can be supported by subclassing and re-keying the
registry — the polling/download machinery is shared.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from deeptutor.services.generation_http import (
    GenerationProviderError,
    build_auth_headers,
    join_api_path,
    raise_for_provider,
)
from deeptutor.services.videogen.base import BaseVideogenAdapter, ProgressFn
from deeptutor.services.videogen.config import VideogenConfig

logger = logging.getLogger(__name__)

_SUBMIT_PATH = "contents/generations/tasks"
_SUCCESS_STATES = {"succeeded", "success", "completed", "done"}
_FAILURE_STATES = {"failed", "error", "cancelled", "canceled", "expired"}


class AsyncTaskVideogenAdapter(BaseVideogenAdapter):
    """Submit a generation task, poll to completion, download the video bytes."""

    @staticmethod
    def _headers(config: VideogenConfig) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }

    async def submit_task(self, prompt: str, config: VideogenConfig) -> str:
        if not config.base_url:
            raise GenerationProviderError("No endpoint URL configured for video generation.")
        submit_url = join_api_path(config.base_url, _SUBMIT_PATH)
        payload = self._build_submit_payload(prompt, config)
        logger.debug("videogen submit url=%s model=%s", submit_url, config.model)
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(submit_url, headers=self._headers(config), json=payload)
                raise_for_provider(resp, "Video task submission")
                return self._extract_task_id(resp)
        except httpx.HTTPError as exc:
            raise GenerationProviderError(f"Video task submission error: {exc}") from exc

    async def generate(
        self,
        prompt: str,
        config: VideogenConfig,
        *,
        progress: ProgressFn | None = None,
    ) -> tuple[bytes, str]:
        task_id = await self.submit_task(prompt, config)
        await self._notify(progress, f"Submitted video task; rendering… (id={task_id})")
        headers = self._headers(config)
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                video_url = await self._poll(client, config, headers, task_id, progress)
                await self._notify(progress, "Downloading rendered video…")
                video_resp = await client.get(video_url)
                raise_for_provider(video_resp, "Video download")
                content = video_resp.content
                content_type = video_resp.headers.get("content-type") or "video/mp4"
        except httpx.HTTPError as exc:
            raise GenerationProviderError(f"Video generation request error: {exc}") from exc
        if not content:
            raise GenerationProviderError("Video provider returned an empty file.")
        if not content_type.startswith("video/"):
            content_type = "video/mp4"
        return content, content_type

    async def _poll(
        self,
        client: httpx.AsyncClient,
        config: VideogenConfig,
        headers: dict[str, str],
        task_id: str,
        progress: ProgressFn | None,
    ) -> str:
        poll_url = join_api_path(config.base_url, f"{_SUBMIT_PATH}/{task_id}")
        deadline = time.monotonic() + config.poll_timeout
        polls = 0
        current_interval = min(2.0, config.poll_interval)
        while True:
            resp = await client.get(poll_url, headers=headers)
            raise_for_provider(resp, "Video task status")
            status, video_url, error = self._extract_status(resp)
            if status in _SUCCESS_STATES and video_url:
                return video_url
            if status in _FAILURE_STATES:
                raise GenerationProviderError(
                    f"Video task {task_id} {status}: {error or 'no detail provided'}"
                )
            if time.monotonic() >= deadline:
                raise GenerationProviderError(
                    f"Video task {task_id} timed out after {config.poll_timeout}s "
                    f"(last status: {status or 'unknown'})."
                )
            polls += 1
            if progress and polls % 3 == 0:
                await self._notify(progress, f"Still rendering video… (status: {status or '…'})")
            await asyncio.sleep(current_interval)
            current_interval = min(config.poll_interval, current_interval + 0.5)

    # --- provider-specific shaping -------------------------------------------

    @staticmethod
    def _build_submit_payload(prompt: str, config: VideogenConfig) -> dict[str, Any]:
        """Build the submit body supporting both Seedance text commands and structured API shapes."""
        commands = []
        if config.aspect_ratio:
            commands.append(f"--ratio {config.aspect_ratio}")
        if config.resolution:
            commands.append(f"--resolution {config.resolution}")
        if config.duration:
            commands.append(f"--duration {config.duration}")
        if config.fps:
            commands.append(f"--fps {config.fps}")
        if config.seed is not None:
            commands.append(f"--seed {config.seed}")
        text = f"{prompt} {' '.join(commands)}".strip() if commands else prompt
        payload: dict[str, Any] = {
            "model": config.model,
            "content": [{"type": "text", "text": text}],
            "prompt": text,
        }
        if config.aspect_ratio:
            payload["aspect_ratio"] = config.aspect_ratio
        if config.duration:
            payload["duration"] = config.duration
        if config.resolution:
            payload["resolution"] = config.resolution
        if config.fps:
            payload["fps"] = config.fps
        if config.seed is not None:
            payload["seed"] = config.seed
        return payload

    @staticmethod
    def _extract_task_id(resp: httpx.Response) -> str:
        data = resp.json()
        if isinstance(data, dict):
            for key in ("id", "task_id", "taskId", "uuid", "job_id"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
            for nest_key in ("data", "result", "output"):
                nested = data.get(nest_key)
                if isinstance(nested, dict):
                    for k in ("id", "task_id", "taskId", "uuid"):
                        val = nested.get(k)
                        if isinstance(val, str) and val:
                            return val
        raise GenerationProviderError("Video task submission returned no task id.")

    @staticmethod
    def _extract_status(resp: httpx.Response) -> tuple[str, str, str]:
        """Return ``(status, video_url, error_message)`` from a status payload."""
        data = resp.json()
        if not isinstance(data, dict):
            raise GenerationProviderError("Malformed video task status response.")
        status = str(
            data.get("status") or data.get("state") or data.get("task_status") or ""
        ).lower()

        def _find_video_url(val: Any) -> str:
            if isinstance(val, str) and (val.startswith("http://") or val.startswith("https://")):
                return val
            if isinstance(val, list):
                for item in val:
                    found = _find_video_url(item)
                    if found:
                        return found
            elif isinstance(val, dict):
                for key in ("video_url", "video", "url", "download_url", "file_url"):
                    item = val.get(key)
                    if isinstance(item, str) and (
                        item.startswith("http://") or item.startswith("https://")
                    ):
                        return item
                for sub in ("content", "data", "result", "output", "videos"):
                    if sub in val:
                        found = _find_video_url(val[sub])
                        if found:
                            return found
            return ""

        video_url = _find_video_url(data)

        err = data.get("error")
        if isinstance(err, dict):
            error = str(err.get("message") or err.get("detail") or "")
        else:
            error = str(err or "")
        return status, video_url, error

    @staticmethod
    async def _notify(progress: ProgressFn | None, message: str) -> None:
        if progress is not None:
            await progress(message)


__all__ = ["AsyncTaskVideogenAdapter"]
