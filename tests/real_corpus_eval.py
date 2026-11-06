# -*- coding: utf-8 -*-
"""W3-9: real-template corpus evaluation harness.

The corpus directory is supplied at runtime via ``--corpus``; no path, file
name, or corpus fact is ever embedded in the repository.  The harness

1. copies every ``.docx`` into an isolated temp workspace (originals stay
   byte-identical, verified by SHA-256 before/after),
2. runs the documented v4 entry point ``analyze_template.py --spec-version 4``
   per file with a hard timeout,
3. runs a fill smoke test on a bounded sample of parseable templates that
   expose at least one FILLABLE token slot, using the documented plan chain
   (analyze -> validate -> ContentPlan/FillPlan -> generate_document), and
4. aggregates robustness metrics into JSON + Markdown reports.

Per task-book rule E3, no annotation baseline exists for this corpus, so no
slot precision/recall/F1 is computed or claimed.  Reports contain anonymous
IDs, technical metadata and aggregate metrics only; document text content is
never copied into reports.

Usage:
    py -3.15 tests/real_corpus_eval.py --corpus "<path-to-docx-dir>" \
        [--out reports/w3/real-corpus-eval.json] \
        [--report reports/w3/real-corpus-eval.md] \
        [--timeout 120] [--fill-sample 6] [--limit 0]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import docx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_intelligence import build_content_plan, build_fill_plan  # noqa: E402
from gate_helpers import ensure_gate  # noqa: E402
from template_intelligence.spec_validator import validate_document_spec  # noqa: E402

FILL_VALUE = "评测值"  # short on purpose: minimizes capacity-conflict rejections


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def discover_docx(corpus: Path) -> list[Path]:
    return sorted(p for p in corpus.rglob("*.docx") if not p.name.startswith("~$"))


def run_script(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable] + args,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def analyze_one(docx_path: Path, workdir: Path, timeout: int, file_id: str) -> dict:
    """Copy one template into the workspace and run the v4 analyzer on it."""
    record: dict = {"id": file_id}
    staged = workdir / "template.docx"
    shutil.copyfile(docx_path, staged)
    record["size_bytes"] = staged.stat().st_size
    record["sha256_before"] = sha256_of(staged)

    started = time.monotonic()
    outcome: dict = {"classification": "OK"}
    try:
        proc = run_script(
            [str(ROOT / "scripts" / "analyze_template.py"),
             "--input", str(staged), "--spec-version", "4"],
            timeout=timeout,
        )
        outcome["elapsed_s"] = round(time.monotonic() - started, 2)
        if proc.returncode != 0:
            outcome["classification"] = "ANALYZE_ERROR"
            outcome["error_tail"] = (proc.stderr or proc.stdout)[-800:]
        else:
            try:
                spec = json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                outcome["classification"] = "INVALID_SPEC"
                outcome["error_tail"] = f"json decode failed: {exc}"
            else:
                validation = validate_document_spec(spec)
                outcome["spec_valid"] = bool(validation["passed"])
                if not validation["passed"]:
                    outcome["classification"] = "INVALID_SPEC"
                    outcome["error_tail"] = json.dumps(
                        validation.get("errors", [])[:5], ensure_ascii=False)
                outcome["summary"] = _summarize_spec(spec)
    except subprocess.TimeoutExpired:
        outcome["classification"] = "TIMEOUT"
        outcome["elapsed_s"] = timeout

    record["sha256_after"] = sha256_of(staged)
    record["template_bytes_changed"] = record["sha256_after"] != record["sha256_before"]
    record["analyze"] = outcome
    return record


def _summarize_spec(spec: dict) -> dict:
    slots = spec.get("slots", []) or []
    fillable = [s for s in slots if s.get("protection_status") == "FILLABLE"]
    protected = [s for s in slots if s.get("protection_status") == "PROTECTED"]
    return {
        "compatibility": (spec.get("template", {}) or {}).get("compatibility"),
        "slot_count": len(slots),
        "fillable_count": len(fillable),
        "protected_count": len(protected),
        "protected_regions": len(spec.get("structure", {}).get("protected_regions", []) or []),
        "unsupported_features": [
            f.get("code") for f in spec.get("unsupported_features", []) or []
        ],
        "warning_codes": [
            w.get("code") for w in spec.get("warnings", []) or []
        ],
        "token_slots": _smoke_slot_ids(fillable),
    }


def _smoke_slot_ids(fillable: list[dict]) -> list[str]:
    """Every fillable text slot the smoke may fill.

    ``{{token}}`` slots come first (the documented GENERATE convention); other
    text slots follow because real corpora rarely use the double-brace style.
    Image and empty-text slots are excluded: the smoke provides no image source.
    Filling all of them keeps QA's ``TEMPLATE_TEXT_RESIDUAL`` gate meaningful —
    a partial fill would be refused by design, which says nothing about the fill.
    """
    braces = [s for s in fillable
              if str(s.get("matched_text", "")).startswith("{{")]
    others = [s for s in fillable
              if s not in braces and str(s.get("matched_text", "")).strip()]
    picked: list[str] = []
    for slot in braces + others:
        if slot.get("semantic_role") == "image":
            continue
        if slot["slot_id"] not in picked:
            picked.append(slot["slot_id"])
    return picked


def fill_smoke(docx_path: Path, workdir: Path, timeout: int, file_id: str,
               writer: str = "python-docx") -> dict:
    """Documented v4 fill chain on one staged copy; outcome metadata only."""
    record: dict = {"id": file_id, "writer": writer}
    staged = workdir / "template.docx"
    shutil.copyfile(docx_path, staged)
    record["sha256_before"] = sha256_of(staged)

    try:
        analyzed = run_script(
            [str(ROOT / "scripts" / "analyze_template.py"),
             "--input", str(staged), "--spec-version", "4"],
            timeout=timeout,
        )
        if analyzed.returncode != 0:
            return {**record, "classification": "ANALYZE_ERROR"}
        spec = json.loads(analyzed.stdout)
        summary = _summarize_spec(spec)
        targets = summary["token_slots"]
        if not targets:
            return {**record, "classification": "SKIPPED_NO_TOKEN_SLOT"}

        facts = []
        by_slot = {}
        for index, slot_id in enumerate(targets, start=1):
            fact_id = "F_SMOKE_%03d" % index
            facts.append({
                "fact_id": fact_id,
                "label": "smoke_%d" % index,
                "value": FILL_VALUE,
                "unit": "none",
                "source": "SMOKE_TEST",
                "verification_status": "VERIFIED",
                "used_by_slots": [slot_id],
            })
            by_slot[slot_id] = fact_id
        content = build_content_plan(
            spec,
            plan_id="CP_REALCORPUS_SMOKE",
            sections=[{
                "section_id": "SEC_SMOKE",
                "purpose": "corpus fill smoke test",
                "target_slots": targets,
                "fact_refs": [f["fact_id"] for f in facts],
            }],
            facts=facts,
            required_slots=targets,
        )
        plan = build_fill_plan(spec, content, task_id="TASK_REALCORPUS_SMOKE",
                               mode="STANDARD")

        spec_path = workdir / "spec.json"
        content_path = workdir / "content_plan.json"
        plan_path = workdir / "fill_plan.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

        # The W4 gate is mandatory: a corpus file is executed only with a
        # record produced through the real analyzer/report/store chain.
        try:
            gate_record = ensure_gate(str(staged), "GENERATE")
        except Exception as exc:  # noqa: BLE001 - one unresolvable file must not stop the run
            return {**record, "classification": "GATE_UNAVAILABLE",
                    "error_tail": "%s: %s" % (type(exc).__name__, exc)}
        gate_path = workdir / "gate_record.json"
        gate_path.write_text(json.dumps(gate_record, ensure_ascii=False), encoding="utf-8")

        output = workdir / "out.docx"
        generated = run_script(
            [str(ROOT / "scripts" / "generate_document.py"),
             "--template", str(staged),
             "--spec", str(spec_path),
             "--content-plan", str(content_path),
             "--plan", str(plan_path),
             "--out", str(output),
             "--mode", "STANDARD",
             "--allow-unverified",
             "--gate-record", str(gate_path),
             "--writer", writer],
            timeout=timeout,
        )
        record["sha256_after"] = sha256_of(staged)
        record["template_bytes_changed"] = record["sha256_after"] != record["sha256_before"]
        if generated.returncode != 0:
            # A structured rejection (BLOCKED/refusal envelope) is a valid smoke
            # outcome and must not be conflated with a crash.
            try:
                payload = json.loads(generated.stdout)
                record["classification"] = "REJECTED_STRUCTURED"
                record["status"] = payload.get("status")
                record["errors"] = [
                    e.get("code") for e in (payload.get("errors", []) or [])
                    if isinstance(e, dict)
                ][:5]
            except json.JSONDecodeError:
                record["classification"] = "GENERATE_ERROR"
                record["error_tail"] = (generated.stderr or generated.stdout)[-800:]
            return record
        payload = json.loads(generated.stdout)
        record["classification"] = "OK"
        record["status"] = payload.get("status")
        data = payload.get("data", {}) or {}
        record["qa_status"] = data.get("qa_status")
        record["missing_checks"] = data.get("missing_checks") or []
        record["coverage_gaps"] = data.get("coverage_gaps") or []
        record["writer_backend"] = data.get("writer_backend")
        record["writer_fallback"] = data.get("writer_fallback")
        record["committed"] = (payload.get("transaction", {}) or {}).get("committed")
        record["filled_slots"] = len((data.get("ledger", {}) or {}).get("records", []) or [])
        return record
    except subprocess.TimeoutExpired:
        record["classification"] = "TIMEOUT"
        return record
    except Exception as exc:  # noqa: BLE001 - harness must survive any single file
        record["classification"] = "SMOKE_ERROR"
        record["error_tail"] = "%s: %s" % (type(exc).__name__, exc)[:800]
        return record


def _fallback_bucket(reason: str) -> str:
    """Classify a writer fallback without echoing document text into reports."""
    text = str(reason or "").lower()
    if "is not installed" in text:
        return "binary_missing"
    if "not supported by the officecli writer" in text:
        return "unsupported_operation"
    if "segment" in text or "story" in text or "section" in text or "txbx" in text or "sdt" in text:
        return "unsupported_location"
    if "spans multiple runs" in text:
        return "token_spans_runs"
    if "not unique" in text:
        return "ambiguous_token"
    return "other"


def aggregate(records: list[dict], smoke_records: list[dict], elapsed_s: float) -> dict:
    classify = Counter(r["analyze"]["classification"] for r in records)
    levels = Counter(
        ((r["analyze"].get("summary") or {}).get("compatibility") or "unknown")
        for r in records if r["analyze"]["classification"] == "OK"
    )
    warning_codes = Counter(
        code
        for r in records if r["analyze"]["classification"] == "OK"
        for code in (r["analyze"].get("summary") or {}).get("warning_codes", [])
    )
    unsupported_codes = Counter(
        code
        for r in records if r["analyze"]["classification"] == "OK"
        for code in (r["analyze"].get("summary") or {}).get("unsupported_features", [])
    )
    return {
        "docx_analyzed": len(records),
        "analyze_classification": dict(classify),
        "compatibility_levels": dict(levels),
        "template_bytes_changed": sum(1 for r in records if r["template_bytes_changed"]),
        "spec_invalid": classify.get("INVALID_SPEC", 0),
        "warning_code_histogram": dict(warning_codes.most_common()),
        "unsupported_code_histogram": dict(unsupported_codes.most_common()),
        "fill_smoke": {
            "attempted": len(smoke_records),
            "classification": dict(Counter(r["classification"] for r in smoke_records)),
            "template_bytes_changed": sum(
                1 for r in smoke_records if r.get("template_bytes_changed")),
            "qa_status": dict(Counter(
                str(r.get("qa_status")) for r in smoke_records
                if r["classification"] == "OK")),
            "writer_backend": dict(Counter(
                str(r.get("writer_backend")) for r in smoke_records
                if r["classification"] == "OK")),
            "writer_fallback": dict(Counter(
                _fallback_bucket(r.get("writer_fallback"))
                for r in smoke_records
                if r["classification"] == "OK" and r.get("writer_fallback"))),
        },
        "elapsed_s": round(elapsed_s, 1),
    }


def write_markdown(path: Path, corpus_arg: str, totals: dict,
                   records: list[dict], smoke_records: list[dict],
                   run_info: dict | None = None) -> None:
    run_info = run_info or {}
    lines = [
        "# W3-9 真实语料评测报告（real-corpus-eval）",
        "",
        "- 评测时间：%s" % datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "- 运行命令：`%s`" % run_info.get("command", "n/a"),
        "- 运行环境：%s" % run_info.get("environment", "n/a"),
        "- 语料来源：运行时通过 `--corpus` 提供的外部目录（路径不入库、不写入代码）",
        "- 语料构成：%d 份 `.docx`（递归发现）" % totals["docx_analyzed"],
        "- 标注基线：无（E3）——因此**不计算也不声称**槽位 P/R/F1、漏检率等需要人工标注的指标",
        "- 指标性质：本报告全部为**真实语料的鲁棒性/披露性指标**，与合成 Fixture 指标分列，未合并",
        "- 内容安全：报告仅含匿名序号、技术元数据与聚合指标，不含路径、文件名或文档正文",
        "",
        "## 总体结果",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        "| 解析分类 | %s |" % json.dumps(totals["analyze_classification"], ensure_ascii=False),
        "| 兼容级别分布（解析成功件） | %s |" % json.dumps(totals["compatibility_levels"], ensure_ascii=False),
        "| 模板字节被改动（分析阶段，目标 0） | %d |" % totals["template_bytes_changed"],
        "| Spec 校验失败 | %d |" % totals["spec_invalid"],
        "| 填充冒烟：尝试 / 分类 | %d / %s |" % (
            totals["fill_smoke"]["attempted"],
            json.dumps(totals["fill_smoke"]["classification"], ensure_ascii=False)),
        "| 冒烟后模板字节被改动（目标 0） | %d |" % totals["fill_smoke"]["template_bytes_changed"],
        "| 冒烟 QA 状态 | %s |" % json.dumps(totals["fill_smoke"]["qa_status"], ensure_ascii=False),
        "| 冒烟写入后端 | %s |" % json.dumps(
            totals["fill_smoke"].get("writer_backend", {}), ensure_ascii=False),
        "| officecli 回退原因类别 | %s |" % json.dumps(
            totals["fill_smoke"].get("writer_fallback", {}), ensure_ascii=False),
        "| 总耗时 | %.1fs |" % totals["elapsed_s"],
        "",
        "## 警告码直方图",
        "",
    ]
    if totals["warning_code_histogram"]:
        lines += ["| 警告码 | 次数 |", "|---|---|"]
        lines += ["| `%s` | %d |" % (k, v)
                  for k, v in totals["warning_code_histogram"].items()]
    else:
        lines += ["（无）"]
    lines += ["", "## UNSUPPORTED 码直方图", ""]
    if totals["unsupported_code_histogram"]:
        lines += ["| 码 | 次数 |", "|---|---|"]
        lines += ["| `%s` | %d |" % (k, v)
                  for k, v in totals["unsupported_code_histogram"].items()]
    else:
        lines += ["（无）"]

    problems = [
        r for r in records
        if r["analyze"]["classification"] != "OK" or r["template_bytes_changed"]
    ]
    lines += ["", "## 逐文件异常清单（仅异常项）", ""]
    if problems:
        lines += ["| 样本 | 分类 | 摘要 |", "|---|---|---|"]
        for r in problems:
            outcome = r["analyze"]
            detail = outcome.get("error_tail", "template bytes changed") or "template bytes changed"
            lines.append("| %s | %s | %s |" % (
                r["id"], outcome["classification"],
                str(detail).replace("\n", " ").replace("|", "\\|")[:160]))
    else:
        lines += ["（无：全部分析成功、字节不变）"]

    smoke_bad = [
        r for r in smoke_records
        if r["classification"] != "OK" or r.get("template_bytes_changed")
    ]
    lines += ["", "## 填充冒烟异常清单", ""]
    if smoke_bad:
        lines += ["| 样本 | 分类 | 摘要 |", "|---|---|---|"]
        for r in smoke_bad:
            if r.get("template_bytes_changed"):
                detail = "template bytes changed"
            elif r["classification"] == "REJECTED_STRUCTURED":
                detail = "status=%s errors=%s" % (
                    r.get("status"), json.dumps(r.get("errors") or [], ensure_ascii=False))
            else:
                detail = r.get("error_tail") or "-"
            lines.append("| %s | %s | %s |" % (
                r["id"], r["classification"],
                str(detail).replace("\n", " ").replace("|", "\\|")[:160]))
    else:
        lines += ["（无）"]

    lines += ["", "## UNVERIFIED 原因分布", ""]
    unverified = [r for r in smoke_records if str(r.get("qa_status")) == "UNVERIFIED"]
    if unverified:
        gap_counts = Counter(
            gap for r in unverified for gap in (r.get("coverage_gaps") or [])
        )
        missing_counts = Counter(
            check for r in unverified for check in (r.get("missing_checks") or [])
        )
        lines += ["| 来源 | 代码 | 次数 |", "|---|---|---|"]
        lines += ["| coverage_gap | `%s` | %d |" % (k, v)
                  for k, v in gap_counts.most_common()]
        lines += ["| missing_check | `%s` | %d |" % (k, v)
                  for k, v in missing_counts.most_common()]
        if not gap_counts and not missing_counts:
            lines += ["| - | 未记录原因 | %d |" % len(unverified)]
    else:
        lines += ["（无）"]

    lines += [
        "",
        "## 已知限制",
        "",
        "- 语料未经脱敏与人工标注，按 E3 不得用于准确率统计，也不得进入仓库 fixtures。",
        "- 本机缺失 PyMuPDF/OCR/matplotlib，视觉类 QA 在冒烟中如实 `UNVERIFIED`。",
        "- SDT 内填充为 W4 能力项（`sdt_edit=false`）；本语料如含 SDT，填充会被显式拒绝，属预期保护行为。",
        "- 冒烟填充全部可填文本槽位：只填一部分会触发 `TEMPLATE_TEXT_RESIDUAL`，"
        "那是 QA 门禁对未完成填充的预期 fail-closed 行为，不代表填充链缺陷。",
        "- 语料含大量【】括号样式文本（如教材式菜单标注），槽位发现按括号约定枚举为候选槽位；"
        "无标注基线（E3）时不声称其精确率，生成内容由内容层负责任何槽位的取舍。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True,
                        help="external corpus directory (never embedded in the repo)")
    parser.add_argument("--out", default=str(ROOT / "reports" / "w3" / "real-corpus-eval.json"))
    parser.add_argument("--report", default=str(ROOT / "reports" / "w3" / "real-corpus-eval.md"))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--fill-sample", type=int, default=6,
                        help="run the fill smoke chain on the first N parseable token templates")
    parser.add_argument("--limit", type=int, default=0, help="0 = all files")
    parser.add_argument("--writer", choices=("python-docx", "officecli"), default="python-docx",
                        help="mutation backend passed through to the fill smoke")
    args = parser.parse_args()

    corpus = Path(args.corpus)
    if not corpus.is_dir():
        parser.error("corpus directory does not exist: %s" % corpus)

    files = discover_docx(corpus)
    if args.limit > 0:
        files = files[:args.limit]
    if not files:
        print("no .docx found under corpus", file=sys.stderr)
        return 2

    started = time.monotonic()
    records: list[dict] = []
    smoke_records: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="real-corpus-") as tmp:
        workdir = Path(tmp)
        for index, docx_path in enumerate(files, start=1):
            file_id = "D%03d" % index
            record = analyze_one(docx_path, workdir, args.timeout, file_id)
            records.append(record)
            summary = record["analyze"].get("summary") or {}
            if (record["analyze"]["classification"] == "OK"
                    and summary.get("token_slots")
                    and len(smoke_records) < args.fill_sample):
                smoke_records.append(
                    fill_smoke(docx_path, workdir, args.timeout, file_id, writer=args.writer)
                )
            print("[%s] %s" % (record["analyze"]["classification"], file_id),
                  flush=True)

    elapsed = time.monotonic() - started
    totals = aggregate(records, smoke_records, elapsed)
    run_info = {
        "command": (
            "python tests/real_corpus_eval.py --corpus <external-dir> "
            "--fill-sample %d --timeout %d --limit %d --writer %s"
            % (args.fill_sample, args.timeout, args.limit, args.writer)
        ),
        "environment": "Python %s; %s; python-docx %s" % (
            platform.python_version(),
            platform.platform(),
            getattr(docx, "__version__", "unknown"),
        ),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "run_info": run_info,
        "totals": totals,
        "records": records,
        "smoke_records": smoke_records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(report_path, str(corpus), totals, records, smoke_records, run_info)

    print(json.dumps(totals, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
