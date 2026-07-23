# Unified workspace GCE verification

- VM: `llmsuper-workspace-0720`
- Project / zone: `project96-sar` / `us-central1-a`
- Machine: Spot `e2-micro`, 10 GB `pd-standard`, no service account/scopes
- Final suite: 171 tests, 0 failures, 0 errors
- Browser path: `/workspace`, reached through an SSH tunnel to the GCE-hosted server
- SQLite backup: `workspace-evidence.db` (`integrity_check=ok`, 2 message nodes,
  1 nested workflow instance)
- Browser findings fixed during the run: false verified-completion state on provider outage, stale inactive polling, duplicate history endeavors, off-canvas newly added nodes, non-semantic drag invalidation, small-screen terminal sizing, hidden mobile pause/resume controls, and missing dynamic-agent capabilities.

The trace database and server/test logs in this directory were copied off the
VM before it and its boot disk were deleted.

Deletion was verified with exact-name instance and disk listings; both were
empty after teardown.
