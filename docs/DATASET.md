# WordYeah labelled media manifests

The calibration gate uses JSONL manifests. Each line identifies a local image
and a human-reviewed expected decision:

```json
{"path":"/data/avatar-001.jpg","expected_decision":"allow"}
{"path":"/data/avatar-002.jpg","expected_decision":"review"}
{"path":"/data/avatar-003.jpg","expected_decision":"block"}
```

The evaluator never uploads the image and reports only local paths, hashes and
model outputs. It reports false-positive rate for expected `allow` samples and
block recall for expected `block` samples. If a class has zero samples, the
metric is `null` with a `SKIP_*` status; zero samples are not a pass.

The current `falconsai-smoke-manifest.jsonl` contains generated safe fixtures
only. It is a pipeline check, not a real-avatar or production accuracy set.
