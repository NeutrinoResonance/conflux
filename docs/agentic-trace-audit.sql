-- Agentic tool-loop trace audit for conflux's SQLite database.
--
-- This file is intended for the sqlite3 CLI.  The main database is opened
-- read-only; the views/tables below live only in SQLite's temporary schema
-- and disappear when the CLI exits.
--
-- Example (replace every value for the run being audited):
--
-- sqlite3 -readonly \
--   -cmd '.parameter init' \
--   -cmd ".parameter set :session 'SESSION_ID'" \
--   -cmd ".parameter set :vm 'VM_NAME'" \
--   -cmd ".parameter set :project 'PROJECT_ID'" \
--   -cmd ".parameter set :account 'ACCOUNT_EMAIL'" \
--   -cmd ".parameter set :zone 'ZONE'" \
--   -cmd '.parameter set :stale_seconds 1800' \
--   traces.db < docs/agentic-trace-audit.sql
--
-- Do not treat a DB transcript as independent proof that a remote machine is
-- still healthy.  The durable-job and artifact queries below identify the
-- evidence the agent observed; re-check the final PID/exit file, artifacts,
-- and guest serial transcript directly through the authorized remote path.

.bail on
.headers on
.mode column
.nullvalue NULL

CREATE TEMP TABLE _conflux_audit_config AS
SELECT :session AS session,
       :vm AS vm,
       :project AS project,
       :account AS account,
       :zone AS zone,
       COALESCE(:stale_seconds, 1800) AS stale_seconds;

SELECT CASE
         WHEN session IS NULL OR trim(session) = ''
           OR vm IS NULL OR trim(vm) = ''
           OR project IS NULL OR trim(project) = ''
           OR account IS NULL OR trim(account) = ''
           OR zone IS NULL OR trim(zone) = ''
         THEN 'ERROR: bind session/vm/project/account/zone before trusting this audit'
         ELSE 'parameters ready'
       END AS parameter_status,
       session, vm, project, account, zone, stale_seconds
FROM _conflux_audit_config;

-- One row per traced task, including orphan event-only or exchange-only task
-- IDs.  Control events use task='-' and are intentionally excluded.
CREATE TEMP VIEW _conflux_audit_task_shape AS
WITH task_keys AS (
    SELECT session, task FROM events WHERE task <> '-'
    UNION
    SELECT session, task FROM exchanges WHERE task <> '-'
), event_counts AS (
    SELECT session, task,
           COUNT(*) AS event_rows,
           SUM(kind = 'agent_turn') AS agent_turns,
           SUM(kind = 'tool_step') AS tool_steps,
           SUM(kind = 'execute') AS executes,
           SUM(kind = 'verify') AS verifies,
           SUM(kind = 'agent_end') AS agent_ends,
           SUM(kind = 'verify_error') AS verify_errors,
           SUM(kind = 'executor_error') AS executor_errors,
           MAX(ts) AS last_event_ts
    FROM events
    WHERE task <> '-'
    GROUP BY session, task
), exchange_counts AS (
    SELECT session, task,
           COUNT(*) AS exchange_rows,
           SUM(kind = 'client_request') AS client_requests,
           SUM(kind = 'client_response') AS client_responses,
           SUM(kind = 'upstream') AS upstreams,
           MAX(ts) AS last_exchange_ts
    FROM exchanges
    WHERE task <> '-'
    GROUP BY session, task
)
SELECT k.session, k.task,
       COALESCE(e.event_rows, 0) AS event_rows,
       COALESCE(e.agent_turns, 0) AS agent_turns,
       COALESCE(e.tool_steps, 0) AS tool_steps,
       COALESCE(e.executes, 0) AS executes,
       COALESCE(e.verifies, 0) AS verifies,
       COALESCE(e.agent_ends, 0) AS agent_ends,
       COALESCE(e.verify_errors, 0) AS verify_errors,
       COALESCE(e.executor_errors, 0) AS executor_errors,
       COALESCE(x.exchange_rows, 0) AS exchange_rows,
       COALESCE(x.client_requests, 0) AS client_requests,
       COALESCE(x.client_responses, 0) AS client_responses,
       COALESCE(x.upstreams, 0) AS upstreams,
       CASE
         WHEN e.last_event_ts IS NULL THEN x.last_exchange_ts
         WHEN x.last_exchange_ts IS NULL THEN e.last_event_ts
         ELSE max(e.last_event_ts, x.last_exchange_ts)
       END AS last_ts
