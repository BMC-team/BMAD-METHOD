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

## Row 2
Description: memlog.py serializes writers. Every command (init, append, set)
 holds an exclusive fcntl.flock for its whole read-modify-write, so concurrent
 appends to one memlog neither cut nor lose a line (F-MEMLOG-RACE: the shared
 .memlog.md.tmp raced to FileNotFoundError and lost lines). The lock file lives
 in the git dir of the memlog's work tree (else the temp dir: $TMPDIR, else
 /tmp; a .git file naming a missing gitdir counts as no git), never in the
 work tree, so no shared index is polluted. A 10 s bounded wait, then exit 75
 and a JSON refusal carrying the entry for the caller to retry. The rename is
 followed by a directory fsync. --help documents the lock and
 F-MEMLOG-NOCOMMIT (append never commits).
Paths: src/scripts/memlog.py, src/scripts/tests/test_memlog.py
Origin: BMC-team (build-memlog-lock-1 and -2, seat-1002073908-5063; gap P8)
Bug: F-MEMLOG-RACE (BMC-v5-system-administrator
 docs/records/2026-10-09-beads-lane-findings.md section 3.5)
Forwarded: no (candidate for upstream after the owner's review)
Applied-Upstream: no
Applied-Here: not yet (bmc-main PR; the install branch bmc-v6.11.0 and the
 seat image's npm bmad-method@6.11.0 install are a separate owner step)
Reviewed-by: review-memlog-lock-1 (PASS; RML-01..04 and 07 addressed in
 round 2); the owner merges
Last-Update: 2026-10-09
