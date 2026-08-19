# MODIFICATIONS.md — BMC-team delta vs upstream (D-015)

Any upstream change touching a path listed here is a conflict-of-record in
sync review, even if git auto-merges.

| # | Path | Modification | Reason |
|---|---|---|---|
| 1 | bmad-modules.yaml | APPLIED on install branch bmc-v6.11.0 (commit 4d2d7ea0991d8eb9fb18650e8dd61d2e40b31678): tea/bmb/cis URLs -> BMC-team forks; never-install modules left upstream | fork-sourced installs pin by our SHAs (D-015 §4) |

Status: row 1 not yet applied — lands with the first fork-sourced install
change. Branch model: upstream-main = ff-only mirror; bmc-main = default.
