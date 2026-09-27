import base64

import pytest

from astra_claw import constants
from astra_claw.cli.image_attachments import (
    detect_image_mime,
    prepare_image_prompt,
)


IMAGE_BYTES = {
    "image.png": b"\x89PNG\r\n\x1a\n" + b"png-data",
    "image.jpg": b"\xff\xd8\xff" + b"jpeg-data",
    "image.gif": b"GIF89a" + b"gif-data",
    "image.webp": b"RIFF\x08\x00\x00\x00WEBP" + b"webp-data",
}


@pytest.mark.parametrize(
    ("filename", "expected_mime"),
    [
        ("image.png", "image/png"),
        ("image.jpg", "image/jpeg"),
        ("image.gif", "image/gif"),
        ("image.webp", "image/webp"),
    ],
)
def test_detect_image_mime_uses_file_signature(tmp_path, filename, expected_mime):
    path = tmp_path / filename
    path.write_bytes(IMAGE_BYTES[filename])

    assert detect_image_mime(path) == expected_mime


def test_direct_image_path_becomes_multimodal_content(tmp_path):
    image = tmp_path / "photo.bin"
    image.write_bytes(IMAGE_BYTES["image.png"])

    prepared = prepare_image_prompt(f"Tell me what is in {image}")

    assert prepared.image_paths == (image.resolve(),)
    assert prepared.content[0]["type"] == "text"
    assert str(image.resolve()) in prepared.content[0]["text"]
    image_url = prepared.content[1]["image_url"]["url"]
    prefix, encoded = image_url.split(",", maxsplit=1)
    assert prefix == "data:image/png;base64"
    assert base64.b64decode(encoded) == IMAGE_BYTES["image.png"]


def test_folder_with_one_image_attaches_automatically(tmp_path):
    folder = tmp_path / "photo folder"
    folder.mkdir()
    image = folder / "only.jpg"
    image.write_bytes(IMAGE_BYTES["image.jpg"])

    prepared = prepare_image_prompt(f"Can you inspect {folder} and explain it?")

    assert prepared.image_paths == (image.resolve(),)
    assert prepared.warnings == ()


def test_folder_with_multiple_images_asks_selector(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    first = folder / "a.png"
    second = folder / "b.jpg"
    first.write_bytes(IMAGE_BYTES["image.png"])
    second.write_bytes(IMAGE_BYTES["image.jpg"])
    calls = []

    def select(question, choices):
        calls.append((question, choices))
        return choices[1]

    prepared = prepare_image_prompt(
        f"Read {folder}",
        selector=select,
    )

    assert prepared.image_paths == (second.resolve(),)
    assert len(calls) == 1
    assert str(first.resolve()) in calls[0][1]
    assert str(second.resolve()) in calls[0][1]


def test_ambiguous_folder_without_selector_returns_warning(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    (folder / "a.png").write_bytes(IMAGE_BYTES["image.png"])
    (folder / "b.jpg").write_bytes(IMAGE_BYTES["image.jpg"])

    prepared = prepare_image_prompt(f"Read {folder}")

    assert prepared.content == f"Read {folder}"
    assert prepared.image_paths == ()
    assert "Multiple images found" in prepared.warnings[0]


def test_image_over_size_limit_is_not_attached(tmp_path):
    image = tmp_path / "large.png"
    image.write_bytes(IMAGE_BYTES["image.png"])

    prepared = prepare_image_prompt(
        f"Read {image}",
        max_image_bytes=4,
    )

    assert prepared.image_paths == ()
    assert "too large" in prepared.warnings[0]


def test_sensitive_image_path_is_blocked(tmp_path):
    image = tmp_path / ".env"
    image.write_bytes(IMAGE_BYTES["image.png"])

    prepared = prepare_image_prompt(f"Read {image}")

    assert prepared.image_paths == ()
    assert "Blocked sensitive image path" in prepared.warnings[0]


def test_sensitive_image_inside_folder_is_blocked(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    (folder / ".env").write_bytes(IMAGE_BYTES["image.png"])

    prepared = prepare_image_prompt(f"Read {folder}")

    assert prepared.image_paths == ()
    assert "Blocked sensitive image path" in prepared.warnings[0]


def test_unsupported_file_does_not_change_text_prompt(tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("hello", encoding="utf-8")
    prompt = f"Read {file_path}"

    prepared = prepare_image_prompt(prompt)

    assert prepared.content == prompt
    assert prepared.image_paths == ()
    assert prepared.warnings == ()


def test_explicit_file_ref_keeps_workspace_fence(tmp_path, monkeypatch):
    inside = tmp_path / "inside"
    outside = tmp_path / "outside"
    inside.mkdir()
    outside.mkdir()
    image = outside / "photo.png"
    image.write_bytes(IMAGE_BYTES["image.png"])
    monkeypatch.chdir(inside)
    constants.set_workspace_fence(inside)
    try:
        prepared = prepare_image_prompt(f"Read @file:{image}")
    finally:
        constants._workspace_fence = None

    assert prepared.image_paths == ()
    assert prepared.content == f"Read @file:{image}"
