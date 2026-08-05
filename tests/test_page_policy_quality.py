from __future__ import annotations

import unittest

from wy_api.page_policy_quality import CSS, render_policy_body, render_quality_body


class PolicyQualityPageTest(unittest.TestCase):
    def test_policy_body_exposes_version_threshold_route_and_release_structure(self) -> None:
        page = render_policy_body(
            {
                "policy_version": "policy-2026.08.05",
                "effective_at": "2026-08-05 09:00 CST",
                "thresholds": [
                    {"label": "自动放行", "value": "≤ 0.12", "detail": "低风险"},
                    {"label": "视觉升级", "value": "≥ 0.68", "detail": "进入二阶段"},
                ],
                "upgrade_routes": [
                    {"stage": "fast_scan", "condition": "置信度不足", "target": "vision_review_2"},
                    {"stage": "vision_review_2", "condition": "仍有分歧", "target": "exception_queue"},
                ],
                "releases": [
                    {"date": "2026-08-05", "version": "v18", "detail": "调整头像裸露阈值"}
                ],
            }
        )
        self.assertIn('aria-labelledby="pq-policy-title"', page)
        self.assertIn("policy-2026.08.05", page)
        self.assertIn("自动放行", page)
        self.assertIn("vision_review_2", page)
        self.assertIn("调整头像裸露阈值", page)
        self.assertIn("pq-policy-grid", CSS)

    def test_policy_accepts_existing_table_and_version_record_shapes(self) -> None:
        page = render_policy_body(
            {
                "current_policy": {"版本": "v4", "放行线": "0.1"},
                "routes": {
                    "columns": ["阶段", "条件", "去向"],
                    "rows": [["初筛", "边界样本", "高级视觉"]],
                },
                "versions": [{"version": "v4", "description": "只读发布"}],
            }
        )
        self.assertIn("v4", page)
        self.assertIn("放行线", page)
        self.assertIn("高级视觉", page)
        self.assertIn("只读发布", page)

    def test_quality_body_focuses_sampling_disagreement_retention_and_labels(self) -> None:
        page = render_quality_body(
            {
                "sampling": {"coverage": "3.0%", "false_positive": "2", "disagreement": "7"},
                "samples": [
                    {
                        "id": "sample-18",
                        "model": "allow / block",
                        "review": "误判确认",
                        "disagreement": "vision ↔ rules",
                        "verdict": "进入仲裁",
                        "tone": "warning",
                    }
                ],
                "retention": {"duration": "30 天", "deidentified": True, "dataset": "quality-v3"},
                "labels": ["false-positive", "avatar", "model-split"],
            }
        )
        self.assertIn('aria-label="抽检概况"', page)
        self.assertIn("误判确认", page)
        self.assertIn("vision ↔ rules", page)
        self.assertIn("data-quality-ai-proposal", page)
        self.assertIn("30 天", page)
        self.assertIn("false-positive", page)
        self.assertIn("人工介入边界", page)
        self.assertNotIn("<form", page)
        self.assertNotIn("<button", page)

    def test_empty_quality_data_is_skip_not_success(self) -> None:
        page = render_quality_body()
        self.assertIn("SKIP · 未提供抽检样本", page)
        self.assertIn("未采集", page)
        self.assertNotIn("100%", page)
        self.assertNotIn("质量通过", page)

    def test_all_dynamic_values_are_escaped_and_tones_are_allowlisted(self) -> None:
        attack = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        policy = render_policy_body(
            {
                "policy_version": attack,
                "thresholds": [{"label": attack, "value": attack, "detail": attack}],
                "routes": [{"stage": attack, "condition": attack, "target": attack}],
                "releases": [{"date": attack, "version": attack, "detail": attack}],
            }
        )
        quality = render_quality_body(
            {
                "samples": [{"id": attack, "model": attack, "tone": attack}],
                "retention": {"duration": attack},
                "labels": [attack],
                "human_intervention": attack,
            }
        )
        for page in (policy, quality):
            self.assertNotIn("<script>", page)
            self.assertNotIn("<img src=x", page)
            self.assertIn("&lt;script&gt;", page)
        self.assertIn('data-tone="quiet"', quality)

    def test_fragments_use_distinct_information_architectures(self) -> None:
        policy = render_policy_body()
        quality = render_quality_body()
        self.assertIn("pq-policy-ledger", policy)
        self.assertNotIn("pq-quality-sheet", policy)
        self.assertIn("pq-quality-sheet", quality)
        self.assertNotIn("pq-policy-ledger", quality)
        self.assertNotIn("hero", policy.lower())
        self.assertNotIn('class="panel"', policy + quality)


if __name__ == "__main__":
    unittest.main()