FROM task_keys k
LEFT JOIN event_counts e USING (session, task)
LEFT JOIN exchange_counts x USING (session, task);

-- sessions.turns is the number of accepted proxy requests.  turns contains
-- completed supervised turns and, in versions with agent-final persistence,
-- completed final agent responses--not intermediate tool steps.  A live or
-- older Hermes run can therefore have a large request count and zero History
-- rows.  Agentic run_tool_turn() does not read or write plan checkpoints;
-- normal planned-unit checkpoints may also be deleted after completion.
SELECT s.session,
       s.turns AS library_request_count,
       (SELECT COUNT(*) FROM turns t WHERE t.session = s.session)
         AS completed_history_rows,
       (SELECT COUNT(*) FROM checkpoints c WHERE c.session = s.session)
         AS live_plan_checkpoints,
       (SELECT COUNT(DISTINCT task)
          FROM events e
         WHERE e.session = s.session AND e.task <> '-') AS traced_task_ids
FROM sessions s, _conflux_audit_config c
WHERE s.session = c.session;

-- Payload completeness.  Any invalid or truncated row makes argument/output
-- auditing incomplete and must be investigated before declaring success.
SELECT kind,
       COUNT(*) AS rows,
       SUM(CASE WHEN json_valid(payload) = 0 THEN 1 ELSE 0 END)
         AS invalid_json_rows,
       SUM(CASE
             WHEN json_valid(payload) = 1
              AND COALESCE(json_extract(payload, '$.truncated'), 0) = 1
             THEN 1 ELSE 0
           END) AS truncated_rows,
       MAX(length(payload)) AS max_payload_chars
FROM exchanges x, _conflux_audit_config c
WHERE x.session = c.session
GROUP BY kind
ORDER BY kind;

SELECT COUNT(*) AS event_rows,
       SUM(CASE WHEN data IS NOT NULL AND json_valid(data) = 0
                THEN 1 ELSE 0 END) AS invalid_event_data_rows,
       SUM(CASE WHEN task IS NULL OR task = '' THEN 1 ELSE 0 END)
         AS empty_task_ids
FROM events e, _conflux_audit_config c
WHERE e.session = c.session;

-- Classify every HTTP/model task in the agentic loop.  A completed tool step
-- has one request, upstream response, client response, agent_turn, and
-- tool_step.  A completed final answer additionally has execute/verify/end
-- records.  Provider errors are recorded as failures, not completed steps.
CREATE TEMP VIEW _conflux_audit_task_state AS
SELECT s.*,
       CASE
         WHEN agent_turns <> 1 OR client_requests <> 1
           THEN 'invalid-shape'
         WHEN tool_steps = 1
          AND executes = 0 AND verifies = 0 AND agent_ends = 0
          AND verify_errors = 0
          AND client_responses = 1 AND upstreams >= 1
           THEN 'complete-tool-step'
         WHEN tool_steps = 0
          AND executes >= 1 AND verifies >= 1 AND agent_ends = 1
          AND client_responses = 1
          AND upstreams >= executes + verifies
           THEN 'complete-final'
         WHEN tool_steps = 0 AND executes = 0 AND verifies = 0
          AND agent_ends = 0 AND client_responses = 0
          AND executor_errors >= 1
           THEN 'provider-error'
         WHEN client_responses = 0
          AND last_ts >= unixepoch() - c.stale_seconds
           THEN 'in-flight'
         WHEN client_responses = 0
           THEN 'stale-unclosed'
         ELSE 'invalid-shape'
       END AS state
FROM _conflux_audit_task_shape s
JOIN _conflux_audit_config c USING (session);

SELECT state, COUNT(*) AS tasks
FROM _conflux_audit_task_state
GROUP BY state
ORDER BY state;

-- This should return no rows after an accepted run.  During a live request,
-- one recent in-flight row is possible.  Provider errors remain useful
-- historical evidence but fail strict acceptance for the selected session.
SELECT task, state,
       datetime(last_ts, 'unixepoch') AS last_utc,
       agent_turns, tool_steps, executes, verifies, agent_ends,
       verify_errors, executor_errors,
       client_requests, client_responses, upstreams
