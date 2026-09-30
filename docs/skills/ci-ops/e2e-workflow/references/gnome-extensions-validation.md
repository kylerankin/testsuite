---
name: gnome-extensions-validation
description: "Deep dive: GNOME OS guest lane for the developer extension-validation service"
metadata:
  type: reference
  audience: agents
  maturity: draft
---
# GNOME OS Extension-Validation Lane (#908)

## Purpose

Validate GNOME developer extensions against a **real GNOME OS Wayland session** with a
**real AT-SPI bus** and **real virtual input** — not the Bluefin desktop and not a mock.
The four `gnome-extensions-hive` extensions are installed, enabled, and exercised with a
qecore/Behave input+AT-SPI scenario.

> **No run has completed yet.** This lane is provisioned and documented; the actual
> boot + load + run evidence is captured in the lab and attached to the run before this
> lane is closed. Do **not** claim GNOME OS extension validation as done until a green
> run exists (issue acceptance: "No claim of GNOME OS validation until an actual run
> succeeds").

## Pinned provenance (do not float)

Base image: `quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-nightly`.

The lane consumes the **digest reference**, never the tag:

```
quay.io/gnome_infrastructure/gnome-build-meta@sha256:57eeef917d057e37d8d5824fab195ebf3b0ad49fc1ca191b7bc02b82418ed981
```

| Tag | Digest |
|---|---|
| `gnomeos-nightly` (pinned for the lane) | `sha256:57eeef917d057e37d8d5824fab195ebf3b0ad49fc1ca191b7bc02b82418ed981` |
| `gnomeos-51` | reference only |
| `gnomeos-50` | reference only |
| `gnomeos-latest` | reference only |

The digest resolved via `skopeo inspect docker://quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-nightly`
on 2026-09-30. It proves **existence**, not a successful boot with this action's
provisioner. Re-derive after any change:

```bash
skopeo inspect docker://quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-nightly \
  | jq -r '.Digest'
```

## Guest inventory

The lane reuses the existing `gnome-e2e` provisioner (bootc/ostree → `bootc install
to-disk` → direct QEMU/KVM boot → GDM autologin → ponytail + qecore-headless), pointed
at `gnomeos-nightly` instead of a Bluefin/Dakota image. Provisioned surface:

- GNOME OS nightly (pinned digest) as a bootc/ostree deployment
- boot kernel + initramfs extracted from the ostree deployment for direct QEMU boot
- GDM autologin for the `bluefin-test` user; passwordless sudo for test automation
- **real** GNOME Wayland session (Mutter) + AT-SPI bus (at-spi2-core)
- `gnome-ponytail-daemon` (virtual input) driven by **qecore-headless**
- SSH (port 2222 → 22) as `bluefin-test` for the harness to drive the guest
- No Fedora dnf/RPM assumption — GNOME OS has no traditional package manager; tooling
  ships in an identified test overlay/sysext, not a stock GNOME OS feature

## The four hive extensions

| Collection key | UUID |
|---|---|
| `just-perfection` | `just-perfection-desktop@just-perfection` |
| `sjc-gold` | `sjc-gold@binhnguyensoft.com` |
| `shade-inactive-windows` | `shade-inactive-windows-reborn@binhnguyensoft.com` |
| `stock-market` | `stock-market@binhnguyensoft.com` |

Their Behave collection (`tests/extensions/*`, PR #914, a separate slice) includes
per-extension behaviour features plus a cross-cutting `extension_lifecycle.feature`
(install / enable / disable / uninstall). This lane documents how to boot the guest and
run the mandatory gate; the extension scenarios themselves live in that slice.

## Repeatable commands

> These adapt the proven `gnome-e2e` action for `gnomeos-nightly`. They are documented
> here; the exact commands are validated in the lab and the verified commands are
> recorded in the run.

### 1. Provision + boot the guest

Reuse the `gnome-e2e` composite action with the **pinned digest** (the action passes
`inputs.image` verbatim to `podman pull` / `bootc install`, so a floating tag here would
boot the current nightly instead of the pin above):

```yaml
- uses: ./.github/actions/gnome-e2e
  with:
    image: quay.io/gnome_infrastructure/gnome-build-meta@sha256:57eeef917d057e37d8d5824fab195ebf3b0ad49fc1ca191b7bc02b82418ed981
```

(the action already runs `bootc install to-disk`, extracts kernel/initramfs, and boots a
KVM QEMU VM, waiting for SSH then a live GNOME session).

### 2. Confirm a real session (canary)

```bash
ssh -p 2222 bluefin-test@127.0.0.1 'bash -lc '"'"'
  echo "session=$XDG_SESSION_TYPE display=$WAYLAND_DISPLAY"
  gdbus call --session --dest org.a11y.atspi.Registry \
    --object-path /org/a11y/atspi --method org.a11y.atspi.Registry.GetRegistry 2>&1 | head -1
  gnome-extensions list
'"'"'
```

`session=wayland` and a non-empty AT-SPI registry reply confirm the real session and
AT-SPI. `gnome-extensions list` is the pre-install inventory here: step 1 boots stock
GNOME OS, so the four hive extensions are installed later by step 3 and are **not**
expected in this listing. Unknown version / provision failures are infrastructure
errors, never green.

### 3. Run the extension scenarios

```bash
cd tests/extensions
behave features/extension_lifecycle.feature   # install/enable/disable/uninstall
behave features/just_perfection.feature       # per-extension behaviour (real input + AT-SPI)
```

Re-run the `gnome-extensions list` canary after `features/extension_lifecycle.feature`
has installed the extensions; it must now list the four hive extensions.

### 4. Gate the run

```bash
python3 scripts/extension_validation.py results/results.json; echo $?
# exit 0 = genuine pass; 1 = empty/all-skipped/undefined/hook-error/failed-boot/missing-result
```

## Mandatory service gate

A run passes the extension-validation gate only if **at least one scenario genuinely
passed and nothing errored**. Implemented in
`scripts/extension_validation.is_extension_validation_pass`. It **fails closed** for:

- **empty** — no scenarios at all
- **all-skipped** — every scenario skipped, none passed
- **undefined / untested** — steps not implemented
- **hook-error / failed-boot / error** — any `error` / `hook_error` (lands in `other`)
- **missing-result** — no `results.json` (a failed boot produced no run)
- **any other non-success status** — the non-success set is derived from
  `e2e_summary.SUCCESS_STATUSES`, so a future behave status fails this gate too

This is deliberately stricter than the general e2e headline
(`scripts/e2e_summary.is_success`), which scores an all-skipped or empty run green for
suites that legitimately ship only `@future` scenarios. An extension-validation run
proves nothing unless at least one extension genuinely works.

## Security posture

The guest is a **test target**, not a trusted host. Extension code runs inside the guest
desktop and must never reach the host:

- **Isolated QEMU VM** — the guest has no direct host access.
- **No host management sockets** — no Podman/Docker socket, no host D-Bus system bus, no
  host `~/.config` bind-mounted into the guest.
- **No privileged host mounts** — the VM boots from a raw disk written by `bootc install`;
  the host filesystem is not writable from the guest.
- **Credentials are harness-only** — the SSH key and `bluefin-test` autologin exist so the
  test harness can drive the guest; they are not exposed to extension code.

If provisioning ever mounts a host socket, key, or mount into the guest desktop, that is
a regression: stop and file an issue.

## Status

- [x] Official GNOME OS nightly pinned (digest above)
- [x] Guest inventory + four hive extensions documented
- [x] Mandatory service gate implemented and unit-tested (`scripts/extension_validation.py`)
- [ ] Repeatable boot + load + run commands validated in the lab
- [ ] At least one green extension-validation run captured and attached
- [ ] Lane closed
