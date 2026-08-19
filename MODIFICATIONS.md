# MODIFICATIONS.md — BMC-team delta vs upstream (D-015)

Any upstream change touching a path listed here is a conflict-of-record in
sync review, even if git auto-merges.

| # | Path | Modification | Reason |
|---|---|---|---|
| 1 | bmad-modules.yaml | PLANNED: re-point external module URLs (tea/bmb/cis) to BMC-team forks | fork-sourced installs pin by our SHAs (D-015 §4) |

Status: row 1 not yet applied — lands with the first fork-sourced install
change. Branch model: upstream-main = ff-only mirror; bmc-main = default.
