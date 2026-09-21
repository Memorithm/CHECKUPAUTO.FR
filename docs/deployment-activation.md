# Shared-host activation and rollback

`deployment_activation.py` activates only a release that has already been staged and marked as verified by `deployment_release.py`.

The activation boundary is deliberately separate from staging. A candidate can therefore download dependencies and compile without touching the live Passenger application. The live change begins only after the staged release, private shared-state directories and existing deployment state have been validated.

## Managed layout

The private deployment tree remains under `$HOME/.checkupauto`; the Passenger document root remains `$HOME/public_html`. Activation refuses path layouts where the private tree, release tree or resolved shared-state directories escape the private root or resolve into the Web root.

The Deployment Center manages one marked block in `public_html/.htaccess`. The block points Passenger at `.checkupauto/current`, configures the release virtualenv and supplies only private filesystem paths through `SetEnv`. Credentials themselves are never copied into `.htaccess` or CRON.

A second marked block is installed in the user's crontab. It runs `scripts/checkupauto-shared-tick.py` every five minutes through the `current` release virtualenv and sends output to the private shared log directory.

## Atomic switch

`current` must be absent or a symlink to a verified release below `.checkupauto/releases`. An ordinary file/directory or a symlink that escapes the managed release tree is refused.

Activation creates a temporary symlink and replaces `current` atomically. It then touches `tmp/restart.txt` in the selected Passenger app root.

## Post-activation verification

The executor probes both the public HTTPS root and `/api/admin/readiness`. The admin password is read only from the private shared state and is used in memory for the readiness request. A symlinked admin credential is refused. The response must contain a supported readiness schema, valid state, boolean activation gate, string blocker list and a `launchReady` value consistent with the activation gate.

A degraded or configuration-required application may remain deployed when the readiness document is structurally valid; the resulting bounded state, activation flag and blocker count are recorded. This matches the existing production helper's separation between successful deployment and business launch readiness.

## Automatic rollback

Before modifying live state, activation snapshots the existing managed `.htaccess`, crontab and previous verified `current` target. If configuration, symlink switching, Passenger restart or HTTPS/readiness verification fails, the executor attempts to restore all three and restarts the previous release. Remote failure output reports only the exception type and whether rollback itself succeeded; credentials and response bodies are not echoed.

Successful activations append a private JSONL history record containing the new SHA, previous SHA, readiness state, activation flag, blocker count and UTC timestamp.

An explicit rollback is the same verified activation path applied to a previous staged release SHA. This avoids maintaining a weaker second code path.