FROM _conflux_audit_task_state
WHERE state NOT IN ('complete-tool-step', 'complete-final')
ORDER BY last_ts;

-- Extract all tool calls from raw client responses.  Invalid function
-- arguments remain visible through arguments_valid instead of aborting JSON
-- extraction.
CREATE TEMP VIEW _conflux_audit_tool_calls AS
WITH raw_calls AS (
    SELECT x.id AS exchange_id, x.ts, x.session, x.task,
           json_extract(tc.value, '$.id') AS call_id,
           json_extract(tc.value, '$.function.name') AS tool_name,
           json_extract(tc.value, '$.function.arguments') AS arguments_blob
    FROM exchanges x
    JOIN json_each(x.payload, '$.choices[0].message.tool_calls') tc
    WHERE x.kind = 'client_response'
)
SELECT *,
       json_valid(arguments_blob) AS arguments_valid,
       CASE WHEN json_valid(arguments_blob) = 1
            THEN json_extract(arguments_blob, '$.command') END AS command,
       CASE WHEN json_valid(arguments_blob) = 1
            THEN COALESCE(json_extract(arguments_blob, '$.background'), 0)
            ELSE 0 END AS background
FROM raw_calls;

-- Tool-result messages are repeated in growing conversation prefixes.  Keep
-- the newest copy of each call ID so the evidence queries do not over-count.
CREATE TEMP VIEW _conflux_audit_tool_results AS
WITH raw_results AS (
    SELECT x.id AS exchange_id, x.ts, x.session, x.task,
           json_extract(m.value, '$.tool_call_id') AS call_id,
           json_extract(m.value, '$.content') AS content_blob,
           ROW_NUMBER() OVER (
             PARTITION BY x.session, json_extract(m.value, '$.tool_call_id')
             ORDER BY x.id DESC
           ) AS newest
    FROM exchanges x
    JOIN json_each(x.payload, '$.messages') m
    WHERE x.kind = 'client_request'
      AND json_extract(m.value, '$.role') = 'tool'
)
SELECT exchange_id, ts, session, task, call_id,
       json_valid(content_blob) AS content_valid,
       CASE WHEN json_valid(content_blob) = 1
            THEN json_extract(content_blob, '$.exit_code') END AS exit_code,
       CASE WHEN json_valid(content_blob) = 1
            THEN json_extract(content_blob, '$.output')
            ELSE content_blob END AS output
FROM raw_results
WHERE newest = 1;

-- The tool_step event's n_calls must match the raw response.  Zero rows is
-- the healthy result.
WITH event_calls AS (
    SELECT session, task, SUM(json_extract(data, '$.n_calls')) AS event_n_calls
    FROM events
    WHERE kind = 'tool_step'
    GROUP BY session, task
), response_calls AS (
    SELECT session, task, COUNT(*) AS response_n_calls
    FROM _conflux_audit_tool_calls
    GROUP BY session, task
)
SELECT e.task, e.event_n_calls, COALESCE(r.response_n_calls, 0) AS response_n_calls
FROM event_calls e
LEFT JOIN response_calls r USING (session, task)
JOIN _conflux_audit_config c USING (session)
WHERE e.event_n_calls <> COALESCE(r.response_n_calls, 0)
ORDER BY e.task;

