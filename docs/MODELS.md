# WordYeah model evidence

## Falconsai/nsfw_image_detection

- Local adapter: `src/wy_media/falconsai.py`
- License declared by the model card: Apache-2.0
- The model card describes a proprietary 80,000-image training set and reports
  `eval_accuracy=0.980375`; this is vendor-provided evidence, not an
  independent WordYeah acceptance result.
- Local loading is `local_files_only=True`; a request cannot download weights
  or send an image to a model API.

Model card: <https://huggingface.co/Falconsai/nsfw_image_detection>.

## Local benchmark smoke

The local M3 Ultra MPS run used 19 samples:

- 14 generated safe fixtures labelled `allow`;
- 5 samples from the public `x1101/nsfw` dataset `nsfw/` directory, labelled
  `block` according to the dataset folder.

Observed result: false-positive rate `0/14`, block recall `5/5`, with no
`review` or `error` result. This is a model/pipeline smoke benchmark only:
the positive set is small and inherits the dataset's folder labels, so it is
not a Cravatar accuracy claim or a production threshold decision. The dataset
archive and extracted images were kept outside the repository and are not
part of the application artifact.

The model remains a baseline. Real, manually reviewed Cravatar-like samples
must be evaluated before `review` or `enforce` is enabled.

## Advanced avatar review chain

- Primary advanced review: G2A Web pool, model `grok-chat-fast`.
- Local primary fallback: Ollama, model `qwen3-vl:8b`.
- Independent low-confidence second review: Ollama, model `gemma3:12b`.
- Human review is requested only after the two model stages remain uncertain,
  disagree, require a human-only policy category, or exhaust retries.

The local fallback is not recorded as G2A: every completed review attempt keeps
the provider and model that actually produced the conclusion. External calls
and Cravatar enforcement both remain disabled by default configuration.
