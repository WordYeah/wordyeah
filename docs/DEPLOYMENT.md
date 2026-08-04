# WordYeah avatar MVP deployment boundary

The repository ships a disabled systemd template for continuous Cravatar
shadow ingestion. Installing the files does not enable or start a service.
Deployment remains `enforce=false` and the runner has no WordPress, Cavalcade,
avatar mutation, Tencent Cloud or production database write code.

## Filesystem contract

```text
/opt/wordyeah/                         application checkout and virtualenv
/etc/wordyeah/cravatar-shadow.env      root-owned 0600 runtime configuration
/var/lib/wordyeah/inbox/               read-only manifest and controlled images
/var/lib/wordyeah/state/               cursor and failure ledger
/var/lib/wordyeah/status/              atomic current watermark JSON
```

The manifest producer is a separate read-only export job. It must write a
complete temporary manifest and rename it atomically; the shadow runner never
queries or updates the production database. Image paths remain relative to the
controlled root and are re-hashed immediately before submission.

The repository includes two bounded producer stages. The PHP stage runs under
WordPress and performs one `SELECT`; it emits metadata-only JSONL to stdout.
The collector accepts only the exact `https://cravatar.cn/avatar/<hash>` source,
fetches through the allowlisted `cn.cravatar.com` image endpoint, checks byte,
pixel and decode limits, and atomically publishes local images plus a manifest:

```bash
# Source host: read-only export. Installing/copying this script is a separate
# production change and is not performed by the WordYeah repository.
WORDYEAH_CRAVATAR_EXPORT_AFTER_ID=0 \
WORDYEAH_CRAVATAR_EXPORT_LIMIT=500 \
WORDYEAH_CRAVATAR_EXPORT_SINCE='2026-08-03 03:54:12' \
wp --allow-root eval-file scripts/cravatar_cavalcade_export.php \
  > /controlled-export/cravatar-jobs.jsonl

# WordYeah host: local/CDN-read-only collection and atomic manifest publish.
python scripts/cravatar_collect_export.py /controlled-export/cravatar-jobs.jsonl \
  --root /var/lib/wordyeah/inbox/images \
  --manifest /var/lib/wordyeah/inbox/cravatar-manifest.jsonl \
  --workers 8
```

如果生产主机不允许安装脚本，或 `wp eval-file /dev/stdin` 不执行输入，使用
WP-CLI 的只读 `SELECT id,status,start,TO_BASE64(args)` 导出 TSV，再在本机运行
`scripts/cravatar_cavalcade_tsv_convert.php`。转换器兼容 MySQL `TO_BASE64`
产生的换行；远端仍只执行 SELECT，不创建文件、不更新 Cavalcade 或头像。
并发采集限制为 1–32 个 worker，默认 8，输出顺序保持与导出顺序一致。

Advance `WORDYEAH_CRAVATAR_EXPORT_AFTER_ID` only after collection reports zero
failures and the shadow runner reports no failed records. If either stage has a
failure, keep the previous ID and re-export the bounded range; durable source
IDs make already completed rows duplicates rather than new submissions.
Export/collection never marks a Cavalcade row and never changes avatar
verification state.

## Staged installation

```bash
python -m venv /opt/wordyeah/.venv
/opt/wordyeah/.venv/bin/pip install '/opt/wordyeah[api]'
install -d -o wordyeah -g wordyeah /var/lib/wordyeah/{inbox,state,status}
install -d -m 0750 /etc/wordyeah
install -m 0600 deploy/systemd/cravatar-shadow.env.example \
  /etc/wordyeah/cravatar-shadow.env
install -m 0644 deploy/systemd/wordyeah-cravatar-shadow.service \
  /etc/systemd/system/wordyeah-cravatar-shadow.service
systemctl daemon-reload
```

Before enabling anything, run one bounded cycle and inspect the watermark:

```bash
sudo -u wordyeah /opt/wordyeah/.venv/bin/wordyeah-cravatar watch \
  --workspace cravatar \
  --state /var/lib/wordyeah/state/cravatar-cursor.json \
  --manifest /var/lib/wordyeah/inbox/cravatar-manifest.jsonl \
  --root /var/lib/wordyeah/inbox/images \
  --endpoint http://127.0.0.1:8000 \
  --max-cycles 1 --output /var/lib/wordyeah/status/cravatar-shadow.json
```

Acceptance requires `mutates_avatar=false`, expected `source_count`, no
unexpected failures, a stable cursor after rerunning the same manifest, and a
WordYeah queue scoped to the `cravatar` workspace. Service enablement is a
separate host decision; this repository does not perform it.

验收证据由 `scripts/audit_cravatar_shadow.py` 从前后两次只读导出、首次运行、
稳定重跑、暂停耗时和采集报告生成。它要求选中源记录前后完全一致、完成数达到
门槛、失败数为 0、重跑没有新 outcome，且暂停耗时不超过 60 秒。

## Stop and rollback

```bash
systemctl disable --now wordyeah-cravatar-shadow.service
```

Stopping the runner leaves Cravatar untouched. Preserve the cursor and status
files for audit. Deleting or rewinding them is not a routine rollback because
it can intentionally replay historical shadow records.