-- Strict remote-boundary audit.  exact_target requires all immutable
-- selectors on every terminal call.  selector_conflict catches a second,
-- different selector even when the allowed one is also present.  Local sleep
-- wrappers are reported separately: they do not move the workload off-VM,
-- but they are poor long-running polling behavior.
CREATE TEMP VIEW _conflux_audit_terminal_boundary AS
SELECT t.*,
       CASE
         WHEN command IS NOT NULL
          AND instr(command, 'gcloud compute ssh ' || c.vm) > 0
          AND instr(command, '--project=' || c.project) > 0
          AND instr(command, '--account=' || c.account) > 0
          AND instr(command, '--zone=' || c.zone) > 0
         THEN 1 ELSE 0
       END AS exact_target,
       CASE
         WHEN instr(replace(command, '--project=' || c.project, ''), '--project') > 0
           OR instr(replace(command, '--account=' || c.account, ''), '--account') > 0
           OR instr(replace(command, '--zone=' || c.zone, ''), '--zone') > 0
         THEN 1 ELSE 0
       END AS selector_conflict,
       CASE
         WHEN lower(command) LIKE '%gcloud config %'
           OR lower(command) LIKE '%gcloud auth %'
         THEN 1 ELSE 0
       END AS mutates_or_reads_global_auth_config,
       CASE
         WHEN lower(command) LIKE '%oneascendant%'
           OR lower(command) LIKE '%one-ascendant%'
           OR lower(command) LIKE '%ops-alt@example.com%'
         THEN 1 ELSE 0
       END AS prohibited_reference,
       (length(lower(command))
          - length(replace(lower(command), 'gcloud ', ''))) / length('gcloud ')
         AS gcloud_invocations,
       CASE
         WHEN trim(command) LIKE 'gcloud compute ssh ' || c.vm || ' %'
           THEN 'direct-ssh'
         WHEN trim(command) LIKE 'sleep % && gcloud compute ssh ' || c.vm || ' %'
           THEN 'local-wait-then-ssh'
         ELSE 'other-local-prefix'
       END AS prefix_class
FROM _conflux_audit_tool_calls t
JOIN _conflux_audit_config c USING (session)
WHERE t.tool_name = 'terminal';

SELECT COUNT(*) AS terminal_calls,
       SUM(exact_target) AS exact_target_calls,
       SUM(selector_conflict) AS selector_conflicts,
       SUM(mutates_or_reads_global_auth_config) AS auth_or_config_calls,
       SUM(prohibited_reference) AS prohibited_reference_calls,
       SUM(gcloud_invocations <> 1) AS multiple_or_missing_gcloud_calls,
       SUM(prefix_class = 'other-local-prefix') AS other_local_prefix_calls,
       SUM(prefix_class = 'local-wait-then-ssh') AS local_wait_calls,
       SUM(background <> 0) AS background_terminal_calls,
       SUM(arguments_valid = 0 OR command IS NULL) AS malformed_terminal_calls
FROM _conflux_audit_terminal_boundary;

-- Zero rows is the healthy boundary result.  local-wait-then-ssh is kept in
-- the summary above as a polling smell but is not itself a cloud-boundary
-- violation.
SELECT exchange_id, task, call_id, prefix_class,
       exact_target, selector_conflict,
       mutates_or_reads_global_auth_config AS auth_or_config,
       prohibited_reference,
       gcloud_invocations,
       substr(command, 1, 500) AS command_preview
FROM _conflux_audit_terminal_boundary
WHERE arguments_valid = 0 OR command IS NULL
   OR exact_target = 0
   OR selector_conflict <> 0
   OR mutates_or_reads_global_auth_config <> 0
   OR prohibited_reference <> 0
   OR gcloud_invocations <> 1
   OR prefix_class = 'other-local-prefix'
ORDER BY exchange_id, call_id;

-- Durable-job and acceptance evidence that is present in the transcript.
-- These rows are leads for independent remote checks, not proof of current
-- state.  exit_code belongs to the client-side tool wrapper.  Only the three
-- newest rows in each category are shown so a long polling loop stays usable.
WITH evidence AS (
    SELECT c.exchange_id, c.task, c.call_id, r.exit_code,
           c.command, r.output,
           CASE
             WHEN lower(c.command) LIKE '%qemu-system-aarch64%'
               THEN 'qemu-command'
             WHEN lower(c.command) LIKE '%uname -m%'
               OR lower(c.command) LIKE '%hw.machine_arch%'
               THEN 'guest-architecture'
             WHEN lower(c.command) LIKE '%sha256sum%'
               THEN 'artifact-hash'
             WHEN lower(c.command) LIKE '%nohup%'
               THEN 'durable-launch'
             WHEN lower(c.command) LIKE '%ppid%'
               THEN 'durability-check'
             WHEN lower(c.command) LIKE '%release.pid%'
               OR lower(c.command) LIKE '%release.exit%'
               THEN 'release-status'
           END AS evidence_kind
    FROM _conflux_audit_tool_calls c
    LEFT JOIN _conflux_audit_tool_results r USING (session, call_id)
    JOIN _conflux_audit_config cfg USING (session)
    WHERE c.tool_name = 'terminal'
), ranked AS (
    SELECT *, ROW_NUMBER() OVER (
             PARTITION BY evidence_kind ORDER BY exchange_id DESC
           ) AS newest
    FROM evidence
    WHERE evidence_kind IS NOT NULL
)
SELECT evidence_kind, exchange_id, task, call_id, exit_code,
       substr(command, 1, 500) AS command_preview,
       substr(output, 1, 1000) AS observed_output
