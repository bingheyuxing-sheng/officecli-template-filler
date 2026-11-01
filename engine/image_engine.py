"""
Safe Image Replacement & Package Media Integrity Engine (v3.0 — Fixes P0-3).

Guarantees DOCX image part integrity when replacing inline/anchored images (`a:blip`):
1. Inspects original `image_part.content_type` (MIME type) and partname extension.
2. Counts how many `<a:blip r:embed="...">` and relationships across the entire DOCX
   package reference the target `image_part` (shared resource detection).
3. Converts replacement image via Pillow (`PIL.Image`) to match the original MIME/format
   by default so `Content-Type` and file extension in `[Content_Types].xml` stay 100% valid.
4. If the original image part is shared by multiple drawings (`ref_count > 1`) OR a format
   change is explicitly requested, allocates a brand-new dedicated `ImagePart` + `rId`
   and updates ONLY the target `<a:blip r:embed="...">` so sibling images are never corrupted.
5. Provides `verify_docx_images_integrity(docx_path)` to re-open the saved `.docx` and confirm
   every media relationship, MIME type, and image binary decodes cleanly.
"""
from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
import docx
from docx.oxml.ns import qn
from PIL import Image

MIME_TO_PIL_FORMAT = {
    "image/png": ("PNG", ".png"),
    "image/jpeg": ("JPEG", ".jpg"),
    "image/jpg": ("JPEG", ".jpg"),
    "image/gif": ("GIF", ".gif"),
    "image/bmp": ("BMP", ".bmp"),
    "image/tiff": ("TIFF", ".tif"),
    "image/webp": ("WEBP", ".webp"),
}

PIL_FORMAT_TO_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
    "WEBP": "image/webp",
}


def _iter_story_parts(doc) -> List[Any]:
    """
    Yield every part that can own `<a:blip>` drawings, covering the whole package.

    Includes the main document part, headers/footers, footnotes, endnotes, comments and any other
    XML story part. Parts without an `element` (for example `ImagePart`) are skipped.
    """
    parts: List[Any] = []
    package = getattr(getattr(doc, "part", None), "package", None)
    if package is not None and hasattr(package, "iter_parts"):
        for part in package.iter_parts():
            if getattr(part, "element", None) is not None:
                parts.append(part)
    if not parts:
        # Fallback for older python-docx builds without `Package.iter_parts()`
        parts.append(doc.part)
        for section in doc.sections:
            for hf_attr in (
                "header", "first_page_header", "even_page_header",
                "footer", "first_page_footer", "even_page_footer",
            ):
                hf = getattr(section, hf_attr, None)
                if hf is not None:
                    try:
                        parts.append(hf.part)
                    except Exception:
                        pass
    return parts


def count_image_part_references(doc, target_partname: Optional[str] = None):
    """
    Count `<a:blip r:embed="...">` references across the entire DOCX package
    (body, headers, footers, footnotes, endnotes, comments).
    - When `target_partname` is provided (`str`), returns `int` (total references to that partname).
    - When `target_partname is None`, returns `Dict[str, Dict[str, Any]]` mapping each `rId` to
      `{"partname": str, "content_type": str, "ref_count": int}`.
    """
    ref_count = 0
    rid_summary: Dict[str, Dict[str, Any]] = {}
    partname_counts: Dict[str, int] = {}

    for part in _iter_story_parts(doc):
        for blip in part.element.xpath(".//a:blip"):
            r_id = blip.get(qn("r:embed"))
            if not r_id or r_id not in part.rels:
                continue
            rel = part.rels[r_id]
            if rel.is_external:
                continue
            target = rel.target_part
            pname = str(target.partname)
            ctype = str(getattr(target, "content_type", "") or "")
            partname_counts[pname] = partname_counts.get(pname, 0) + 1
            rid_summary[f"{part.partname}:{r_id}"] = {
                "partname": pname,
                "content_type": ctype,
                "ref_count": 0,
                "rId": r_id,
                "owner_part": str(part.partname),
            }
            if target_partname is not None and pname == str(target_partname):
                ref_count += 1

    if target_partname is not None:
        return ref_count

    for info in rid_summary.values():
        info["ref_count"] = partname_counts.get(info["partname"], 1)
    return rid_summary


def _encode_image_to_target_format(img_path: str, target_pil_fmt: str) -> bytes:
    """Load `img_path` via Pillow and encode to `target_pil_fmt` (handling RGBA->RGB for JPEG)."""
    with Image.open(img_path) as im:
        if target_pil_fmt == "JPEG" and im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            rgba = im.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            im = bg
        elif target_pil_fmt == "BMP" and im.mode == "RGBA":
            im = im.convert("RGB")
        buf = io.BytesIO()
        save_kwargs: Dict[str, Any] = {}
        if target_pil_fmt == "JPEG":
            save_kwargs["quality"] = 95
        im.save(buf, format=target_pil_fmt, **save_kwargs)
        return buf.getvalue()


