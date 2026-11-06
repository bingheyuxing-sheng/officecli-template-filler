# -*- coding: utf-8 -*-
"""Evidence registry: registration, querying, conflict detection and digesting."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .models import EvidenceRecord, EvidenceStatus, canonical_json, sha256_text


class EvidenceRegistry:
    """Deterministic container for :class:`EvidenceRecord` objects."""

    def __init__(self, records: Optional[Iterable[EvidenceRecord]] = None) -> None:
        self._records: Dict[str, EvidenceRecord] = {}
        for record in records or ():
            self.add(record)

    def __len__(self) -> int:
        return len(self._records)

    def add(self, record: EvidenceRecord) -> None:
        if not isinstance(record, EvidenceRecord):
            raise TypeError("record must be an EvidenceRecord")
        existing = self._records.get(record.evidence_id)
        if existing is not None:
            if canonical_json(existing.to_dict()) != canonical_json(record.to_dict()):
                raise ValueError(
                    "duplicate evidence_id with different content: %s" % record.evidence_id
                )
            return
        self._records[record.evidence_id] = record

    def get(self, evidence_id: str) -> Optional[EvidenceRecord]:
        return self._records.get(str(evidence_id))

    def query(
        self,
        *,
        object_id: Optional[str] = None,
        property: Optional[str] = None,
        status: Optional[str] = None,
        blocking: Optional[bool] = None,
        task_relevant: Optional[bool] = None,
    ) -> List[EvidenceRecord]:
        result: List[EvidenceRecord] = []
        for record in self._records.values():
            if object_id is not None and record.object_id != object_id:
                continue
            if property is not None and record.property != property:
                continue
            if status is not None and record.verification_status != str(status).upper():
                continue
            if blocking is not None and bool(record.blocking) != bool(blocking):
                continue
            if task_relevant is not None and bool(record.task_relevant) != bool(task_relevant):
                continue
            result.append(record)
        return sorted(result, key=lambda item: item.evidence_id)

    def records(self) -> List[EvidenceRecord]:
        return sorted(self._records.values(), key=lambda item: item.evidence_id)

    def detect_conflicts(self) -> List[Dict[str, Any]]:
        """Find same-object/same-property VERIFIED values that disagree.

        ``CONFLICT`` records are evidence in their own right and are not
        re-derived here; this method only reports contradictions between
        otherwise VERIFIED claims.
        """
        groups: Dict[tuple, List[EvidenceRecord]] = {}
        for record in self._records.values():
            if record.verification_status != EvidenceStatus.VERIFIED.value:
                continue
            groups.setdefault((record.object_id, record.property), []).append(record)

        conflicts: List[Dict[str, Any]] = []
        for (object_id, prop), records in sorted(groups.items()):
            values: Dict[str, List[str]] = {}
            for record in records:
                key = canonical_json(record.value)
                values.setdefault(key, []).append(record.evidence_id)
            if len(values) <= 1:
                continue
            conflicts.append(
                {
                    "object_id": object_id,
                    "property": prop,
                    "values": [record_value for record_value in values],
                    "evidence_ids": sorted(
                        evidence_id
                        for group in values.values()
                        for evidence_id in group
                    ),
                }
            )
        return conflicts

    def summary(self) -> Dict[str, Any]:
        counts = {
            "verified": 0,
            "unverified": 0,
            "ambiguous": 0,
            "conflict": 0,
        }
        blocking = 0
        relevant = 0
        for record in self._records.values():
            if record.verification_status == EvidenceStatus.VERIFIED.value:
                counts["verified"] += 1
            elif record.verification_status == EvidenceStatus.UNVERIFIED.value:
                counts["unverified"] += 1
            elif record.verification_status == EvidenceStatus.AMBIGUOUS.value:
                counts["ambiguous"] += 1
            elif record.verification_status == EvidenceStatus.CONFLICT.value:
                counts["conflict"] += 1
            if record.blocking:
                blocking += 1
            if record.task_relevant:
                relevant += 1
        total = len(self._records)
        counts.update(
            {
                "total": total,
                "task_relevant": relevant,
                "blocking": blocking,
                "coverage": round(counts["verified"] / float(total), 4) if total else 0.0,
            }
        )
        return counts

    def digest(self) -> str:
        """Stable sha256 over every evidence record, excluding volatile fields."""
        payload = [record.canonical_dict() for record in self.records()]
        return sha256_text(canonical_json(payload))

    def to_list(self) -> List[Dict[str, Any]]:
        return [record.to_dict() for record in self.records()]
