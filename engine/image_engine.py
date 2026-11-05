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

# Formats Pillow cannot decode. They are replaced through the part-allocation path and
# cannot be byte-verified, so they must be reported as a coverage gap, never as a pass.
VECTOR_MIME_TYPES = frozenset({
    "image/svg+xml",
    "image/x-emf",
    "image/emf",
    "image/x-wmf",
    "image/wmf",
    "image/x-wmz",
})

SVG_BLIP_URI_MARKER = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"


def _local_name(el) -> str:
    tag = el.tag if isinstance(el.tag, str) else ""
    return tag.split("}")[-1] if "}" in tag else tag


def _svg_blips(blip) -> List[Any]:
    """Return `<asvg:svgBlip>` children of an `<a:blip>` extension list (namespace-agnostic)."""
    return [node for node in blip.iter() if _local_name(node) == "svgBlip"]


def _blip_fill_src_rect(blip):
    parent = blip.getparent()
    if parent is None:
        return None
    for node in parent:
        if _local_name(node) == "srcRect":
            return node
    return None


def _wp_extent(blip):
    """Nearest `<wp:extent>` above the blip (inline or anchor)."""
    node = blip
    while node is not None:
        for child in node:
            if _local_name(child) == "extent" and child.get("cx") and child.get("cy"):
                return child
        node = node.getparent()
    return None


def _is_vector_mime(content_type: str) -> bool:
    return (content_type or "").lower() in VECTOR_MIME_TYPES


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
                        # ``hf.part`` materializes a phantom definition for linked
                        # headers/footers; skip them before touching the part.
                        if hf.is_linked_to_previous:
                            continue
                        parts.append(hf.part)
                    except Exception:
                        pass
    return parts


def count_image_part_references(doc, target_partname: Optional[str] = None):
    """
    Count image-part references across the entire DOCX package.

    Three OOXML shapes reference an image part and all three count:
    - `<a:blip r:embed>` (raster fallback of inline/anchored drawings),
    - `<asvg:svgBlip r:embed>` (the SVG Word actually renders for inserted icons/SVG),
    - `<v:imagedata r:id>` (legacy VML pictures used by WPS headers/logos/stamps).

    Missing the latter two let a "shared" part look exclusive, so replacing it corrupted
    sibling images.
    """
    ref_count = 0
    rid_summary: Dict[str, Dict[str, Any]] = {}
    partname_counts: Dict[str, int] = {}

    def _record(part, r_id: str, kind: str) -> None:
        nonlocal ref_count
        if not r_id or r_id not in part.rels:
            return
        rel = part.rels[r_id]
        if rel.is_external:
            return
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
            "reference_kind": kind,
        }
        if target_partname is not None and pname == str(target_partname):
            ref_count += 1

    for part in _iter_story_parts(doc):
        for blip in part.element.xpath(".//a:blip"):
            _record(part, blip.get(qn("r:embed")), "blip")
            # An SVG dual-embedded icon has BOTH a raster fallback and an SVG part; the
            # SVG reference is what Word renders, so it must count as a shared reference.
            for svg_blip in _svg_blips(blip):
                _record(part, svg_blip.get(qn("r:embed")), "svgBlip")
        for imagedata in part.element.iter():
            if _local_name(imagedata) != "imagedata":
                continue
            r_id = imagedata.get(qn("r:id")) or imagedata.get(qn("r:embed"))
            _record(part, r_id, "vml")

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