def replace_inline_image_in_paragraph(
    doc,
    paragraph,
    new_image_path: str,
    blip_index: int = 0,
    preserve_original_format: bool = True,
) -> Dict[str, Any]:
    """
    Safely replace the inline/anchored image referenced by `<a:blip>` inside `paragraph` (fixes P0-3):
    1. Reads original `image_part.content_type` and checks reference count across the package.
    2. If `ref_count == 1` and `preserve_original_format=True` (and original format is raster-supported
       by Pillow), converts `new_image_path` into the exact original image format so MIME Content-Type
       and partname extension match 100%, then updates `_blob`.
    3. If `ref_count > 1` (shared image part) or format differs, adds a fresh dedicated image part via
       `doc.part.get_or_add_image(new_image_path)` and re-points ONLY `blips[blip_index]`'s `r:embed`
       attribute, keeping original `wp:extent` dimensions untouched.
    """
    blips = paragraph._p.xpath(".//a:blip")
    if not blips or blip_index >= len(blips):
        raise ValueError(f"No a:blip at index {blip_index} in target paragraph")

    target_blip = blips[blip_index]
    owner_part = getattr(paragraph, "part", doc.part)
    old_rId = target_blip.get(qn("r:embed"))
    if not old_rId or old_rId not in owner_part.rels:
        raise ValueError(f"Blip r:embed={old_rId!r} not found in part relationships")

    old_image_part = owner_part.related_parts[old_rId]
    orig_mime = (getattr(old_image_part, "content_type", "") or "").lower()
    orig_partname = str(getattr(old_image_part, "partname", ""))
    if not orig_mime.startswith("image/") or not hasattr(old_image_part, "_blob"):
        raise ValueError(
            f"r:embed={old_rId!r} does not point to an image part (content_type={orig_mime!r}). "
            f"Only raster/vector image parts can be replaced."
        )
    ref_count = count_image_part_references(doc, orig_partname)

    with Image.open(new_image_path) as src_im:
        src_pil_fmt = (src_im.format or "PNG").upper()
    src_mime = PIL_FORMAT_TO_MIME.get(src_pil_fmt, "image/png")

    with open(new_image_path, "rb") as f:
        raw_bytes = f.read()

    # Case A: Exclusive image part (ref_count <= 1) and original MIME is a standard Pillow-writable raster
    if ref_count <= 1 and preserve_original_format and orig_mime in MIME_TO_PIL_FORMAT:
        target_pil_fmt, _ext = MIME_TO_PIL_FORMAT[orig_mime]
        if src_pil_fmt == target_pil_fmt:
            new_blob = raw_bytes
        else:
            new_blob = _encode_image_to_target_format(new_image_path, target_pil_fmt)
        old_image_part._blob = new_blob
        return {
            "mode": "in_place_mime_matched",
            "effective": True,
            "allocated_new_part": False,
            "old_rId": old_rId,
            "new_rId": old_rId,
            "rId": old_rId,
            "partname": orig_partname,
            "content_type": orig_mime,
            "shared_ref_count": ref_count,
        }

    # Case B: Image part is shared by multiple drawings (ref_count > 1) OR format cannot be encoded in-place
    # Allocate a dedicated ImagePart via python-docx package image collection and rebind r:embed
    stream = io.BytesIO(raw_bytes)
    stream.name = new_image_path
    new_rId, _new_img = owner_part.get_or_add_image(stream)
    new_part = owner_part.related_parts[new_rId]

    if new_rId == old_rId:
        # python-docx de-duplicates image parts by SHA-1, so identical bytes legitimately reuse the
        # existing part. The image is already the requested one; report it instead of claiming a fork.
        return {
            "mode": "noop_identical_bytes",
            "effective": False,
            "allocated_new_part": False,
            "old_rId": old_rId,
            "new_rId": new_rId,
            "rId": new_rId,
            "partname": str(new_part.partname),
            "content_type": getattr(new_part, "content_type", src_mime),
            "shared_ref_count": ref_count,
        }

    target_blip.set(qn("r:embed"), new_rId)
    return {
        "mode": "isolated_new_part",
        "effective": True,
        "allocated_new_part": True,
        "old_rId": old_rId,
        "new_rId": new_rId,
        "rId": new_rId,
        "partname": str(new_part.partname),
        "content_type": getattr(new_part, "content_type", src_mime),
        "shared_ref_count": ref_count,
    }


def _declared_content_types(zf: zipfile.ZipFile) -> Dict[str, List[str]]:
    """
    Parse `[Content_Types].xml` and return `{"defaults": [ext...], "overrides": {partname: ctype}}`.
    """
    defaults: List[str] = []
    overrides: Dict[str, str] = {}
    try:
        root = ET.fromstring(zf.read("[Content_Types].xml"))
    except (KeyError, ET.ParseError):
        return {"defaults": defaults, "overrides": overrides, "parse_error": True}
    for node in root:
        local = node.tag.split("}")[-1]
        if local == "Default":
            defaults.append((node.get("Extension") or "").lower())
        elif local == "Override":
            overrides[(node.get("PartName") or "").lstrip("/")] = (node.get("ContentType") or "").lower()
    return {"defaults": defaults, "overrides": overrides, "parse_error": False}


