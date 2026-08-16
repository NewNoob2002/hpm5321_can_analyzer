# Evidence storage policy

Effective 2026-08-16, raw HIL archives larger than 5 MiB are not stored as
ordinary Git blobs. The repository stores a versioned manifest containing the
SHA-256, compressed size, member names and sizes, key result excerpts, and the
external archive record.

The preferred backing store is a controlled evidence repository with immutable
object/version IDs. A GitHub Release asset is acceptable when access control and
retention match the project requirement. Git LFS requires a separate decision
and is reserved for a demonstrated offline-clone verification need.

Each external object record must contain all of the following before freeze:

- immutable object or release-asset ID;
- stable retrieval location;
- SHA-256 and byte size;
- complete member table and key excerpts needed for review without downloading
  the raw archive;
- retention class `project_lifetime_plus_2_years`;
- upload and independent verification timestamps.

`docs/evidence/phase3/P3B-external-artifacts.json` is the repository index. A
record with `archive_status: PENDING_UPLOAD`, a null object ID, or a null
location is an explicit freeze blocker. Local staging paths are ignored by Git.
Small deterministic packages needed by clean-checkout validators may remain in
Git after review; this exception does not apply to high-volume raw captures.
