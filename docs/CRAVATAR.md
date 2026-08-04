# Cravatar adapter boundary

The current production code still has the WordPress queue entry at:

- `feicode-prod:/www/wwwroot/cravatar/wp-content/plugins/cravatar/inc/class-avatar-audit.php:20-23`
- `feicode-prod:/www/wwwroot/cravatar/wp-content/plugins/cravatar/inc/class-q-cloud.php:38-40`

WordYeah does not connect to either file yet. `wy-cravatar` only translates a
`ModerationResult` into a pure action contract:

| Mode | `allow` | `review`/`block` | `error` | Avatar mutation |
|---|---|---|---|---|
| `shadow` | record only | record only | record only | none |
| `review` | allow | queue review | hold | none |
| `enforce` | allow | review or block | hold | block only |

The first production gate must be a shadow adapter with no avatar-state write,
no remote URL fetch, and no Tencent Cloud call. PHP/WP integration is outside
the PoC and requires an independent canary and rollback verification.