def verify_docx_images_integrity(docx_path: str) -> Dict[str, Any]:
    """
    Re-open `docx_path` from disk and verify:
    1. Every `<a:blip r:embed="...">` in every XML story resolves to a valid relationship and part.
    2. Every image part can be decoded by Pillow and its actual binary format matches its declared MIME `content_type`.
    3. Every `word/media/*` entry in the archive — including parts no drawing references — is declared in
       `[Content_Types].xml` and its bytes match the declared MIME type.
    Returns `{"passed": bool, "checked_count": int, "issues": List[str]}`.
    """
    issues: List[str] = []
    checked_count = 0
    try:
        doc = docx.Document(docx_path)
    except Exception as exc:
        return {"passed": False, "checked_count": 0, "issues": [f"DOCX_REOPEN_FAILED: {exc}"]}

    parts_to_check = _iter_story_parts(doc)
    checked_partnames: set = set()

    for part in parts_to_check:
        el = getattr(part, "element", None)
        if el is None:
            continue
        for blip in el.xpath(".//a:blip"):
            r_id = blip.get(qn("r:embed"))
            if not r_id:
                continue
            checked_count += 1
            if r_id not in part.rels:
                issues.append(f"DANGLING_BLIP_RID {part.partname}: r:embed='{r_id}' missing in .rels")
                continue
            rel = part.rels[r_id]
            if rel.is_external:
                continue
            img_part = rel.target_part
            checked_partnames.add(str(img_part.partname))
            declared_mime = (getattr(img_part, "content_type", "") or "").lower()
            blob = getattr(img_part, "blob", b"")
            if not blob:
                issues.append(f"EMPTY_IMAGE_BLOB {img_part.partname} (rId={r_id})")
                continue
            if declared_mime in MIME_TO_PIL_FORMAT:
                expected_fmt, _ = MIME_TO_PIL_FORMAT[declared_mime]
                try:
                    with Image.open(io.BytesIO(blob)) as im:
                        im.verify()
                        actual_fmt = (im.format or "").upper()
                    if actual_fmt and actual_fmt != expected_fmt:
                        issues.append(
                            f"IMAGE_MIME_MISMATCH {img_part.partname}: declared='{declared_mime}' ({expected_fmt}), actual binary='{actual_fmt}'"
                        )
                except Exception as exc:
                    issues.append(f"CORRUPT_IMAGE_BINARY {img_part.partname}: {exc}")

    # Also verify zip archive integrity and every media entry's declared Content-Type
    try:
        with zipfile.ZipFile(docx_path, "r") as zf:
            bad_file = zf.testzip()
            if bad_file:
                issues.append(f"ZIP_CRC_ERROR: {bad_file}")

            content_types = _declared_content_types(zf)
            if content_types.get("parse_error"):
                issues.append("CONTENT_TYPES_UNPARSEABLE: [Content_Types].xml is missing or invalid")
            defaults = set(content_types["defaults"])
            overrides = content_types["overrides"]

            for name in zf.namelist():
                if "/media/" not in name or name.endswith("/"):
                    continue
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                declared = overrides.get(name, "")
                if not declared:
                    if ext not in defaults:
                        issues.append(f"MEDIA_CONTENT_TYPE_UNDECLARED: {name} (ext='{ext}')")
                        continue
                    declared = {
                        "png": "image/png",
                        "jpg": "image/jpeg",
                        "jpeg": "image/jpeg",
                        "gif": "image/gif",
                        "bmp": "image/bmp",
                        "tif": "image/tiff",
                        "tiff": "image/tiff",
                        "webp": "image/webp",
                    }.get(ext, "")
                if declared in MIME_TO_PIL_FORMAT:
                    expected_fmt, _ = MIME_TO_PIL_FORMAT[declared]
                    try:
                        with Image.open(io.BytesIO(zf.read(name))) as im:
                            actual_fmt = (im.format or "").upper()
                        if actual_fmt and actual_fmt != expected_fmt:
                            issues.append(
                                f"MEDIA_MIME_MISMATCH {name}: declared='{declared}' ({expected_fmt}), actual='{actual_fmt}'"
                            )
                    except Exception as exc:
                        issues.append(f"MEDIA_BINARY_UNREADABLE {name}: {exc}")
    except Exception as exc:
        issues.append(f"ZIP_OPEN_ERROR: {exc}")

    return {
        "passed": len(issues) == 0,
        "checked_count": checked_count,
        "checked_image_parts": len(checked_partnames),
        "issues": issues,
    }
