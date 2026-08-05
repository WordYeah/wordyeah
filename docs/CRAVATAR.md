# Cravatar adapter boundary

首次覆盖 `wp_9_avatar_verify` 全量登记记录的计划见
[`CRAVATAR_FULL_REGISTRY_REVIEW_PLAN.md`](CRAVATAR_FULL_REGISTRY_REVIEW_PLAN.md)。
该文档为 plan-only，不授权生产扫描或写回。

The current production code still has the WordPress queue entry at:

- `feicode-prod:/www/wwwroot/cravatar/wp-content/plugins/cravatar/inc/class-avatar-audit.php:20-23`
- `feicode-prod:/www/wwwroot/cravatar/wp-content/plugins/cravatar/inc/class-q-cloud.php:38-40`

WordYeah does not write to either file. `wy-cravatar` imports controlled local
copies in shadow mode and translates a `ModerationResult` into a pure action
contract:

Cravatar content decisions are produced only by WordYeah's own fast scan and
configured self-managed vision providers (the G2A Web account pool and local
Ollama models). Tencent Cloud CI and other third-party moderation APIs are not
fallbacks. If WordYeah cannot obtain a confident conclusion, the item is held
or escalated instead of being sent to an external moderation service.

| Mode | `allow` | `review`/`block` | `error` | Avatar mutation |
|---|---|---|---|---|
| `shadow` | record only | record only | record only | none |
| `review` | allow | queue review | hold | none |
| `enforce` | allow | review or block | hold | block only |

The first production gate must be a shadow adapter with no avatar-state write,
no remote URL fetch, and no Tencent Cloud call. `src/wy_cravatar/shadow.py`
provides a disabled-by-default local staging boundary that records only avatar
reference, content hash, request id and the non-mutating action; it does not
perform HTTP or call WordPress. PHP/WP integration remains outside the
production path and requires an independent canary and rollback verification.

## 2026-08-04 read-only production evidence

- The active queue is `wp_cavalcade_jobs` with hook
  `lpcn_sensitive_content_recognition`; `wp_9_avatar_verify` is an avatar
  registry and must not be treated as the moderation backlog. The current
  1,100-item WordYeah import was sampled from Cavalcade and joined to that
  registry; it is not a full export of the registry.
- At the 2026-08-04 19:25 Asia/Shanghai snapshot the hook had 33,548
  `completed`, 270 `failed`, 12 `running`, and 4 `waiting` jobs. The queue is
  live, so these counts are only a timestamped snapshot.
- `class-q-cloud.php` has returned `true` before moderation since its
  2026-08-03 deployment. There were 8,436 completed jobs whose scheduled
  `start` was at or after `2026-08-03 03:54:12`; those records are candidates
  for shadow rechecking, not proof of unsafe content.
- A five-item read-only canary was exported to a Mac-local controlled folder,
  fetched only through the canonical `cravatar.com` to `cn.cravatar.com` HTTPS path,
  decoded under image limits, normalized by `cravatar_backlog_import.py`, and
  submitted to the local Falconsai path. All five returned `allow`; five
  samples are insufficient to infer backlog quality and therefore do not pass
  an accuracy gate.
- The canary wrote only local ignored artifacts and a local SQLite result DB.
  It made no WordPress, avatar, Cavalcade, Tencent Cloud, or production DB
  mutation.
- A 2026-08-05 live read-only count found 3,068,649 `gravatar` rows and
  18,320 `cravatar` rows in `wp_9_avatar_verify`. Those 3,086,969 registry rows
  have not been fully imported or reviewed by WordYeah.

## Local shadow ingestion

```bash
python scripts/cravatar_backlog_import.py manifest.json \
  --root ./controlled-images --output ./normalized.jsonl
python scripts/cravatar_backlog_submit.py manifest.json \
  --root ./controlled-images --endpoint http://127.0.0.1:18765 \
  --workspace cravatar \
  --output ./shadow-results.json
```

The submitter rechecks every content hash immediately before sending, accepts
only loopback endpoints, sends the Cravatar workspace plus local source/job
identifiers, and always reports `mutates_avatar=false`. The API rejects the
request unless that workspace was preconfigured. The cursor retains each
source ID's request ID and decision, while SQLite keeps the same source mapping
for review and later enforcement handoff.

Historical backlog submissions also set `requires_ai_review=true`. This keeps a
cheap fast-scan `allow` result from closing an old queue item: newly imported
historical items enter AI review 1, low-confidence results continue to AI
review 2, and only unresolved results enter the human queue. Source IDs that
were already closed keep their prior result; repeating one is idempotent even
after its earlier review item has reached a final state.
This rule applies equally to native Cravatar avatars and avatars served through
the Gravatar mirror; `avatar_origin` is provenance, not an audit exemption.

For larger read-only exports, `scripts/cravatar_cavalcade_export.php` performs a
bounded Cavalcade query plus a bounded read from `wp_9_avatar_verify`, joined by
`image_md5`. It exports `avatar_origin=cravatar|gravatar|unknown`, registry
status and a canonical `cravatar.com` URL. The collector accepts only canonical
`cravatar.com`/`cn.cravatar.com` paths and stores an immutable local copy with
SHA-256, collected MD5 and whether it still matches the historical queued MD5.
The former `cravatar.cn` host is recognized only while reading legacy queue
metadata because it now serves redirects; collectors, manifests and previews
never request or emit that host.
That origin and hash evidence is propagated into WordYeah submissions and
review items. A mismatch means the currently served avatar differs from the old
queue bytes and must not be represented as an exact historical replay.

## Incremental shadow runner

`wordyeah-cravatar` stores a source cursor, stable source IDs, failure records and a
watermark in an atomically replaced local JSON state file. Re-running the same records is idempotent. The
runner can be paused without changing Cravatar and replay only failed local
records:

```bash
wordyeah-cravatar run --workspace cravatar --state ./cursor.json \
  --manifest ./manifest.jsonl --root ./controlled-images \
  --endpoint http://127.0.0.1:18765
wordyeah-cravatar watermark --workspace cravatar --state ./cursor.json
wordyeah-cravatar pause --workspace cravatar --state ./cursor.json
wordyeah-cravatar resume --workspace cravatar --state ./cursor.json
wordyeah-cravatar replay --workspace cravatar --state ./cursor.json \
  --manifest ./manifest.jsonl --root ./controlled-images
wordyeah-cravatar watch --workspace cravatar --state ./cursor.json \
  --manifest ./manifest.jsonl --root ./controlled-images \
  --output ./shadow-status.json
```

`watch` refreshes an atomically published manifest, retries the local failure
ledger and updates an atomic watermark. A disabled hardened systemd template is
documented in `docs/DEPLOYMENT.md`; installing or enabling it is a separate host
decision. The runner never writes WordPress, avatar state, Cavalcade jobs or a
remote database; `enforce=false` remains the only supported deployment state.
