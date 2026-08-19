# MODIFICATIONS.md — BMC-team delta vs upstream (D-015)

Any upstream change touching a `Paths:` entry below is a conflict-of-record in
sync review, even if git auto-merges. Entry schema: Debian DEP-3 (per the
fork-maintenance standards annex, spec-creator docs/reports/, 60b0fe1).
Branch model: upstream-main = ff-only mirror; bmc-main = default (dev
tracking); bmc-v6.11.0 = install branch (release 9ce3c397 + applied rows only).

## Row 1
Description: Re-point external-module registry URLs (tea/bmb/cis) to BMC-team
 forks so installs resolve from our SHAs; never-install modules (bmad-loop,
 gds, automator, wds) left at upstream URLs deliberately.
Paths: bmad-modules.yaml
Origin: BMC-team (C4, bmc-0817183354-c3e7)
Bug: n/a (policy change, not a defect fix)
Forwarded: not-needed (BMC-specific sourcing policy)
Applied-Upstream: no
Applied-Here: bmc-v6.11.0 @ 4d2d7ea0991d8eb9fb18650e8dd61d2e40b31678; row
 carried on bmc-main for future syncs
Reviewed-by: owner plan D-015 (2026-08-19); C4 executed
Last-Update: 2026-08-19