FROM ranked
WHERE newest <= 3
ORDER BY evidence_kind, exchange_id;

-- Machine-readable evidence indicators.  Review the linked rows above: a
-- nonzero count only says the command/result appeared in the tool transcript.
SELECT
  SUM(lower(c.command) LIKE '%nohup%' AND COALESCE(r.exit_code, -1) = 0)
    AS successful_detached_launch_results,
  SUM(lower(c.command) LIKE '%sha256sum%' AND COALESCE(r.exit_code, -1) = 0)
    AS successful_sha256_results,
  SUM(lower(c.command) LIKE '%qemu-system-aarch64%'
      AND lower(c.command) LIKE '%accel=tcg%') AS explicit_aarch64_tcg_commands,
  SUM(lower(COALESCE(r.output, '')) LIKE '%machine=evbarm%'
      AND lower(COALESCE(r.output, '')) LIKE '%arch=aarch64%')
    AS guest_arch_marker_results
FROM _conflux_audit_tool_calls c
LEFT JOIN _conflux_audit_tool_results r USING (session, call_id)
JOIN _conflux_audit_config cfg USING (session)
WHERE c.tool_name = 'terminal';

-- Final supervision acceptance.  PASS requires a non-escalated agent_end
-- after the last tool step, a passed agentic-final verifier in that same task,
-- and exactly one persisted client response.  NOT COMPLETE is expected while
-- the agent is still returning tool calls.
WITH latest_tool AS (
    SELECT MAX(e.ts) AS ts
    FROM events e, _conflux_audit_config c
    WHERE e.session = c.session AND e.kind = 'tool_step'
), final_tasks AS (
    SELECT e.session, e.task,
           MAX(CASE WHEN e.kind = 'agent_end' THEN e.ts END) AS end_ts,
           SUM(CASE
                 WHEN e.kind = 'verify'
                  AND json_extract(e.data, '$.stage') = 'agentic-final'
                  AND json_extract(e.data, '$.passed') = 1
                 THEN 1 ELSE 0
               END) AS passed_agentic_verifies,
           MAX(CASE WHEN e.kind = 'agent_end'
                    THEN COALESCE(json_extract(e.data, '$.escalated'), '') END)
             AS escalation
    FROM events e, _conflux_audit_config c
    WHERE e.session = c.session
    GROUP BY e.session, e.task
), response_counts AS (
    SELECT session, task, SUM(kind = 'client_response') AS client_responses
    FROM exchanges
    GROUP BY session, task
), accepted AS (
    SELECT f.*
    FROM final_tasks f
    LEFT JOIN response_counts r USING (session, task)
    CROSS JOIN latest_tool l
    WHERE f.end_ts IS NOT NULL
      AND f.end_ts > COALESCE(l.ts, 0)
      AND f.passed_agentic_verifies >= 1
      AND COALESCE(f.escalation, '') = ''
      AND COALESCE(r.client_responses, 0) = 1
)
SELECT CASE WHEN EXISTS (SELECT 1 FROM accepted)
            THEN 'PASS' ELSE 'NOT COMPLETE' END AS final_supervision_status,
       (SELECT datetime(MAX(ts), 'unixepoch')
          FROM events e, _conflux_audit_config c
         WHERE e.session = c.session AND e.kind = 'tool_step') AS last_tool_utc,
       (SELECT datetime(MAX(end_ts), 'unixepoch') FROM final_tasks)
         AS last_agent_end_utc,
       (SELECT SUM(passed_agentic_verifies) FROM final_tasks)
         AS passed_agentic_final_verifies;
