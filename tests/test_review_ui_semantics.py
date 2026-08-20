from __future__ import annotations

from wy_api.review_ui import WORKBENCH_JS, _product_reason, _queue_time_text
from wy_review.store import ReviewItem


def _item(**overrides: object) -> ReviewItem:
    values: dict[str, object] = {
        "item_id": "item-1",
        "consumer_id": "cravatar",
        "content_sha256": "a" * 64,
        "media_type": "image",
        "media_ref": "media://review/item-1",
        "source_id": "source-1",
        "source_ref": "cravatar://" + "b" * 32,
        "source_metadata": {},
        "decision_hint": "allow",
        "reasons": (),
        "findings": (),
        "model_versions": {},
        "top_score": 0.99,
        "request_id": "request-1",
        "policy_version": "policy-1",
        "status": "pending",
        "version": 1,
        "created_at": "2026-08-20T00:00:00+00:00",
    }
    values.update(overrides)
    return ReviewItem(**values)  # type: ignore[arg-type]


def test_product_reason_distinguishes_pending_quality_and_completed_items() -> None:
    assert _product_reason(_item()) == "模型建议通过，等待人工确认"
    assert _product_reason(_item(quality_sample=True)) == "质量抽检需要人工确认"
    assert (
        _product_reason(_item(status="approved", stage="auto_approved"))
        == "AI 自动判定为安全头像"
    )
    assert (
        _product_reason(_item(status="approved", stage="human_decided"))
        == "人工审核确认通过"
    )
    assert (
        _product_reason(
            _item(status="rejected", stage="auto_rejected", decision_hint="block")
        )
        == "AI 自动判定为高风险头像"
    )


def test_queue_time_text_uses_completion_time_for_reviewed_items() -> None:
    approved = _item(
        status="approved",
        stage="human_decided",
        reviewed_at="2026-08-20T00:30:00+00:00",
    )
    pending = _item(created_at="2026-08-20T00:30:00+00:00")

    # Freeze the relative-time assertion through the helper used by the queue.
    assert _queue_time_text(approved).startswith("完成于 ")
    assert "等待" not in _queue_time_text(approved)
    assert _queue_time_text(pending).startswith("等待 ")


def test_lightbox_declares_modal_semantics_and_focus_management() -> None:
    assert "modal.setAttribute('role', 'dialog')" in WORKBENCH_JS
    assert "modal.setAttribute('aria-modal', 'true')" in WORKBENCH_JS
    assert "modal.setAttribute('aria-labelledby', 'lightbox-title')" in WORKBENCH_JS
    assert "modal.querySelector('.lightbox-close')?.focus()" in WORKBENCH_JS
    assert "lightboxReturnFocus.focus()" in WORKBENCH_JS
    assert "openLightbox && event.key === 'Tab'" in WORKBENCH_JS
