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

## Stop and rollback

```bash
systemctl disable --now wordyeah-cravatar-shadow.service
```

Stopping the runner leaves Cravatar untouched. Preserve the cursor and status
files for audit. Deleting or rewinding them is not a routine rollback because
it can intentionally replay historical shadow records.