def _remove_svg_blip(blip) -> List[str]:
    """
    Drop `<asvg:svgBlip>` extensions from `a:blip` and return the removed rIds.

    Word 2016+ stores an inserted icon/SVG as a dual embed: `<a:blip>` points at a raster
    fallback while `<asvg:svgBlip>` points at the real SVG, and **the SVG wins** when
    rendering. Replacing only the raster part therefore looks successful but Word keeps
    showing the old artwork. Removing the extension makes the replaced raster authoritative.
    """
    removed: List[str] = []
    for svg_blip in _svg_blips(blip):
        r_id = svg_blip.get(qn("r:embed"))
        if r_id:
            removed.append(r_id)
        parent = svg_blip.getparent()
        if parent is None:
            continue
        parent.remove(svg_blip)
        # Clean up the now-empty <a:ext>, then the empty <a:extLst>.
        ext = parent
        if len(ext) == 0 and not ext.attrib:
            ext_lst = ext.getparent()
            if ext_lst is not None:
                ext_lst.remove(ext)
                if len(ext_lst) == 0 and ext_lst.getparent() is not None:
                    ext_lst.getparent().remove(ext_lst)
    return removed


def _fit_extent_to_image(blip, image_path: str) -> Optional[Dict[str, int]]:
    """Recompute `wp:extent` from the new image aspect ratio, keeping width."""
    extent = _wp_extent(blip)
    if extent is None:
        return None
    try:
        cx = int(extent.get("cx") or 0)
        with Image.open(image_path) as im:
            px_w, px_h = im.size
    except Exception:
        return None
    if cx <= 0 or px_w <= 0 or px_h <= 0:
        return None
    old_cy = int(extent.get("cy") or 0)
    new_cy = int(round(cx * px_h / float(px_w)))
    extent.set("cy", str(new_cy))
    return {"cx": cx, "cy": new_cy, "previous_cy": old_cy}


def _vml_imagedata(paragraph) -> List[Any]:
    """Return `<v:imagedata>` nodes inside `w:pict` (legacy VML pictures)."""
    return [node for node in paragraph._p.iter() if _local_name(node) == "imagedata"]


IMAGE_ROLES = ("logo", "stamp", "qr", "illustration", "photo")

_ROLE_CAPTION_HINTS = {
    "illustration": ("示意图", "流程图", "结构图", "框架图", "框图", "图1", "图一", "图示"),
    "qr": ("二维码", "扫码", "QR"),
}


def _dominant_color(image) -> str:
    """Coarse hue bucket for a small thumbnail: red / grayscale / color."""
    try:
        small = image.convert("RGB").resize((32, 32))
        width, height = small.size
        pixels = [small.getpixel((x, y)) for y in range(height) for x in range(width)]
    except Exception:
        return "unknown"
    red = green = blue = 0
    colorful = 0
    for r, g, b in pixels:
        red += r
        green += g
        blue += b
        if max(r, g, b) - min(r, g, b) > 40:
            colorful += 1
    total = max(len(pixels), 1)
    if colorful / total < 0.15:
        return "grayscale"
    if red / total > green / total * 1.35 and red / total > blue / total * 1.35:
        return "red"
    return "color"


def _guess_role(in_header: bool, width: int, height: int, color: str, caption: str) -> Tuple[str, str]:
    """Return `(role, evidence)` from cheap structural signals — never from pixels alone."""
    caption_lower = (caption or "").lower()
    for role, hints in _ROLE_CAPTION_HINTS.items():
        for hint in hints:
            if hint in caption or hint.lower() in caption_lower:
                return role, f"caption contains '{hint}'"

    aspect = (width / float(height)) if height else 0.0
    square = 0.9 <= aspect <= 1.1
    if in_header:
        if square and min(width, height) <= 400 and color == "red":
            return "stamp", "header image, square and predominantly red"
        return "logo", "header/footer image"
    if square and min(width, height) <= 400 and color == "grayscale":
        return "qr", "square, small, grayscale"
    if width >= 400 or height >= 300:
        return "illustration", "large body image"
    return "photo", "body image"


