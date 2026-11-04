# -*- coding: utf-8 -*-
"""Optional OCR adapter for text painted inside pictures.

The engine itself has no OCR. When a backend happens to be installed
(`rapidocr_onnxruntime`, `paddleocr`, or `pytesseract` + the `tesseract` binary) this
module extracts image text so placeholder residue such as `***`, `XXXX` or another
major's examples can be detected. When no backend exists the caller receives an explicit
`OCR_UNAVAILABLE` coverage gap — never a silent pass.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import tempfile
import zipfile
from typing import Any, Callable, Dict, List, Optional, Sequence

DEFAULT_PLACEHOLDER_PATTERNS = (
    r"\*{3,}",
    r"[Xx]{3,}",
    r"_{3,}",
    r"待填写",
    r"示例文本",
    r"此处插入",
)

_BACKEND_ORDER = ("rapidocr", "paddleocr", "tesseract")


def _rapidocr_reader() -> Optional[Callable]:
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        engine = RapidOCR()
        return lambda path: engine(path)
    except Exception:
        return None


def _paddleocr_reader() -> Optional[Callable]:
    try:
        from paddleocr import PaddleOCR  # type: ignore

        engine = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)
        return lambda path: engine.ocr(path, cls=False)
    except Exception:
        return None


def _tesseract_reader() -> Optional[Callable]:
    if not shutil.which("tesseract"):
        return None
    try:
        import pytesseract  # type: ignore
        from PIL import Image
    except Exception:
        return None
    return lambda path: pytesseract.image_to_string(Image.open(path), lang="chi_sim+eng")


def detect_ocr_backend() -> Dict[str, Any]:
    """Return `{"name": ..., "reader": callable|None, "reason": ...}` for the first usable backend."""
    for name in _BACKEND_ORDER:
        if name == "rapidocr":
            reader = _rapidocr_reader()
        elif name == "paddleocr":
            reader = _paddleocr_reader()
        else:
            reader = _tesseract_reader()
        if reader is not None:
            return {"name": name, "reader": reader, "reason": None}
    return {"name": "none", "reader": None, "reason": "OCR_UNAVAILABLE"}


def _flatten_result(raw: Any) -> str:
    """Normalize the three backends' wildly different return shapes into plain text."""
    lines: List[str] = []
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, tuple):
        # RapidOCR returns (results, elapsed); results is a list of [box, text, score].
        for item in raw:
            text = _flatten_result(item)
            if text:
                lines.append(text)
        return "\n".join(lines)
    if isinstance(raw, list):
        for item in raw:
            # RapidOCR: [box, text, score]
            if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[1], str):
                lines.append(item[1])
            elif isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[1], (list, tuple)) and item[1] and isinstance(item[1][0], str):
                lines.append(item[1][0])
            elif isinstance(item, (list, tuple)) and item and isinstance(item[0], str):
                lines.append(item[0])
            else:
                text = _flatten_result(item)
                if text:
                    lines.append(text)
        return "\n".join(lines)
    if isinstance(raw, dict):
        for value in raw.values():
            text = _flatten_result(value)
            if text:
                lines.append(text)
        return "\n".join(lines)
    return ""


def ocr_image(image_path: str, reader: Optional[Callable] = None) -> Dict[str, Any]:
    """Run OCR on one image file and return `{"text", "backend", "error"}`."""
    backend = detect_ocr_backend() if reader is None else {"name": "injected", "reader": reader}
    if backend.get("reader") is None:
        return {"text": "", "backend": backend.get("name", "none"), "error": "OCR_UNAVAILABLE"}
    try:
        text = _flatten_result(backend["reader"](image_path))
    except Exception as exc:
        return {"text": "", "backend": backend.get("name", "none"), "error": f"{type(exc).__name__}: {exc}"}
    return {"text": text, "backend": backend.get("name", "none"), "error": None}


def find_placeholder_text(text: str, patterns: Sequence[str] = DEFAULT_PLACEHOLDER_PATTERNS) -> List[str]:
    hits: List[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text or ""):
            hits.append(match.group(0))
    return hits


def audit_image_text(
    docx_path: str,
    patterns: Sequence[str] = DEFAULT_PLACEHOLDER_PATTERNS,
    reader: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    OCR every `word/media/*` picture and report placeholder residue found inside it.

    Returns `passed`, `issues` (`PLACEHOLDER_TEXT_IN_IMAGE`, medium because the picture is
    evidence a human should look at), `images`, and `coverage_gaps`.
    """
    backend = detect_ocr_backend() if reader is None else {"name": "injected", "reader": reader, "reason": None}
    if backend.get("reader") is None:
        return {
            "passed": True,
            "issued_count": 0,
            "issues": [],
            "structured_issues": [],
            "images": [],
            "backend": "none",
            "coverage_gaps": ["OCR_UNAVAILABLE"],
            "unverified_count": 1,
        }

    images: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    gaps: List[str] = []

    try:
        archive = zipfile.ZipFile(docx_path, "r")
    except Exception as exc:
        return {
            "passed": False,
            "issues": [{"code": "OCR_INPUT_UNREADABLE", "location": "package", "detail": str(exc), "severity": "high"}],
            "structured_issues": [{"code": "OCR_INPUT_UNREADABLE", "location": "package", "detail": str(exc), "severity": "high"}],
            "images": [],
            "backend": backend.get("name"),
            "coverage_gaps": ["OCR_UNAVAILABLE"],
            "unverified_count": 1,
        }

    with archive:
        media = [name for name in archive.namelist() if "/media/" in name and not name.endswith("/")]
        for name in media:
            extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if extension in ("svg", "emf", "wmf", "wmz"):
                gaps.append(f"VECTOR_IMAGE_OCR_UNSUPPORTED: {name}")
                continue
            try:
                from PIL import Image  # local import: OCR is optional

                with Image.open(io.BytesIO(archive.read(name))) as image:
                    temp_dir = tempfile.mkdtemp(prefix="office_ocr_")
                    temp_png = os.path.join(temp_dir, f"image_{len(images)}.png")
                    image.convert("RGB").save(temp_png, format="PNG")
                try:
                    result = ocr_image(temp_png, backend["reader"])
                finally:
                    try:
                        os.remove(temp_png)
                        os.rmdir(temp_dir)
                    except OSError:
                        pass
            except Exception as exc:
                gaps.append(f"IMAGE_OCR_FAILED: {name} ({type(exc).__name__})")
                continue

            if result.get("error"):
                gaps.append(f"IMAGE_OCR_FAILED: {name} ({result['error']})")
                continue
            text = (result.get("text") or "").strip()
            hits = find_placeholder_text(text, patterns)
            images.append({"partname": name, "text": text[:2000], "placeholder_hits": hits})
            if hits:
                issues.append({
                    "code": "PLACEHOLDER_TEXT_IN_IMAGE",
                    "location": name,
                    "detail": f"image text contains placeholder residue {sorted(set(hits))}: {text[:120]!r}",
                    "severity": "medium",
                })

    return {
        "passed": not issues,
        "issued_count": len(issues),
        "issues": issues,
        "structured_issues": issues,
        "images": images,
        "backend": backend.get("name"),
        "coverage_gaps": gaps,
        "unverified_count": len(gaps),
    }
