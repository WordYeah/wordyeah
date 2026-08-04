"""Freeze deterministic, stratified samples for independent dual review."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from wy_review.quality import QualityStore


class QualitySelectionError(ValueError):
    """Raised when a frozen review selection would be invalid or overwritten."""


def freeze_dual_review_selection(
    *,
    database: Path,
    output: Path,
    consumer_id: str,
    fraction: float = 0.10,
    seed: str = "avatar-mvp-dual-review-v1",
    batch_id: str = "dual-review-10pct-v2",
    primary_batch_id: str = "corpus-primary-v1",
) -> dict[str, object]:
    if not 0 < fraction <= 1:
        raise QualitySelectionError("fraction must be greater than zero and at most one")
    if not seed.strip() or len(seed) > 256:
        raise QualitySelectionError("seed must be between 1 and 256 characters")
    if not batch_id.strip() or len(batch_id) > 128:
        raise QualitySelectionError("batch_id must be between 1 and 128 characters")
    if not primary_batch_id.strip() or len(primary_batch_id) > 128:
        raise QualitySelectionError("primary_batch_id must be between 1 and 128 characters")
    if primary_batch_id == batch_id:
        raise QualitySelectionError("primary and dual review batch ids must differ")
    store = QualityStore(str(database.expanduser()))
    samples = store.list_samples(consumer_id=consumer_id)
    if not samples:
        raise QualitySelectionError("quality inbox has no samples")
    source_fingerprint = hashlib.sha256(
        "\n".join(
            f"{sample.sample_id}\0{sample.content_sha256}\0{sample.stratum or ''}"
            for sample in sorted(samples, key=lambda item: item.sample_id)
        ).encode("utf-8")
    ).hexdigest()
    by_stratum: dict[str, list[object]] = {}
    for sample in samples:
        if not sample.stratum:
            raise QualitySelectionError("every quality sample must have a stratum")
        by_stratum.setdefault(sample.stratum, []).append(sample)

    selected: list[dict[str, object]] = []
    quotas: dict[str, int] = {}
    for stratum in sorted(by_stratum):
        candidates = by_stratum[stratum]
        quota = max(1, int(len(candidates) * fraction + 0.5))
        quotas[stratum] = quota
        ranked = sorted(
            candidates,
            key=lambda sample: (
                hashlib.sha256(
                    f"{seed}\0{stratum}\0{sample.content_sha256}".encode("utf-8")
                ).hexdigest(),
                sample.sample_id,
            ),
        )
        for ordinal, sample in enumerate(ranked[:quota], 1):
            selected.append(
                {
                    "selection_id": f"{stratum}-{ordinal:04d}",
                    "sample_id": sample.sample_id,
                    "item_id": sample.item_id,
                    "content_sha256": sample.content_sha256,
                    "media_ref": sample.media_ref,
                    "stratum": stratum,
                    "required_independent_reviewers": 2,
                    "selection_status": "awaiting_reviews",
                    "selection_source_sha256": source_fingerprint,
                    "ground_truth": False,
                }
            )
    rendered = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in selected
    ).encode("utf-8")
    path = output.expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    reused = False
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise QualitySelectionError("selection output must be a regular file")
        if path.read_bytes() != rendered:
            raise QualitySelectionError("frozen review selection already exists with different data")
        reused = True
    else:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    path.chmod(0o600)
    try:
        primary_items = tuple(
            (sample.sample_id, sample.stratum or "")
            for sample in sorted(samples, key=lambda item: item.sample_id)
        )
        store.create_review_batch(
            consumer_id=consumer_id,
            batch_id=primary_batch_id,
            source_sha256=source_fingerprint,
            fraction=1.0,
            seed=seed,
            items=primary_items,
            required_reviewers=1,
        )
        store.create_review_batch(
            consumer_id=consumer_id,
            batch_id=batch_id,
            source_sha256=source_fingerprint,
            fraction=fraction,
            seed=seed,
            items=tuple((str(row["sample_id"]), str(row["stratum"])) for row in selected),
            required_reviewers=2,
        )
        store.configure_review_requirements(
            consumer_id=consumer_id,
            primary_sample_ids=tuple(sample_id for sample_id, _ in primary_items),
            dual_review_sample_ids=tuple(str(row["sample_id"]) for row in selected),
        )
    finally:
        store.close()
    return {
        "kind": "wordyeah_dual_review_selection",
        "status": "FROZEN_AWAITING_REVIEWS",
        "consumer_id": consumer_id,
        "batch_id": batch_id,
        "primary_batch_id": primary_batch_id,
        "source_sample_count": len(samples),
        "selected_count": len(selected),
        "fraction": fraction,
        "seed": seed,
        "source_sha256": source_fingerprint,
        "quotas": quotas,
        "reused": reused,
        "ground_truth": False,
        "dual_review_completed": 0,
        "output": str(path),
    }