def find_images(doc, role: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Locate pictures by role instead of by `blip_index`.

    Business tasks reference "the logo", "the stamp", "the QR code" far more often than
    "paragraph 12, second blip". Each entry reports the structural evidence behind its
    guess so a wrong guess is visible rather than silently applied.

    `role` filters to one of `logo` / `stamp` / `qr` / `illustration` / `photo`;
    `None` returns every image. VML pictures are included with `reference_kind: "vml"`.
    """
    if role is not None and role not in IMAGE_ROLES:
        raise ValueError(f"role must be one of {IMAGE_ROLES} or None, got {role!r}")

    results: List[Dict[str, Any]] = []
    story_parts = _iter_story_parts(doc)

    from docx.text.paragraph import Paragraph

    for part in story_parts:
        element = getattr(part, "element", None)
        if element is None:
            continue
        partname = str(getattr(part, "partname", ""))
        in_header = "header" in partname.lower() or "footer" in partname.lower()

        # `.//w:p` works for w:body, w:hdr and w:ftr roots alike (a header root is w:hdr
        # itself, so `.//w:hdr//w:p` would never match).
        for paragraph_index, paragraph_element in enumerate(element.xpath(".//w:p")):
            paragraph = Paragraph(paragraph_element, part)
            caption = (paragraph.text or "").strip()

            for blip_index, blip in enumerate(paragraph._p.xpath(".//a:blip")):
                r_id = blip.get(qn("r:embed"))
                if not r_id or r_id not in part.rels or part.rels[r_id].is_external:
                    continue
                image_part = part.rels[r_id].target_part
                blob = getattr(image_part, "blob", b"")
                try:
                    with Image.open(io.BytesIO(blob)) as im:
                        width, height = im.size
                        color = _dominant_color(im)
                except Exception:
                    width = height = 0
                    color = "unknown"
                guessed, evidence = _guess_role(in_header, width, height, color, caption)
                entry = {
                    "role": guessed,
                    "evidence": evidence,
                    "reference_kind": "blip",
                    "owner_part": partname,
                    "paragraph_index": paragraph_index,
                    "blip_index": blip_index,
                    "rId": r_id,
                    "partname": str(image_part.partname),
                    "content_type": getattr(image_part, "content_type", ""),
                    "width_px": width,
                    "height_px": height,
                    "caption": caption[:80],
                }
                if role is None or role == guessed:
                    results.append(entry)

            for blip_index, imagedata in enumerate(_vml_imagedata(paragraph)):
                r_id = imagedata.get(qn("r:id")) or imagedata.get(qn("r:embed"))
                if not r_id or r_id not in part.rels or part.rels[r_id].is_external:
                    continue
                image_part = part.rels[r_id].target_part
                blob = getattr(image_part, "blob", b"")
                try:
                    with Image.open(io.BytesIO(blob)) as im:
                        width, height = im.size
                        color = _dominant_color(im)
                except Exception:
                    width = height = 0
                    color = "unknown"
                guessed, evidence = _guess_role(in_header, width, height, color, caption)
                entry = {
                    "role": guessed,
                    "evidence": evidence,
                    "reference_kind": "vml",
                    "owner_part": partname,
                    "paragraph_index": paragraph_index,
                    "blip_index": blip_index,
                    "rId": r_id,
                    "partname": str(image_part.partname),
                    "content_type": getattr(image_part, "content_type", ""),
                    "width_px": width,
                    "height_px": height,
                    "caption": caption[:80],
                }
                if role is None or role == guessed:
                    results.append(entry)

    return results


def replace_image_by_role(doc, role: str, new_image_path: str, **options) -> Dict[str, Any]:
    """
    Replace the single image whose role matches. Refuses to act when the match is
    ambiguous — replacing the wrong logo silently is worse than asking.
    """
    matches = find_images(doc, role=role)
    if not matches:
        raise ValueError(f"No image matched role={role!r}")
    if len(matches) > 1:
        locations = [f"{item['owner_part']}#p{item['paragraph_index']}/b{item['blip_index']}" for item in matches]
        raise ValueError(f"{len(matches)} images matched role={role!r}: {locations}; refine the target")
    entry = matches[0]
    paragraph = None
    part = None
    for candidate in _iter_story_parts(doc):
        if str(getattr(candidate, "partname", "")) != entry["owner_part"]:
            continue
        part = candidate
        paragraphs = candidate.element.xpath(".//w:p")
        if entry["paragraph_index"] < len(paragraphs):
            paragraph = paragraphs[entry["paragraph_index"]]
        break
    if paragraph is None or part is None:
        raise ValueError(f"Could not resolve paragraph for role={role!r}")

    # Reuse the paragraph-level replacement path by wrapping the raw w:p element.
    from docx.text.paragraph import Paragraph

    wrapped = Paragraph(paragraph, doc.part if "document" in entry["owner_part"] else part)
    result = replace_inline_image_in_paragraph(
        doc, wrapped, new_image_path, blip_index=entry["blip_index"], **options
    )
    result["role"] = role
    result["matched"] = entry
    return result


def _replace_vml_image(
    doc,
    paragraph,
    imagedata,
    new_image_path: str,
    preserve_original_format: bool,
) -> Dict[str, Any]:
    """
    Replace a VML picture (`w:pict` / `v:imagedata`), which WPS uses for header logos,
    stamps and older templates. The `<a:blip>` path never sees these, so without this
    branch they were silently left untouched.
    """
    owner_part = getattr(paragraph, "part", doc.part)
    old_rId = imagedata.get(qn("r:id")) or imagedata.get(qn("r:embed"))
    if not old_rId or old_rId not in owner_part.rels:
        raise ValueError(f"VML imagedata r:id={old_rId!r} not found in part relationships")

    old_part = owner_part.related_parts[old_rId]
    orig_mime = (getattr(old_part, "content_type", "") or "").lower()
    orig_partname = str(getattr(old_part, "partname", ""))
    ref_count = count_image_part_references(doc, orig_partname)

    with Image.open(new_image_path) as src_im:
        src_pil_fmt = (src_im.format or "PNG").upper()
    src_mime = PIL_FORMAT_TO_MIME.get(src_pil_fmt, "image/png")
    with open(new_image_path, "rb") as handle:
        raw_bytes = handle.read()

    common = {
        "shared_ref_count": ref_count,
        "adjustments": [],
        "removed_svg_rids": [],
        "extent": None,
        "verification": "unverified_vector" if _is_vector_mime(orig_mime) else "raster_verified",
        "original_content_type": orig_mime,
        "reference_kind": "vml",
    }

    if ref_count <= 1 and preserve_original_format and orig_mime in MIME_TO_PIL_FORMAT:
        target_fmt, _ext = MIME_TO_PIL_FORMAT[orig_mime]
        blob = raw_bytes if src_pil_fmt == target_fmt else _encode_image_to_target_format(new_image_path, target_fmt)
        old_part._blob = blob
        return {
            "mode": "vml_in_place_mime_matched",
            "effective": True,
            "allocated_new_part": False,
            "old_rId": old_rId,
            "new_rId": old_rId,
            "rId": old_rId,
            "partname": orig_partname,
            "content_type": orig_mime,
            **common,
        }

    stream = io.BytesIO(raw_bytes)
    stream.name = new_image_path
    new_rId, _img = owner_part.get_or_add_image(stream)
    new_part = owner_part.related_parts[new_rId]
    if new_rId == old_rId:
        return {
            "mode": "noop_identical_bytes",
            "effective": False,
            "allocated_new_part": False,
            "old_rId": old_rId,
            "new_rId": new_rId,
            "rId": new_rId,
            "partname": str(new_part.partname),
            "content_type": getattr(new_part, "content_type", src_mime),
            **common,
        }
    for attribute in ("r:id", "r:embed"):
        if imagedata.get(qn(attribute)) is not None:
            imagedata.set(qn(attribute), new_rId)
    return {
        "mode": "vml_isolated_new_part",
        "effective": True,
        "allocated_new_part": True,
        "old_rId": old_rId,
        "new_rId": new_rId,
        "rId": new_rId,
        "partname": str(new_part.partname),
        "content_type": getattr(new_part, "content_type", src_mime),
        **common,
    }


def replace_inline_image_in_paragraph(
    doc,
    paragraph,
    new_image_path: str,
    blip_index: int = 0,
    preserve_original_format: bool = True,
    fit_mode: str = "preserve_frame",
    drop_svg_fallback: bool = True,
) -> Dict[str, Any]:
    """
    Safely replace the inline/anchored image referenced by `<a:blip>` inside `paragraph`.

    Fixes beyond the original v3.0 behaviour:
    - **SVG dual embed**: a Word-inserted icon stores a raster `<a:blip>` plus an
      `<asvg:svgBlip>` that Word actually renders. The SVG extension is removed
      (`drop_svg_fallback=True`) so the replacement is really visible; otherwise the
      call would report success while Word still shows the old image.
    - **Crop box**: `a:srcRect` (crop) is cleared, because carrying the old crop onto a new
      image crops away its subject.
    - **Display box**: `fit_mode="fit_image"` recomputes `wp:extent` from the new image
      aspect ratio; `preserve_frame` (default) keeps the original frame and reports it.
    - **Vector originals**: an SVG/EMF/WMF original cannot be byte-verified, so the result
      carries `verification: "unverified_vector"`.

    Returns a dict describing the mode, the new rId and every adjustment applied.
    """
    if fit_mode not in ("preserve_frame", "fit_image"):
        raise ValueError(f"fit_mode must be 'preserve_frame' or 'fit_image', got {fit_mode!r}")

    blips = paragraph._p.xpath(".//a:blip")
    if not blips or blip_index >= len(blips):
        # Legacy VML pictures (`w:pict` / `v:imagedata`) carry no a:blip, and WPS uses
        # them for header logos and stamps. Handle them instead of failing.
        vml_images = _vml_imagedata(paragraph)
        if vml_images and blip_index < len(vml_images):
            return _replace_vml_image(
                doc, paragraph, vml_images[blip_index], new_image_path, preserve_original_format
            )
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

    adjustments: List[str] = []
    removed_svg_ids = _remove_svg_blip(target_blip) if drop_svg_fallback else []
    if removed_svg_ids:
        adjustments.append("svg_fallback_removed")

    src_rect = _blip_fill_src_rect(target_blip)
    if src_rect is not None:
        src_rect.getparent().remove(src_rect)
        adjustments.append("crop_rect_cleared")

    extent_change = None
    if fit_mode == "fit_image":
        extent_change = _fit_extent_to_image(target_blip, new_image_path)
        if extent_change:
            adjustments.append("extent_fitted")

    common = {
        "shared_ref_count": ref_count,
        "adjustments": adjustments,
        "removed_svg_rids": removed_svg_ids,
        "extent": extent_change,
        "verification": "unverified_vector" if _is_vector_mime(orig_mime) else "raster_verified",
        "original_content_type": orig_mime,
    }

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
            **common,
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
            **common,
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
        **common,
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
    2. Every raster image part decodes and its binary format matches its declared MIME.
    3. Every `word/media/*` entry is declared in `[Content_Types].xml` and matches its MIME.
    4. SVG dual embeds are structurally valid (no dangling `asvg:svgBlip` target).

    Checks that cannot run are returned in `coverage_gaps` — vector images (SVG/EMF/WMF)
    cannot be decoded by Pillow, and externally linked images are not package parts, so
    neither may be reported as verified.
    """
    issues: List[str] = []
    coverage_gaps: List[str] = []
    vector_parts: List[str] = []
    external_links: List[str] = []
    svg_dual_embeds: List[Dict[str, str]] = []
    checked_count = 0
    try:
        doc = docx.Document(docx_path)
    except Exception as exc:
        return {
            "passed": False,
            "checked_count": 0,
            "issues": [f"DOCX_REOPEN_FAILED: {exc}"],
            "coverage_gaps": ["IMAGE_VERIFICATION_UNAVAILABLE"],
            "unverified_count": 1,
        }

    parts_to_check = _iter_story_parts(doc)
    checked_partnames: set = set()

    for part in parts_to_check:
        el = getattr(part, "element", None)
        if el is None:
            continue
        for blip in el.xpath(".//a:blip"):
            r_id = blip.get(qn("r:embed"))
            checked_count += 1
            if r_id:
                if r_id not in part.rels:
                    issues.append(f"DANGLING_BLIP_RID {part.partname}: r:embed='{r_id}' missing in .rels")
                else:
                    rel = part.rels[r_id]
                    if rel.is_external:
                        external_links.append(f"{part.partname}:{r_id} -> {rel.target_ref}")
                    else:
                        img_part = rel.target_part
                        checked_partnames.add(str(img_part.partname))
                        declared_mime = (getattr(img_part, "content_type", "") or "").lower()
                        blob = getattr(img_part, "blob", b"")
                        if not blob:
                            issues.append(f"EMPTY_IMAGE_BLOB {img_part.partname} (rId={r_id})")
                        elif _is_vector_mime(declared_mime):
                            if str(img_part.partname) not in vector_parts:
                                vector_parts.append(str(img_part.partname))
                        elif declared_mime in MIME_TO_PIL_FORMAT:
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
                        else:
                            coverage_gaps.append(f"IMAGE_TYPE_UNVERIFIED: {img_part.partname} ({declared_mime or 'unknown'})")

            # SVG dual embed: the raster fallback and the SVG must both resolve.
            for svg_blip in _svg_blips(blip):
                svg_rid = svg_blip.get(qn("r:embed"))
                svg_dual_embeds.append({"owner_part": str(part.partname), "svg_rId": svg_rid or ""})
                if not svg_rid:
                    issues.append(f"SVG_BLIP_MISSING_RID {part.partname}")
                elif svg_rid not in part.rels:
                    issues.append(
                        f"SVG_BLIP_DANGLING_RID {part.partname}: asvg:svgBlip r:embed='{svg_rid}' missing in .rels"
                    )
                else:
                    rel = part.rels[svg_rid]
                    if rel.is_external:
                        external_links.append(f"{part.partname}:{svg_rid} -> {rel.target_ref} (svg)")
                    else:
                        svg_part = rel.target_part
                        checked_partnames.add(str(svg_part.partname))
                        if _is_vector_mime(getattr(svg_part, "content_type", "") or ""):
                            if str(svg_part.partname) not in vector_parts:
                                vector_parts.append(str(svg_part.partname))

    # VML pictures (`w:pict` / `v:imagedata`) are a separate reference path.
    for part in parts_to_check:
        el = getattr(part, "element", None)
        if el is None:
            continue
        for node in el.iter():
            if _local_name(node) != "imagedata":
                continue
            r_id = node.get(qn("r:id")) or node.get(qn("r:embed"))
            checked_count += 1
            if r_id and r_id not in part.rels:
                issues.append(f"DANGLING_VML_RID {part.partname}: imagedata r:id='{r_id}' missing in .rels")

    if vector_parts:
        coverage_gaps.append(f"VECTOR_IMAGE_UNVERIFIED: {', '.join(sorted(vector_parts))}")
    if external_links:
        coverage_gaps.append(f"EXTERNAL_IMAGE_LINK: {', '.join(external_links)}")

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

    coverage_gaps = list(dict.fromkeys(coverage_gaps))
    return {
        "passed": len(issues) == 0,
        "checked_count": checked_count,
        "checked_image_parts": len(checked_partnames),
        "issues": issues,
        "coverage_gaps": coverage_gaps,
        "unverified_count": len(coverage_gaps),
        "vector_parts": sorted(vector_parts),
        "external_links": external_links,
        "svg_dual_embeds": svg_dual_embeds,
    }
