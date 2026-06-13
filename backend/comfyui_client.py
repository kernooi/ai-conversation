from __future__ import annotations

import copy
import json
import mimetypes
import random
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

import httpx

from config import settings


class ComfyUIError(RuntimeError):
    """Raised when ComfyUI is unavailable or generation fails."""


def _backend_dir() -> Path:
    return Path(__file__).resolve().parent


def _resolve_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return _backend_dir() / candidate


def _base_url() -> str:
    return settings.comfyui_url.rstrip("/")


async def health() -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{_base_url()}/system_stats")
        response.raise_for_status()
        data = response.json()
        return {
            "available": True,
            "url": _base_url(),
            "devices": data.get("devices", []),
        }


def _default_workflow(
    *,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float,
) -> dict:
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": settings.comfyui_checkpoint},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": prompt},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": negative},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": settings.image_gen_sampler,
                "scheduler": settings.image_gen_scheduler,
                "denoise": 1.0,
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"images": ["6", 0], "filename_prefix": "ai_conversation"},
        },
    }


def _reference_workflow(
    *,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float,
    reference_image: str,
    denoise: float,
) -> dict:
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": settings.comfyui_checkpoint},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": prompt},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": negative},
        },
        "4": {
            "class_type": "LoadImage",
            "inputs": {"image": reference_image},
        },
        "5": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["4", 0],
                "upscale_method": "lanczos",
                "width": width,
                "height": height,
                "crop": "center",
            },
        },
        "6": {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["6", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": settings.image_gen_sampler,
                "scheduler": settings.image_gen_scheduler,
                "denoise": denoise,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["7", 0], "vae": ["1", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "ai_conversation"},
        },
    }


def _load_workflow() -> dict | None:
    if not settings.comfyui_workflow_path.strip():
        return None
    workflow_path = _resolve_path(settings.comfyui_workflow_path)
    if not workflow_path.is_file():
        raise ComfyUIError(f"ComfyUI workflow file not found: {workflow_path}")
    return json.loads(workflow_path.read_text(encoding="utf-8"))


def _apply_workflow_values(
    workflow: dict,
    *,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float,
    reference_image: str | None = None,
) -> dict:
    updated = copy.deepcopy(workflow)
    for node in updated.values():
        inputs = node.get("inputs", {})
        class_type = node.get("class_type")
        if class_type == "CLIPTextEncode" and "text" in inputs:
            text = str(inputs.get("text") or "").lower()
            inputs["text"] = negative if "negative" in text else prompt
        if class_type == "EmptyLatentImage":
            inputs["width"] = width
            inputs["height"] = height
            inputs["batch_size"] = 1
        if class_type == "LoadImage" and reference_image:
            inputs["image"] = reference_image
        if class_type == "ImageScale":
            inputs["width"] = width
            inputs["height"] = height
        if class_type == "KSampler":
            inputs["seed"] = seed
            inputs["steps"] = steps
            inputs["cfg"] = cfg
            inputs["sampler_name"] = settings.image_gen_sampler
            inputs["scheduler"] = settings.image_gen_scheduler
            if reference_image:
                inputs["denoise"] = settings.image_gen_reference_denoise
        if class_type == "SaveImage":
            inputs["filename_prefix"] = "ai_conversation"
    return updated


def _workflow(
    *,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float,
    reference_image: str | None = None,
) -> dict:
    custom = _load_workflow()
    if custom is not None:
        return _apply_workflow_values(
            custom,
            prompt=prompt,
            negative=negative,
            width=width,
            height=height,
            seed=seed,
            steps=steps,
            cfg=cfg,
            reference_image=reference_image,
        )
    if reference_image:
        return _reference_workflow(
            prompt=prompt,
            negative=negative,
            width=width,
            height=height,
            seed=seed,
            steps=steps,
            cfg=cfg,
            reference_image=reference_image,
            denoise=settings.image_gen_reference_denoise,
        )
    return _default_workflow(
        prompt=prompt,
        negative=negative,
        width=width,
        height=height,
        seed=seed,
        steps=steps,
        cfg=cfg,
    )


