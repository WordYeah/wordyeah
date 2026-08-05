from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import MagicMock, patch

from wy_jobs import __main__ as worker_cli
from wy_media.g2a import G2AConfig


class VisionWorkerCliTests(unittest.TestCase):
    def test_vision_once_constructs_providers_stores_and_worker_without_network(self) -> None:
        secondary = G2AConfig(
            enabled=True,
            endpoint="https://secondary.invalid/v1/chat/completions",
            api_key="secondary-secret",
            model_id="secondary-model",
        )
        job_store = MagicMock()
        attempt_store = MagicMock()
        review_store = MagicMock()
        vision_worker = MagicMock()
        vision_worker.run_once.return_value = None

        primary_provider = MagicMock(enabled=True)
        secondary_provider = MagicMock(enabled=True)

        with (
            patch.object(worker_cli, "build_primary_vision_provider", return_value=primary_provider),
            patch.object(worker_cli, "_secondary_g2a_config", return_value=secondary),
            patch.object(worker_cli, "G2AVisionProvider", return_value=secondary_provider),
            patch.object(worker_cli, "JobStore", return_value=job_store) as jobs,
            patch.object(worker_cli, "ReviewAttemptStore", return_value=attempt_store) as attempts,
            patch.object(worker_cli, "ReviewStore", return_value=review_store) as reviews,
            patch.object(worker_cli, "VisionReviewWorker", return_value=vision_worker) as worker,
        ):
            worker_cli.main(
                [
                    "--vision",
                    "--once",
                    "--database",
                    "fixture.sqlite3",
                    "--media-root",
                    "fixture-media",
                    "--worker-id",
                    "fixture-worker",
                ]
            )

        jobs.assert_called_once_with("fixture.sqlite3")
        attempts.assert_called_once_with("fixture.sqlite3")
        reviews.assert_called_once_with("fixture.sqlite3")
        worker.assert_called_once()
        kwargs = worker.call_args.kwargs
        self.assertEqual(
            kwargs["providers"],
            {"primary": primary_provider, "secondary": secondary_provider},
        )
        self.assertEqual(kwargs["worker_id"], "fixture-worker")
        self.assertEqual(str(kwargs["media_root"]), "fixture-media")
        vision_worker.run_once.assert_called_once_with()
        review_store.close.assert_called_once_with()
        attempt_store.close.assert_called_once_with()
        job_store.close.assert_called_once_with()

    def test_disabled_vision_exits_before_stores_without_leaking_secret(self) -> None:
        stderr = io.StringIO()

        disabled_provider = MagicMock(enabled=False)
        with (
            patch.object(worker_cli, "build_primary_vision_provider", return_value=disabled_provider),
            patch.object(worker_cli, "G2AVisionProvider") as provider,
            patch.object(worker_cli, "JobStore") as jobs,
            patch.object(worker_cli, "ReviewAttemptStore") as attempts,
            patch.object(worker_cli, "ReviewStore") as reviews,
            patch.object(worker_cli, "VisionReviewWorker") as worker,
            redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            worker_cli.main(["--vision", "--once"])

        self.assertEqual(raised.exception.code, 2)
        output = stderr.getvalue()
        self.assertIn("advanced vision is disabled", output)
        self.assertNotIn("must-not-appear", output)
        provider.assert_not_called()
        jobs.assert_not_called()
        attempts.assert_not_called()
        reviews.assert_not_called()
        worker.assert_not_called()

    def test_secondary_configuration_uses_only_secondary_namespace(self) -> None:
        env = {
            "WORDYEAH_G2A_ENABLED": "true",
            "WORDYEAH_G2A_API_KEY": "primary-secret",
            "WORDYEAH_G2A_SECONDARY_ENABLED": "true",
            "WORDYEAH_G2A_SECONDARY_ENDPOINT": "https://secondary.invalid/v1/chat/completions",
            "WORDYEAH_G2A_SECONDARY_API_KEY": "secondary-secret",
            "WORDYEAH_G2A_SECONDARY_MODEL": "secondary-model",
        }

        config = worker_cli._secondary_g2a_config(env)

        self.assertTrue(config.enabled)
        self.assertEqual(config.api_key, "secondary-secret")
        self.assertNotEqual(config.api_key, env["WORDYEAH_G2A_API_KEY"])

    def test_default_mode_does_not_construct_vision_worker(self) -> None:
        with (
            patch.object(worker_cli, "VisionReviewWorker") as vision_worker,
            patch.object(worker_cli, "load_policy_config", side_effect=RuntimeError("legacy path")),
            self.assertRaisesRegex(RuntimeError, "legacy path"),
        ):
            worker_cli.main(["--once"])

        vision_worker.assert_not_called()

    def test_default_worker_waits_when_queue_is_temporarily_empty(self) -> None:
        job_store = MagicMock()
        review_store = MagicMock()
        result_store = MagicMock()
        worker = MagicMock()
        worker.run_once.side_effect = [None, KeyboardInterrupt]
        service = MagicMock()

        with (
            patch.object(worker_cli, "load_policy_config") as policy,
            patch.object(worker_cli, "JobStore", return_value=job_store),
            patch.object(worker_cli, "ReviewStore", return_value=review_store),
            patch.object(worker_cli, "ResultStore", return_value=result_store),
            patch.object(worker_cli, "FalconsaiClassifier"),
            patch.object(worker_cli, "MediaModerationService", return_value=service),
            patch.object(worker_cli, "JobWorker", return_value=worker),
            patch.object(worker_cli.time, "sleep") as sleep,
            self.assertRaises(KeyboardInterrupt),
        ):
            policy.return_value.media_policy = MagicMock()
            policy.return_value.policy_version = "test"
            policy.return_value.profile = "avatar-default"
            worker_cli.main(["--poll-interval", "0.2"])

        sleep.assert_called_once_with(0.2)
        self.assertEqual(worker.run_once.call_count, 2)
        review_store.close.assert_called_once_with()
        result_store.close.assert_called_once_with()
        job_store.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
