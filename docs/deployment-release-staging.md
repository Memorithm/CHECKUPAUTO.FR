# Shared-host release staging

`deployment_release.py` implements the staging phase of the Deployment Center for Passenger/shared-host targets. It deliberately does not switch `current`, modify `public_html`, install CRON entries or perform rollback yet.

The staging contract is fail-closed:

- the input release is an exact 40-hex Git commit, archived from the local repository rather than the working tree;
- the archive SHA-256 is calculated locally and verified again on the remote host;
- symlinks, hard links, devices, FIFOs, absolute paths and `..` archive members are rejected;
- the release is unpacked below `$HOME/.checkupauto/releases/.incoming-<sha>-*`, never below `public_html`;
- the Python virtual environment and dependencies are prepared inside the incoming release;
- `compileall` must succeed before the verified release marker is written;
- the incoming directory is renamed to `$HOME/.checkupauto/releases/<sha>` only after all staging checks pass;
- an existing release is accepted only when its marker matches both the requested Git SHA and archive SHA-256;
- SSH still uses the Deployment Center's strict `known_hosts` verification and never places a password in process arguments.

The next activation phase must consume only a release carrying this verified marker. It will manage the Passenger entry point and CRON in the Web root, atomically switch the private `current` symlink, run HTTPS health/readiness checks and restore the previous release automatically if verification fails.