def _reference_filename(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    return f"ai_conversation_ref_{uuid.uuid4().hex}{suffix}"


async def _upload_reference_image(
    client: httpx.AsyncClient,
    image_bytes: bytes,
    filename: str | None,
    content_type: str | None,
) -> str:
    upload_name = _reference_filename(filename)
    media_type = content_type or mimetypes.guess_type(upload_name)[0] or "image/png"
    response = await client.post(
        f"{_base_url()}/upload/image",
        data={"type": "input", "overwrite": "true"},
        files={"image": (upload_name, image_bytes, media_type)},
    )
    response.raise_for_status()
    data = response.json()
    name = data.get("name")
    subfolder = data.get("subfolder") or ""
    if not name:
        raise ComfyUIError("ComfyUI did not return an uploaded image name")
    if subfolder:
        return f"{subfolder}/{name}"
    return name


async def _queue_prompt(client: httpx.AsyncClient, workflow: dict) -> str:
    response = await client.post(
        f"{_base_url()}/prompt",
        json={"prompt": workflow, "client_id": str(uuid.uuid4())},
    )
    response.raise_for_status()
    prompt_id = response.json().get("prompt_id")
    if not prompt_id:
        raise ComfyUIError("ComfyUI did not return a prompt_id")
    return prompt_id


async def _wait_for_image(client: httpx.AsyncClient, prompt_id: str) -> dict:
    deadline = time.perf_counter() + settings.image_gen_timeout
    last_status = ""
    while time.perf_counter() < deadline:
        response = await client.get(f"{_base_url()}/history/{prompt_id}")
        response.raise_for_status()
        history = response.json().get(prompt_id)
        if history:
            status = history.get("status", {})
            if status.get("status_str") == "error":
                messages = status.get("messages") or []
                raise ComfyUIError(f"ComfyUI generation failed: {messages}")
            for output in history.get("outputs", {}).values():
                images = output.get("images") or []
                if images:
                    return images[0]
            last_status = str(status)
        await _sleep(0.5)
    raise ComfyUIError(f"ComfyUI generation timed out; last status={last_status}")


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


async def generate_image(
    *,
    prompt: str,
    negative: str = "",
    width: int | None = None,
    height: int | None = None,
    seed: int | None = None,
    steps: int | None = None,
    cfg: float | None = None,
    reference_image_bytes: bytes | None = None,
    reference_image_filename: str | None = None,
    reference_image_content_type: str | None = None,
) -> bytes:
    width = width or settings.image_gen_width
    height = height or settings.image_gen_height
    seed = seed if seed is not None else random.randint(0, 2**32 - 1)
    steps = steps or settings.image_gen_steps
    cfg = cfg if cfg is not None else settings.image_gen_cfg

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.image_gen_timeout + 30.0, connect=5.0)) as client:
            reference_image = None
            if reference_image_bytes:
                reference_image = await _upload_reference_image(
                    client,
                    reference_image_bytes,
                    reference_image_filename,
                    reference_image_content_type,
                )
            workflow = _workflow(
                prompt=prompt,
                negative=negative,
                width=width,
                height=height,
                seed=seed,
                steps=steps,
                cfg=cfg,
                reference_image=reference_image,
            )
            prompt_id = await _queue_prompt(client, workflow)
            image = await _wait_for_image(client, prompt_id)
            query = urlencode(
                {
                    "filename": image["filename"],
                    "subfolder": image.get("subfolder", ""),
                    "type": image.get("type", "output"),
                }
            )
            response = await client.get(f"{_base_url()}/view?{query}")
            response.raise_for_status()
            return response.content
    except httpx.ConnectError as e:
        raise ComfyUIError(f"ComfyUI is not running at {_base_url()}") from e
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:500]
        raise ComfyUIError(f"ComfyUI HTTP {e.response.status_code}: {detail}") from e
