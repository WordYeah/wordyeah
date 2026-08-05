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

For datasets distributed as local Parquet with embedded `image.bytes` and integer
`label`, install `pyarrow` in the corpus-preparation environment and select one or
more source labels. The reader streams batches, applies the same image and total
output limits, and keeps each candidate set in a separate private directory:

```bash
python3 scripts/prepare_hf_parquet_candidates.py /private/cache/train.parquet \
  --dataset owner/content-levels --candidate-set boundary \
  --label 1 --count 200 \
  --output-root /private/wordyeah/avatar-corpus-candidates \
  --source-url https://huggingface.co/datasets/owner/content-levels \
  --license apache-2.0 --style-candidate other --decision-candidate review
```

`pyarrow` is only needed for this local preparation command and is not a WordYeah
runtime dependency.

### Private quality inbox import

Candidate manifests can be copied into the reviewer-only `media://corpus/...`
root and registered as unresolved quality samples. The importer verifies every
manifest path stays below its sibling `images/` directory, rejects symlinks,
recomputes SHA-256, decodes each bounded image, writes 0600 media files and keeps
source suggestions separate from human decisions:

```bash
python3 scripts/import_corpus_quality_samples.py \
  --database /private/wordyeah/avatar-review/wordyeah.sqlite3 \
  --media-root /private/wordyeah/avatar-review/media \
  --consumer-id corpus-avatar \
  --manifest human=/private/candidates/human/candidates.jsonl \
  --manifest anime=/private/candidates/anime/candidates.jsonl \
  --manifest logo_text=/private/candidates/logo/candidates.jsonl \
  --manifest boundary=/private/candidates/boundary/candidates.jsonl \
  --manifest explicit_violation=/private/candidates/explicit/candidates.jsonl
```

The command is idempotent by content hash. `READY_FOR_HUMAN_REVIEW` means only
that the private inbox is ready; its report deliberately remains
`ground_truth=false`. Imported rows do not receive `expected_decision` or a
final quality decision until independent reviewers submit labels.

The importer also creates bounded 192 px reviewer thumbnails. The paginated
quality page loads only these small derivatives; opening a sample follows the
session-protected original endpoint. Both paths are resolved component by
component without following symlinks.

Freeze the required 10% independent dual-review subset before labeling:

```bash
python3 scripts/freeze_corpus_dual_review.py \
  --database /private/wordyeah/avatar-review/wordyeah.sqlite3 \
  --output /private/wordyeah/avatar-review/dual-review-10pct-v2.jsonl \
  --consumer-id corpus-avatar --fraction 0.10 \
  --batch-id dual-review-10pct-v2 \
  --primary-batch-id corpus-primary-v1
```

The selection is deterministic by seed and content hash, includes a fingerprint
of all source samples, and refuses to overwrite a different frozen result. Its
initial state remains `FROZEN_AWAITING_REVIEWS`, `ground_truth=false`, and
`dual_review_completed=0`.

The same command registers two immutable ordered batches in the private quality
database: `corpus-primary-v1` contains all source samples for one primary human
label, while `dual-review-10pct-v2` contains the frozen 10% subset that requires
a second independent reviewer. Reusing a `consumer_id + batch_id` requires an
exact metadata and item-order match. The quality page defaults to unfinished
primary labeling and exposes an explicit switch to the dual-review subset. A
dual-subset sample counts toward primary progress after its first label even
though it remains open for the independent second label. Primary completion is
not ground truth; only a fully resolved dual-review batch reports
`ground_truth=true`. The second reviewer cannot see the first decision before
submitting their own.

Generate aggregate corpus evidence directly from the frozen batch after
reviewing. This command opens SQLite in read-only mode and evaluates only pairs
that have both a resolved human decision and a separately stored successful AI
proposal. Candidate routing hints and strata are never converted into truth:

```bash
python3 scripts/evaluate_quality_corpus.py \
  --database /private/wordyeah/avatar-review/wordyeah.sqlite3 \
  --consumer-id corpus-avatar --batch-id corpus-primary-v1 \
  --output artifacts/avatar-corpus-evaluation-mvp.json
```

Until all 1,100 human decisions, 1,100 AI proposals, the frozen 10% independent
double review, and any required arbitration are complete, the report remains
`INCOMPLETE`. It never modifies quality decisions, review items, or avatars.
