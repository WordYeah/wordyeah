# WordYeah labelled media manifests

The calibration gate uses JSONL manifests. The per-entry contract is fixed in
`config/dataset-manifest.schema.json`. Each line identifies a controlled local
image reference and a human-reviewed expected decision:

```json
{"sample_id":"avatar-001","content_sha256":"<64 lowercase hex>","local_ref":"dataset://avatars/avatar-001.jpg","media_type":"image","style":"real","expected_decision":"allow","categories":[],"source":"internal-consented","license":"private","reviewer_count":2,"split":"calibration","duplicate_group":"sha-or-perceptual-group","path":"/private/corpus/avatar-001.jpg"}
```

The local-only validator checks the manifest, exact duplicate hashes, split
leaks, controlled paths, SHA-256 values, and the same image decode limits as
the API:

```bash
python3 scripts/dataset_validate.py /private/corpus/avatar-manifest.jsonl \
  --root /private/corpus --check-files \
  --output /private/corpus/avatar-manifest-validation.json
```

The validator does not print raw paths in its report. `--require-acceptance`
is reserved for the real frozen corpus and fails until all minimum strata are
present. Without it, incomplete strata are reported as `INCOMPLETE` or
`SKIP_NO_SAMPLES`; zero samples are never a pass.

For a labelled directory tree, `dataset_import.py` accepts either
`<style>/<decision>/...` folders or explicit `--style` and `--decision` flags.
It only writes a manifest and never uploads or rewrites source images:

```bash
python3 scripts/dataset_import.py /private/corpus/raw \
  --output /private/corpus/avatar-manifest.jsonl \
  --dataset-name avatars --source internal-consented --license private \
  --split calibration --reviewer-count 2
```

`dataset_deduplicate.py` reports exact SHA-256 duplicates and a conservative
average-hash near-duplicate report by sample ID. The perceptual groups are
advisory and must be reviewed before deleting samples. It can fail a local gate on exact
duplicates with `--fail-on-exact`; the validator remains the split-leak gate.

The evaluator never uploads the image and reports only sample IDs, hashes and
model outputs. It reports false-positive rate for expected `allow` samples and
block recall for expected `block` samples. If a class has zero samples, the
metric is `null` with a `SKIP_*` status.

The committed smoke manifest contains generated safe fixtures only. A separate
local-only benchmark may add a small public dataset subset, but its labels and
domain must be recorded separately; it is not a real-avatar or production
accuracy set.

## Public candidate staging

Public datasets may be used to prepare a review inbox, but their source labels are
not WordYeah ground truth. Candidate manifests deliberately use
`review_status=unreviewed`, `ground_truth=false` in the report, and contain no
`expected_decision` field. They cannot pass `dataset_validate.py` or the avatar MVP
aggregate gate until reviewed entries are promoted into the controlled manifest.

The viewer collector calls only `datasets-server.huggingface.co`, rejects redirects
and non-`/cached-assets/` image URLs, applies the normal image decode limits, and
writes a private 0600 manifest plus 0600 image files under a 0700 dataset directory:

```bash
python3 scripts/prepare_hf_avatar_candidates.py \
  --dataset LakoreAI/human-nonhuman-face-classification \
  --config default --split test --label 0 --count 300 \
  --output-root /private/wordyeah/avatar-corpus-candidates \
  --source-url https://huggingface.co/datasets/LakoreAI/human-nonhuman-face-classification \
  --license mit --style-candidate real --decision-candidate allow
```

For a locally downloaded Hugging Face zip, the archive collector bounds archive,
member and compression sizes, ignores traversal/symlink entries and extracts only
validated images:

```bash
python3 scripts/prepare_hf_archive_candidates.py /private/cache/data.zip \
  --dataset huggan/anime-faces --count 300 \
  --output-root /private/wordyeah/avatar-corpus-candidates \
  --source-url https://huggingface.co/datasets/huggan/anime-faces \
  --license cc0-1.0 --style-candidate anime --decision-candidate allow
```

The `style-candidate` and `decision-candidate` values are routing hints only. Every
candidate remains unreviewed, including rows whose source dataset calls them human,
safe or explicit.
