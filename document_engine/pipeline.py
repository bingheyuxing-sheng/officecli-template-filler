# -*- coding: utf-8 -*-
"""v4.0 generation pipeline (W1-D).

The pipeline is deliberately thin: the executor owns validation, mutation,
QA and the transaction boundary. ``generate_document_v4`` exists so callers
have one stable entry point whose signature mirrors the CLI.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .fill_executor import execute_fill_plan


def generate_document_v4(
    template_path: str,
    spec: Dict[str, Any],
    content_plan: Optional[Dict[str, Any]],
    fill_plan: Dict[str, Any],
    output_path: str,
    *,
    qa_runner=None,
    allow_unverified: bool = False,
) -> Dict[str, Any]:
    """Execute ``fill_plan`` over ``template_path`` and return a ToolEnvelope 4.0 dict."""
    return execute_fill_plan(
        template_path,
        spec,
        fill_plan,
        output_path,
        content_plan=content_plan,
        qa_runner=qa_runner,
        allow_unverified=allow_unverified,
    )


__all__ = ["generate_document_v4"]
