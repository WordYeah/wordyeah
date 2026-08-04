from __future__ import annotations

import json
from pathlib import Path

import pytest

from wy_review.quality import QualityStore
from wy_review.quality_selection import QualitySelectionError, freeze_dual_review_selection


def _quality_database(path: Path) -> None:
    store = QualityStore(str(path))
    store.create_vocabulary(consumer_id="corpus-avatar")
    for stratum, count, character in (("human", 10, "a"), ("boundary", 20, "b")):
        for index in range(count):
            digest = f"{index:02x}" + character * 62
            store.create_sample(
                consumer_id="corpus-avatar",
                item_id=f"{stratum}-{index}",
                content_sha256=digest,
                media_ref=f"media://corpus/corpus-avatar/{digest}.png",
                reason="quality_sample",
                stratum=stratum,
                retention_status="private_corpus",
            )
    store.close()


def test_freezes_exact_stratified_ten_percent_idempotently(tmp_path: Path) -> None:
    database = tmp_path / "quality.sqlite3"
    output = tmp_path / "selection" / "dual-review.jsonl"
    _quality_database(database)
    first = freeze_dual_review_selection(
        database=database,
        output=output,
        consumer_id="corpus-avatar",
    )
    second = freeze_dual_review_selection(
        database=database,
        output=output,
        consumer_id="corpus-avatar",
    )
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert first["source_sample_count"] == 30
    assert first["selected_count"] == 3
    assert first["quotas"] == {"boundary": 2, "human": 1}
    assert first["ground_truth"] is False
    assert first["dual_review_completed"] == 0
    assert second["reused"] is True
    assert second["batch_id"] == "dual-review-10pct-v2"
    assert len({row["sample_id"] for row in rows}) == 3
    assert all(row["required_independent_reviewers"] == 2 for row in rows)
    assert all(row["ground_truth"] is False for row in rows)
    assert output.stat().st_mode & 0o777 == 0o600
    store = QualityStore(str(database))
    batches = store.list_review_batches(consumer_id="corpus-avatar")
    assert [(batch.batch_id, batch.selected_count) for batch in batches] == [
        ("dual-review-10pct-v2", 3)
    ]
    store.close()


def test_refuses_to_overwrite_frozen_selection_after_source_changes(tmp_path: Path) -> None:
    database = tmp_path / "quality.sqlite3"
    output = tmp_path / "dual-review.jsonl"
    _quality_database(database)
    freeze_dual_review_selection(
        database=database,
        output=output,
        consumer_id="corpus-avatar",
    )
    store = QualityStore(str(database))
    store.create_sample(
        consumer_id="corpus-avatar",
        item_id="human-new",
        content_sha256="f" * 64,
        media_ref="media://corpus/corpus-avatar/new.png",
        reason="quality_sample",
        stratum="human",
        retention_status="private_corpus",
    )
    store.close()
    with pytest.raises(QualitySelectionError, match="already exists"):
        freeze_dual_review_selection(
            database=database,
            output=output,
            consumer_id="corpus-avatar",
        )
