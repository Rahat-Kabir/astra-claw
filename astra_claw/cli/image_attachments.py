"""Prepare local image paths as multimodal chat content blocks."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..tools.path_safety import inside_workspace_fence, is_sensitive_path


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGES_PER_PROMPT = 4
_PATH_TOKEN_PATTERN = re.compile(r'"[^"]+"|\'[^\']+\'|\S+')
_PATH_PREFIXES = ("@file:", "@folder:")
_EDGE_PUNCTUATION = "\"'()[]{}.,;!?"


@dataclass(frozen=True)
class ImageAttachment:
    path: Path
    mime_type: str
    data_url: str


@dataclass(frozen=True)
class PreparedImagePrompt:
    content: str | list[dict]
    image_paths: tuple[Path, ...]
    warnings: tuple[str, ...]


def detect_image_mime(path: Path) -> Optional[str]:
    """Detect a supported image from its signature, not its extension."""
    try:
        with open(path, "rb") as image_file:
            header = image_file.read(16)
    except OSError:
        return None

    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return None


def prepare_image_prompt(
    source_text: str,
    *,
    text_for_model: Optional[str] = None,
    selector: Optional[Callable[[str, list[str]], str]] = None,
    max_image_bytes: int = MAX_IMAGE_BYTES,
    max_images: int = MAX_IMAGES_PER_PROMPT,
) -> PreparedImagePrompt:
    """Attach supported images mentioned as ordinary paths in ``source_text``.

    Direct image paths attach immediately. A folder with one supported image
    attaches it; a folder with several asks through ``selector``. Without an
    interactive selector, ambiguous folders become warnings and are skipped.
    """
    model_text = source_text if text_for_model is None else text_for_model
    mentioned_paths = discover_image_paths(source_text)
    selected_paths: list[Path] = []
    warnings: list[str] = []

    for mentioned_path in mentioned_paths:
        if is_sensitive_path(mentioned_path):
            warnings.append(f"Blocked sensitive image path: {mentioned_path}")
            continue

        if mentioned_path.is_file():
            selected_paths.append(mentioned_path)
            continue

        images = _images_in_folder(mentioned_path)
        if len(images) == 1:
            selected_paths.append(images[0])
            continue
        if not images:
            continue
        if selector is None:
            warnings.append(
                f"Multiple images found in {mentioned_path}; use a direct image path "
                "in non-interactive mode."
            )
            continue

        choices = [str(path) for path in images]
        answer = selector(f"Which image from {mentioned_path} should I attach?", choices)
        chosen = _resolve_selection(answer, images)
        if chosen is None:
            warnings.append(f"No image selected from {mentioned_path}.")
            continue
        selected_paths.append(chosen)

    selected_paths = _deduplicate_paths(selected_paths)
    if len(selected_paths) > max_images:
        warnings.append(
            f"Found {len(selected_paths)} images; attached the first {max_images}."
        )
        selected_paths = selected_paths[:max_images]

    attachments: list[ImageAttachment] = []
    for path in selected_paths:
        attachment, warning = _encode_image(path, max_image_bytes=max_image_bytes)
        if warning:
            warnings.append(warning)
        if attachment is not None:
            attachments.append(attachment)

    if not attachments:
        return PreparedImagePrompt(model_text, (), tuple(warnings))

    attachment_note = "\n".join(f"- {item.path}" for item in attachments)
    text_block = model_text.rstrip() + "\n\nAttached images:\n" + attachment_note
    content: list[dict] = [{"type": "text", "text": text_block}]
    content.extend(
        {
            "type": "image_url",
            "image_url": {"url": item.data_url},
        }
        for item in attachments
    )
    return PreparedImagePrompt(
        content=content,
        image_paths=tuple(item.path for item in attachments),
        warnings=tuple(warnings),
    )


def discover_image_paths(message: str) -> list[Path]:
    """Return mentioned image files and image-containing folders in order."""
    raw_tokens = _PATH_TOKEN_PATTERN.findall(message)
    tokens = [_clean_token(token) for token in raw_tokens]
    found: list[Path] = []

    start = 0
    while start < len(tokens):
        if not tokens[start]:
            start += 1
            continue
        longest: Optional[Path] = None
        longest_end = start + 1
        for end in range(start + 1, min(len(tokens), start + 12) + 1):
            raw = " ".join(tokens[start:end]).strip(_EDGE_PUNCTUATION)
            explicit_context_ref = False
            for prefix in _PATH_PREFIXES:
                if raw.startswith(prefix):
                    raw = raw[len(prefix) :]
                    explicit_context_ref = True
                    break
            raw = raw.strip(_EDGE_PUNCTUATION)
            if not raw:
                continue
            path = Path(raw).expanduser()
            try:
                if not path.exists():
                    continue
                resolved = path.resolve()
            except OSError:
                continue
            if explicit_context_ref and not inside_workspace_fence(resolved):
                continue
            if _path_has_supported_images(resolved):
                longest = resolved
                longest_end = end
        if longest is not None:
            found.append(longest)
            start = longest_end
        else:
            start += 1

    return _deduplicate_paths(found)


def _clean_token(token: str) -> str:
    return token.strip().strip(_EDGE_PUNCTUATION)


def _path_has_supported_images(path: Path) -> bool:
    if path.is_file():
        return detect_image_mime(path) is not None
    if path.is_dir():
        return bool(_images_in_folder(path))
    return False


def _images_in_folder(path: Path) -> list[Path]:
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return []
    return [
        child.resolve()
        for child in children
        if child.is_file() and detect_image_mime(child) is not None
    ]


def _resolve_selection(answer: str, images: list[Path]) -> Optional[Path]:
    normalized = (answer or "").strip()
    if not normalized:
        return None
    for image in images:
        if normalized in {str(image), image.name}:
            return image
    return None


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _encode_image(
    path: Path,
    *,
    max_image_bytes: int,
) -> tuple[Optional[ImageAttachment], Optional[str]]:
    if is_sensitive_path(path):
        return None, f"Blocked sensitive image path: {path}"
    mime_type = detect_image_mime(path)
    if mime_type is None:
        return None, f"Unsupported image format: {path}"
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, f"Could not inspect image {path}: {exc}"
    if size > max_image_bytes:
        return None, (
            f"Image is too large: {path} ({size} bytes; limit {max_image_bytes} bytes)."
        )
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as exc:
        return None, f"Could not read image {path}: {exc}"
    return (
        ImageAttachment(
            path=path,
            mime_type=mime_type,
            data_url=f"data:{mime_type};base64,{encoded}",
        ),
        None,
    )
