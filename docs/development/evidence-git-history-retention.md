# Evidence Git History Retention

PR #3 was merged with rebase, so the original reviewed source history is not
reachable from `main` even though the resulting source tree is identical. The
history root retained by this repair is
`22fde348366357c2b087fe13fcdeb1676f1c1108`.

Commits referenced by evidence must remain reachable through the ancestry of
`main`. Temporary feature branches, remote reflogs, and incidental Git object
retention are not durable evidence storage mechanisms.

This repair changes no product code or firmware behavior and does not advance
P3B, P4E, HIL, or freeze status. The repair pull request must be merged with a
merge commit so its second-parent ancestry is preserved; squash and rebase
merges are prohibited.

Future evidence-bearing pull requests must preserve referenced source history
with a merge commit unless their evidence is fully self-contained and no
validator or audit process reads historical Git objects.
