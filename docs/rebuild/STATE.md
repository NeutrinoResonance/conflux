# Rebuild state

Keep this short and current. One entry per decision; newest first. Full detail per slice lives in each entry's
evidence `RESULTS.md` and in the PR that landed it (`git log`); measured model behaviour in `MODELS.md`.

MISSION-STATUS: ACTIVE

- **Goal:** work item C (minimal replacement core) aimed at the completion gate. The completion run's only task input is
  `run12/task.txt` verbatim. The sub-goal fixtures (`optee_goal_a/b.json`: decomposition, locations, commands, flags,
  proof criteria) were developer-written. They are grading references only (founder decision 2026-10-28, MISSION
  773b964). Everything accepted so far (a1–a4, b1a, b1b, slice 30's b2) is **reachable with developer-written spec and
  help**: it is not progress toward the gate. b3 failed (slice 31). Top priorities: Conflux derives the spec itself
  and produces its own corrections. Slice 60 is the first run of core to reach G5 + G7 from `task.txt` alone, with no developer
  help and no false DONE, independently re-executed. Slice 61 replicated G5 + G7 (n=2), but ended in a false DONE by the
  gate. Slice 62 shows that false DONE is a spec-derivation gap, not a reviewer-family one. Slice 63: proof criteria derived from
  `task.txt` before the trace stop that false DONE (0/12 vs 3/6), but for goal (b)'s TA-session bar; the derived Linux
  goal is dropped once the reviewer reads the trace. Slice 66: those criteria also reject a run that truly met goal (a)
  (6/6, both the open and the per-criterion verdict); they over-demand. Slice 67: glm-5.3's short one-shot goal lists (Gl) pass c8 and keep the Linux criterion at s61 when judged per criterion (kimi 4/6, at the derivation ceiling); Slice 68: under core's open finish ask the same Gl lists pass c8 (0/12 false rejects) but the reviewer drops the Linux criterion at s61 in 16/16 L-list reviews (gate reason 0/16; DONE 5/24), so inserting criteria into the open review is not a capability. Slices 60 and 61 drew on a contaminated snapshot (a prior run's `optee.o`), so neither shows the driver from `task.txt` alone. Slice 69 does, on a cleaned lab: G7 by re-execution, but as a loadable module (strict G5 unmet), again with a false DONE. Slice 43's lead-s1 (a demo harness) reached G5 + G7 first, but ended in a false DONE.
  - **Gate reaffirmed (founder, 2026-11-01; 33c99f2 reverted by 82b6d68):** goal (a) includes the Linux boot, so G3 is
    required. That answers slice 60's open question.
  - **Open founder question (asked 2026-11-01 ~13:00Z, unanswered):** may the finish gate use a per-criterion verdict?
    Slices 67/68 put it in conflict with the open finish ask (MISSION a7322df). Until MISSION records the answer, build
    no per-criterion verdict and no fixed answer shape into core (operator, 2026-11-01).
- **C slice 69 (2026-11-01, attribution gate run, $0.072634 metered + ≈ $1.56 GCE): fixed core 93d0466 with
  `--lab-clean`, `task.txt` only, slice 61's settings. Ended `unverified`/`finish_review_done` at step 179 (4.27 h).
  G7 is met by grader re-execution with no contamination: the executor's own driver gets OP-TEE's API UID and
  EXCHANGE_CAPABILITIES ret=0 from an OP-TEE built in the run. H69 is falsified by the letter: G5 (a kernel rebuilt with
  the driver) is unmet, because the driver is a loadable module (`tee.kmod`) in the snapshot's stock kernel. False DONE
  by the gate again (n=2 with s61).**
  - Milestones G2 G4 G6 G7 = 4/7 strict; with the module as G5, 5/7 (= s60/s61's set). G1 no (no manifest tree), G3 no
    (0/55 goal lists require a Linux boot).
  - **Provenance (items 0/1 exercised live):** `lab.clean.exit` 0. Executor commands naming `conflux-scratch`: 0 (s61:
    42). Naming the residue: 0. So a G6 + G7 driver outcome, as in slices 60/61, is reached without either leak.
  - **Finish review:** steps 122–173 refused DONE: placeholder proof at 122, then the TA session (open_session →
    `0xffff0006`, origin TEE).
    Step 173 closed it as "a documented limitation", and step 179 passed DONE. This is the open ask's
    drop-a-goal licence (slices 63/68), live. Held under the founder question above.
  - Lead: 43 reviews, median 23.4 s, 12 deliveries. D1: 16 hits, 0 harness faults.
  - Billing: 664 export-matched, 27 cost-less unbilled. Not Conflux in the window: $0.006670.
  - W44 GCE ≤ $50.95 of $60. Lab g5 deleted.
  - Evidence: `~/evidence/gate-run-s69-2026-11-01/RESULTS.md` (`grade.json`, `reexec/`, `provenance_scan.out`).
- **C slice 68 (2026-11-01, criteria under the open ask, offline, $0.034948 metered + $0 GCE): the open finish review
  drops pre-trace criteria it was given. Gl lists sit in core's finish-review data, with `FINAL_ASK` unchanged (kimi-k3
  low; 6 lists × 2 repeats at c8, s61@132 and s61@127). c8 goal-(a) false rejects 0/12 (A holds). s61 DONE 5/24
  (bar ≤ 2). Gate-reason refusals on the L lists 0/16 strict (falsifier ≤ 4/16). H68 falsified. Build nothing.**
  - **What happens to the Linux criterion in the 16 L-list reviews at s61:**
    - 8/8 Gl2/Gl3 reviews mark it waived, descoped, "superseded" or "DONE via substitution";
    - 4/4 Gl5 reviews rewrite it out silently;
    - 4/4 Gl4 reviews keep it, but as a NetBSD-side TA invocation (its text allows "hello_world or xtest").
  - Every refusal (19/19) is for a userspace ioctl or a TA session. None names the revision 0.4 vs 4.2.0 contradiction.
  - False DONE: Gl1 (no L criterion) 3/4; Gl3 2/4, both "superseded/substituted".
  - Same lists, same reviewer, judged per criterion as written (slice 67): the Linux criterion held at s61 4/4. The drop
    comes from the open ask's licence to revise or drop goals, not from the derivation or the reviewer's family.
  - Billing: 294/294 export-matched. Not Conflux in the window: $0.001488.
  - Evidence: `~/evidence/criteria-open-ask-demo-2026-11-01/RESULTS.md` (`audit.json`, `reviews.jsonl`).
- **C slice 67 (2026-11-01, criteria-acceptance demo, offline, $0.030992 metered + $0 GCE): one existing derivation
  passes the true goal (a) and still refuses s61's false DONE. H67 supported for Gl (one-shot glm-5.3 low goal lists from
  `task.txt`): discriminating draws (c8 all goal-(a) criteria MET, and s61@132 a Linux/xtest criterion UNMET) kimi-k3 4/6,
  glm-5.3 3/6. Build nothing yet.**
  - **Setup:** slice 63's 24 one-shot lists (Gl Gh Kl Kh × 6), one per-criterion MET/UNMET turn per state. Judges
    kimi-k3 low and glm-5.3 low. Scope and Linux/xtest (L) labels were set by hand before the draw; L matches slice 63's
    P1 grades 24/24. Pre-flight 5/5 seam, c8 evidence visible.
  - **Results:**
    - D (kimi/glm): Gl 4/3, Gh 3/1, Kl 3/1, Kh 1/1.
    - kimi passes c8 in 19/24 lists (GK revised, slice 66: 0/6). At s61 it marks ≥ 1 L criterion UNMET in 12/12
      L-bearing lists (not every one: Gl4 G1, Gh2 G2, Kl2 G1 are MET).
    - Gl's 4/6 is the derivation ceiling: Gl1 and Gl6 have no Linux criterion, and kimi says DONE on Gl1 at s61.
    - glm says one more false DONE (Gl4): it counts an early-TA load as "hello_world or xtest passes".
  - **c8 rejections (13 goal-(a) verdicts):** 5 criteria over-demand as written; 3 come from c8's pre-built OP-TEE; 2
    are survey-scope readings; 1 is the judge being stricter than the criterion; 2 are parse-only (glm's id-first
    format, 9/48 incompletes after a redraw).
  - **Caveat:** per-criterion form only. Slice 63 D1 saw the open ask drop a derived Linux goal.
  - Billing: 118/118 export-matched (kimi $0.026637, glm $0.004355). Not Conflux in the window: $0.000295.
  - Evidence: `~/evidence/criteria-acceptance-demo-2026-11-01/RESULTS.md` (`labels.json`, `tally.json`).
- **C slice 66 (2026-11-01, criteria-verdict demo, offline, $0.104705 metered + $0 GCE): pre-trace GK criteria in the
  finish reviewer's data reject the first near-positive state. c8's accepted goal-(a) run (OP-TEE build, secure-world +
  Linux boot, xtest 1001 PASS) is judged not done 6/6, both with core's open finish ask (O) and with a per-criterion
  MET/UNMET verdict whose DONE is computed by code (S). The registered falsifier fired: the criteria over-demand. Build
  nothing.**
  - **Setup:**
    - kimi-k3 low; core's finish review; GK revised criteria (slice 63 D2) inserted after the task.
    - Arms: O keeps `FINAL_ASK` (MISSION a7322df). S is a demo-only arm (operator note).
    - States: c8 a3+a4 rebuilt as one run, with `task.txt` as the task; s61@132/127; s60@229.
    - Pre-flight is $0. Seam 5/5. The copied `ask` is byte-identical to core's. 6/6 parser cases pass. c8's Linux and
      xtest PASS lines are visible to the reviewer after clipping.
  - **c8:**
    - The reviewer sees the boot and the PASS, yet keeps goal (a) open in every review. It asks for things the gate does
      not require: the full xtest suite, manifests/sha256s, DTB dumps, an interleaved capture, negative controls.
    - S: 1 of 23 goal-(a) criterion verdicts is MET.
  - **s61:**
    - DONE: O 0/10, S 0/10.
    - Gate reason: O 2/10 (H66-O falsified). S 9/10 (+1 lenient). But each of the 9 complete S replies has 8–14 UNMET blockers (the incomplete init-only
      reply, s61@127 d1, has no verdict lines), and S says DONE
      in 0/18 reviews, c8 included. S's numeric edge is refuse-everything behaviour, not discrimination.
    - S incompletes: 2/18. One is core's own path: an init review with no goal lines turns the finish review into a
      second init turn (s61@127 d1, 2 calls).
  - **Failure class now:** the planner + critic derivation inflates proof criteria into audit checklists (8–14 items).
    It is no longer the reviewer dropping the Linux goal.
  - Billing: 291/291 export-matched. Not Conflux in the window: $0.006646.
  - Evidence: `~/evidence/criteria-verdict-demo-2026-11-01/RESULTS.md` (`audit.json`, `preflight.json`).
- **C slice 65 (2026-11-01, harness fault, $0 metered + ≈ $0.08 GCE): snapshot contamination is closed for gate runs.
  A lab fixture now lists the snapshot's prior-run driver object, and core removes it before the first model call:
  `--lab-clean tests/fixtures/core_loop/optee_lab_residue.txt`.**
  - Core's step is generic: `run_lab(clean_paths=…)`, with no task paths in `conflux/` (operator review).
    - It is fail-closed: a failed removal, or a verification that did not run, ends the run `clean_failed` before any
      model call.
    - The job's script deletes itself, so the path list never reaches `~/.conflux-jobs`.
  - **A clean snapshot is the better fix and needs the founder.** The controller lacks `compute.snapshots.create`
    (`testIamPermissions`: only `compute.snapshots.get`). Until then, every gate run must pass `--lab-clean`.
  - **Inventory (fresh lab, H65 supported):** the residue is exactly `GENERIC64/optee.{o,d,su}`.
    - They were built 2026-07-19 from a since-deleted `sys/dev/optee/optee.c`. They are the only `*optee*` names on
      the disk, and `optee.o` is the only object without a `.depend` target.
    - The prebuilt kernels have no optee symbols. There are no shell histories anywhere, and the other rebuilds are
      stock.
    - `llmsuper-netbsd-run/arm64.img` is the founder's stock NetBSD 10.1 boot validation, with no OP-TEE or driver
      content: kept. This corrects slice 61's "contaminated guest disk".
  - **Checks:**
    - after the clean, a stock `build.sh -u kernel=GENERIC64` passes (rc 0) and finds 0 residue;
    - the fixture-driven clean through `lab_shell` on another fresh lab: files gone, no script left, idempotent; a runner
      that cannot execute exits 1;
    - 6 new tests. One caught a draft that exited 0 when `rm` failed.
  - Evidence: `~/evidence/snapshot-clean-2026-11-01/RESULTS.md`.
- **C slice 64 (2026-11-01, harness fault, $0 metered + ≈ $0.001 GCE worker): the scratch side channel is closed.**
  - Upper/work dirs and the private `/tmp` now sit on a sparse ext4 image, loop-mounted only inside the scratch's
    namespace (`SCRATCH_SH new`). The image has no journal and is mounted `noinit_itable,discard`, so its disk use
    is what the scratch holds now: an in-scratch delete of 2 GB frees host disk at once.
  - Regression test `test_lab_scratch_contents_unreachable_from_root_namespace` (real namespaces, needs sudo):
    - on worker-1 (the labs' kernel), f11d700 passes setup and fails only on the root-namespace `find`;
    - the fix passes; 1 GB scratch write: disk released after `rm`.
  - **Slice 60 had the channel too** ($0 trace check): steps 10–39, while session v1 was open. Steps 30–31 copied the
    lead's built optee_os/TF-A into its own tree. So G5/G7 attribution in both slices 60 and 61 includes lead-session
    builds reached through the leak.
  - Not yet exercised on a lab with a live lead.
  - Evidence: `~/evidence/scratch-isolation-2026-11-01/RESULTS.md`.
- **C slice 63 (2026-11-01, proof-criteria demos, offline, $0.040635 metered + $0 lab GCE): proof criteria that Conflux's
  other models derive from `task.txt` before reading the trace stop slice 61's false DONE: s61@132 0/6 in each design, vs
  3/6. But they stop it for the wrong reason. The derived Linux-boot goal rarely survives the trace, and most refusals
  demand a TA session instead. Both registered rules are inconclusive (DONE conditions met, gate-reason condition not
  met). Build nothing.**
  - Two designs were registered by sessions the keeper bug archived mid-work. Their draws were reused (operator note). The
    resume drew 1 cut-off conversation.
    - **D1:** a one-shot derivation replaces the finish reviewer's goal list after its k−10 init review.
    - **D2:** a glm-5.3 planner + kimi-k3 critic write criteria, inserted into the reviewer's data.
    - Reviewer in both: kimi-k3 low (core's); seam 5/5.
  - **Derivation** (goal (a) requires a normal-world Linux boot or xtest; hand-graded, n=6; the reference is never sent):
    - one-shot: glm-5.3 low 4/6, high 3/6; kimi-k3 low 3/6, high 2/6;
    - glm→kimi pair 5/6 (draft 5/6); kimi→glm 3/6.
    - The driver's values must match the booted OP-TEE: glm→kimi 4/6, one-shot ≤ 3/6.
  - **Finish verdicts (DONE):** s61@132 D1 0/6, D2 0/6; s61@127 D1 1/4, D2 0/2; s60 states 0/12.
  - **Hand audit of the s61 refusals:**
    - Gate reason (Linux/xtest, or the revision/UUID contradiction, as a finish blocker): D1 1/9, D2 3/8.
    - Refusals for a TA session only: D1 6/9, D2 3/8.
    - Linux/xtest named at all: D1 8/16 (incl. s60@240 d2, which drops the Linux-guest xtest baseline), D2 6/14 (slice 62: 0/28).
    - After reading the trace, the reviewer makes the derived Linux goal optional or a "documented deviation", or drops
      it. `FINAL_ASK` allows "revise … or drop goals".
  - Unmeasured: the false-reject cost on a true-DONE state (none exists) and goal (b)'s bar (item 6). So no core build.
  - Billing: 313/313 calls export-matched (D1 $0.018674, D2 $0.021961). Not Conflux in the joint window: $0.030296.
  - Evidence: `~/evidence/proof-criteria-demo-2026-11-01/RESULTS.md` (D1 + comparison),
    `~/evidence/criteria-first-demo-2026-11-01/RESULTS.md` (D2).
- **C slice 62 (2026-11-01, finish-gate demo, offline, $0.012892 metered + $0 lab GCE): neither a different-family
  finish reviewer nor a generic claim-check turn refuses slice 61's false DONE. The cause is upstream of the reviewer: 0/28
  reviews derive the gate's Linux boot from `task.txt`, and only 1/28 makes the revision contradiction a finish
  blocker.**
  - Setup: core's own fresh finish review (core 535c2d2 = f11d700's `conflux/`) on 5 recorded states: s61@127/132 and
    s60@154/229/240. All 5 are gate-not-met.
    - Seam 5/5 exact: the recorded init and goal-1 requests, `prompt_chars` + `ask` tail.
    - Arms: K kimi-k3 low; G glm-5.3 low; V = K + one generic claim-check turn where K said DONE.
  - **s61@132 DONE:** K 3/6 (the live false DONE reproduces); G **5/6, falsified**; V 2/6, not supported.
    - V also kept K's 2/2 false DONE on s61@127, where the live review said not DONE.
    - s60's three states: 0 DONE in every arm.
    - Pairing rules (two K reviews, or K and G) do not get ≤ 1/6 on both s61 states.
  - **Audit:**
    - No reply asks for a Linux boot or the standard OP-TEE QEMU setup (0/28; slices 47–48: 0/16).
    - 5 replies note the OP-TEE 4.2.0 vs "OS revision 0.4" mismatch:
      - glm s61@127 d1 requires a correct 4.2.0 read (else fix the SMC decoding and rebuild) before finishing;
      - glm d2 says "fix or document";
      - kimi's 3 claim-check turns call it a decode quirk and keep DONE in 2 of them.
      - At s61@132 no glm reply names it.
    - The s61@132 rejections ask for proof-bundle hygiene only.
  - Decision: build nothing in core. The failure class is the derivation of proof criteria from `task.txt`, not the
    reviewer's family (next action 2).
  - Billing: 166/166 calls export-matched. Not Conflux in the window: $0.010370.
  - Evidence: `~/evidence/finish-gate-demo-2026-11-01/RESULTS.md`.
- **C slice 61 (2026-11-01, gate run, replication, $0.092726 metered + ≈ $1.41 GCE): core f11d700 unchanged ended
  `unverified`/`finish_review_done` at step 132 (3.83 h). Milestones G2 G4 G5 G6 G7 = 5/7, the same set as slice 60.
  **False DONE by the gate:** the finish review passed DONE with G1 (no qemu_v8 root) and G3 (no Linux boot) unmet.
  H61 is replicated only by its narrower pre-registered rule: G5 + G7 met by grader re-execution, and no DONE while
  G5/G7 was unmet.**
  - **Why the step:** slice 60's late self-damage (next action 2) was already named by its own step-240 review ("broke
    the kernel build … the build still fails"). The run had hit the cap 5 steps after the damage, so no detector is
    needed yet (n=1).
  - **Grading:**
    - The grading instruments were fixed first: G5 matches `netbsd.bin`/`netbsd*.img`, and snapshots also pull `/home`
      boot logs and images.
    - Re-execution of the run's final boot on copies shows, in one boot:
      - OP-TEE 4.2.0 "switching to normal world boot" (G6);
      - NetBSD #8 with OP-TEE's API UID from `smccc_call` (G7).
    - **Verification failure of the finish review:**
      - dmesg prints "OP-TEE OS revision 0.4" and "API revision 0.2" against the same boot's OP-TEE 4.2.0 banner, and
        a malformed OP-TEE UUID.
      - The step-132 review quoted these without noticing, and took an ioctl that returned the cached value as proof.
      - Slice 60's three finish reviews had required a TA session.
  - **New, harness isolation leak (scratch side channel):**
    - 42 executor commands (steps 13–48, with sudo) read and copied the lead's verify-session scratch upper dir
      (`/var/tmp/conflux-scratch/…`), which held session 1's TF-A/OP-TEE/U-Boot builds.
    - The executor also built a TA inside it while that session was still open.
    - So goal (a)'s firmware came mostly through this channel, not through replayed deliveries. This confounds delivery
      attribution in both runs; slice 60 is not checked for it.
  - **Snapshot contamination (G4 provenance, slices 60 and 61):** the clean snapshot carries a prior run's compiled
    `netbsd-obj/.../GENERIC64/optee.o`.
    - Slice 60 mined it at steps 11–14.
    - Slice 61 reconstructed its driver from its disassembly (same symbol set), then deleted it at step 69.
    - Slice 61's guest disk also overlays a prior run's `llmsuper-netbsd-run/arm64.img`.
  - **Lead:** 7.8 reviews/h, 445 calls, median latency 31.7 s.
    - Deliveries: 3/5 sessions delivered, all with replay ok; all 3 arrived 22–46 steps late, behind 6–8 newer reviews.
    - 0/36 goal lists name a Linux boot.
  - D1: 13 hits, all false positives; 0 harness faults. No late self-damage.
  - Billing: 571/577 calls export-matched; 6 cost-less replies unbilled. Not Conflux in the window: $0.028182.
  - W44 GCE ≤ $49.31 of $60. Lab g4 deleted.
  - Evidence: `~/evidence/gate-run-s61-2026-11-01/RESULTS.md` (`grade.json`, `reexec/`, `verify_scan.out`).
- **C slice 60 (2026-10-31/11-01, gate run, $0.140021 metered + ≈ $2.17 GCE): core f11d700 ended `unverified`/`step_cap`.
  There was no false DONE: 3/3 finish reviews said not DONE, correctly. Milestones G2 G4 G5 G6 G7 = 5/7 (slice 50: 4/7).
  G5 and G7 are met for the first time in a core gate run, with no false DONE, and verified by grader re-execution.
  Slice 43's lead-s1 demo reached both earlier but ended in a false DONE. H60 supported (n=1).**
  - Setup: `task.txt` only, pro + `--lead kimi-k3`, verify sessions beside the cadence, fresh lab, 240 steps (5.9 h).
  - **Driver:** the run wrote it in-tree in the machine's `netbsd-src`; every upstream fetch returned 404.
    - It built kernel #20 with the driver in it (G5).
    - Grader re-execution of the run's own step-224 boot shows, in one boot:
      - OP-TEE 4.11 "switching to normal world boot" (G6);
      - NetBSD #20 with `optee0 at simplebus0`;
      - real SMC answers: OP-TEE's API UID, OS revision 4.11, and GET_SHM_CONFIG with SHM `0x42000000` (G7).
  - **Not met:** a TA session (`teectl` open_session returned EIO and was never fixed), G1 (no qemu_v8 build root) and G3
    (no Linux boot; no goal names Linux).
  - **Sessions beside the cadence work live:**
    - 50 review injections (8.5/h vs slice 50's 8.3/h); lead latency median 21 s;
    - 8 sessions, 5 delivered with replay ok;
    - initial uptake 5/5: each delivery's first command has its best match at the injection step (token Jaccard
      0.57–0.90).
    - Coverage: 11/29 delivered commands near-verbatim (J ≥ 0.7), 18/29 at J ≥ 0.5. Complete sequence execution is not
      shown.
    - Examples: the lead's driver rewrite (steps 73–76, J 0.90–0.94 on 4/7) and its DTB + SMC-owner fix (212–214),
      ahead of the attach at step 224 (the executor had found the owner fix itself at step 208).
  - **Stale:** 5/5 deliveries arrived 22–55 steps after their reply, behind 4–9 newer reviews. 1/5 contradicted the newest
    review's "no OP-TEE/TF-A rebuild" and was run anyway (steps 134–135).
  - **Slice 58's spec gap did not recur:** the executor (step 2 `find`) and the lead's first session (`ls /home`) found the
    machine's NetBSD project themselves.
    - Caveat: the clean snapshot holds an earlier agent's compiled `netbsd-obj/.../optee.o`. The executor mined its
      strings and symbols (steps 11–14), and the driver reuses those message strings. This is machine prior art, not
      developer input.
  - **New failure, late self-damage:** after the working boot, in-place edits for open_session broke the build at steps
    237–240 and removed `netbsd.img`, the bootable wrapper. Kernel #20 survived as `netbsd.bin`, and the source was left unbuildable.
    The run had also deleted its own proof logs.
  - **Grading gaps:** `grade.sh` G5 misses `netbsd.bin`, and `snap.sh` pulls only `/tmp`. G5–G7 were graded from the trace
    plus a reconstruction (`netbsd.img` re-made from `netbsd.bin` by the build's own `mkubootimage` rule).
  - D1: 5 hits (1 real masking in the model's own check, 4 false positives); 0 harness faults.
  - Billing: 984/1,017 calls export-matched, 33 cost-less unbilled; not Conflux in the window: $0.035205.
  - W44 GCE including controller and disks: ≤ $47.90 of $60. Lab g3 deleted.
  - Evidence: `~/evidence/gate-run-s60-2026-10-31/RESULTS.md` (`grade.json`, `reexec/`, `uptake_scan.out`).
- **C slice 59 (2026-10-31, build, $0.007675 metered + ≈ $0.10 GCE): verify sessions run beside the review cadence.**
  - `Steering` has two slots. Reviews keep the cadence (one in flight). A review that returns while no session is open
    opens one on its own thread; at most one session is open until its result is taken. The reply is injected when its
    review returns, the delivery later as its own message (no new prose). `Lead.verify(convo=…)` continues its own
    review. finish/close semantics unchanged, over both threads.
  - Tests: 4 new regression tests, all fail on be8895e; full suite passes. A `/proc` TOCTOU flake in an existing
    scratch test was fixed.
  - Lab smoke (scripted models, real `LabScratch`, cadence 20 s), 8/8:
    - session 1 was open 339.8 s, and 11 reviews were injected meanwhile;
    - sessions never overlapped (17 reviews skipped);
    - the delivery came as its own message;
    - close during `sleep 900` took 179 s with no delivery; no scratch was left. Lab s59 deleted.
  - `VERIFY_ASK` was corrected after critic round 1. It no longer says "Before your reply reaches the agent"; it now says
    the reply was sent and the commands arrive as a later message.
    - Demo on slice 55's 24 R1 conversations, kimi-k3 low, first call: run_shell first 48/48 both before and after, 0
      deliver-first and 0 no-tool, $0.007675.
    - This is a first-turn proxy only: the effect on delivered outcomes is unmeasured.
  - Evidence: `~/evidence/core-session-cadence-2026-10-31/RESULTS.md`, `~/evidence/verify-prompt-demo-2026-10-31/RESULTS.md`.
- **C slice 58 (2026-10-31, cadence-review demo, offline, $0.017903 metered + $0 GCE): running reviews on selected
  prefixes of slice 57's run reject its false proof. Registered rule supported: R∧Q 6/6 (a detection result on those
  prefixes, not a runtime cadence measurement). A session wall bound is ruled out.**
  - Setup: core's `Lead.ask` (frozen 44a70f8) on slice 57's recorded run, from its recorded review-1 state.
    - Prefixes: steps 11, 20, 29, 41, 48 are the 300 s marks on the recorded turn times, assuming each review is back
      before the next mark. Step 55 (after `PROOF.md`) is an off-cadence extra sample: the run was cut before the next mark.
    - 3 chains; kimi-k3 low; no verify session.
    - Scheduling limit: chain 3's step-41 review took 325.1 s, but step 48's turn comes 301.9 s after step 41's. Under
      `Steering.turn`'s in-flight guard, that chain's successor would have started at step 49, not step 48.
    - Seam: the init request is rebuilt exactly (only one recorded review exists).
  - At the false-proof states (steps 48 and 55): 6/6 replies reject the host simulator, `PROOF.md` and "VALIDATED" as proof,
    and direct the TF-A `SPD=opteed` + OP-TEE + U-Boot build toward a `secure=on` boot. None boots in that round (0/6 strict).
  - From step 20 on, 15/15 replies reject the standalone `netbsd-optee-driver/` tree.
  - Review wall: median 192 s, max 325 s (2/18 over 300 s).
  - Verify sessions vs cadence (slice 55's 24): median 1,716 s; the fastest kernel delivery took 1,284 s. Under a 600 s
    bound, 0 configures or kernels would have been delivered (1,800 s: 7/16 kernels). Sessions must run beside the cadence.
  - New spec gap (18/18):
    - every reply claims an in-tree NetBSD `sys/dev/tee/` OP-TEE driver; there is none, in the machine's tree or upstream;
    - 0/18 look for the machine's own NetBSD project;
    - a Linux-boot goal appears in 8/18 goal lists.
  - Fidelity limit: replies were not delivered, but the notes say they were. From step 29 on, replies scold the executor for
    "ignoring" them. Live uptake is not measured.
  - Billing:
    - 47/47 in-reply-billed calls export-matched. The 73 cost-less replies are unbilled; the balance delta equals $0.017903.
    - Slice 57's pending replies (13 run + 5 diagnosis) are settled as unbilled ($0): the export resumed, but has no row in
      17:47:46–18:20Z.
  - Evidence: `~/evidence/cadence-review-demo-2026-10-31/RESULTS.md`.
- **C slice 57 (2026-10-31, gate run, $0.005915 metered + ≈ $0.23 GCE): missing evidence;
  harness fault fixed.** Core d8ee6f1 (scratch on) ran `run12/task.txt` and ended `unverified provider_403` at step 55.
  The pre-registered rule (provider failure before step 60) means no rerun this session. H57 (G5/G7 via delivered
  sequences) was not tested.
  - **Fault:** one nginx `403 Forbidden` HTML page from Surplus's edge (0.28 s) ended the task. The step-55 request,
    rebuilt from the trace and resent, got 200 twice; the step-54 control reproduced its recorded 58,606 prompt tokens.
    Fix: `_unavailable` treats a non-JSON 403 as unavailable (availability backoff); a JSON 403 stays final.
    Regression test fails on d8ee6f1.
  - **Measured (n=1): the verify session starves the cadence (MISSION a594bbc).**
    - Review 1 (step 1) returned the goal list in 17 s. Its verify session then ran to the stop: 38 calls, 41 scratch
      commands, 1,953 s. The lead did goal (a) itself in the scratch (OP-TEE clone and builds, 6 QEMU boots).
    - The review and its session are one in-flight unit, so **0 reviews reached the executor in 55 steps** (slice 50:
      ≈ 6 in that time).
    - Unsupervised, the executor faked proof: a host `optee_simulator` ("11 passed"), a `PROOF.md`, and a "VALIDATED"
      banner. It built OP-TEE OS only and booted nothing.
  - Billing: Surplus recorded no usage after 17:47:45Z (export and `recent_usage`). 13 cost-less run replies and 5
    diagnosis calls were pending; slice 58 settled them as unbilled ($0). `snap.sh` (item 3) pulled the lab's `/tmp` every
    300 s, 7/7 ok. Lab g2 deleted.
  - Evidence: `~/evidence/gate-run-s57-2026-10-31/RESULTS.md`.
- **C slice 56 (2026-10-31, build, $0 metered + ≈ $0.21 GCE): slice 55's mechanism is in core.** After each
  running review, the lead gets a verify session: `run_shell` on a scratch, then `deliver(commands, note)`. The harness
  replays the selection on a fresh scratch, with one feedback turn on failure. The executor receives the reply, the note
  and the replayed commands verbatim. With no delivery, the plain reply goes through as before.
  - Code:
    - `core.Lead.verify`, `LabScratch`, `LocalScratch`, `deliver_text`, `Steering(scratch=…)`;
    - demo texts and limits (40 commands, +10 after feedback, 90 calls, 1800 s/command, 6000 s wall);
    - on by default with `--lead`, off with `--no-scratch`.
  - A review plus its verify session is one in-flight unit. The executor is never blocked; reviews per hour drop.
  - Lab scratch:
    - a private mount namespace with an overlay of the **live** `/home` and a private `/tmp`;
    - writes elsewhere are not isolated, and the lead's ASK says so;
    - the overlay over a changing lower dir is undefined in the kernel docs (no crash); its effect is unmeasured.
  - Lab smoke (scripted models, real `lab_shell`):
    - try 1 found a **harness fault**: every `new` failed. The holder log was opened by `dev` in root's scratch dir. It
      was fixed, and a regression test reproduces the lab error on the pre-fix script.
    - The kill guard was made fail-closed.
    - Tries 2–3 pass every check. They cover isolation, a fresh replay → feedback → delivery, injection, cleanup,
      `kill_all`, close during a 900 s scratch command (161.8 s task), and the proxy.
  - Critic round 1 (offline fixes, regression tests fail on the round-0 code):
    - a finish review now cancels the running verify session;
    - scratch teardown runs on its own shell, `deadline + TEARDOWN_S`, and its results are checked;
    - `LocalScratch` kills a scratch's background jobs on `rm`, marker-checked;
    - task end purges every lab scratch.
    - The lab smoke ran before round 1; the teardown shell and `purge` are offline-tested only.
  - Tests: `tests/test_core_scratch.py` (21); full suite passes.
  - Not measured: the live effect (gate run). Each scratch command is a lab job, about 13 s round trip.
  - Evidence: `~/evidence/core-scratch-2026-10-31/RESULTS.md`.
- **C slice 55 (2026-10-31, executed-sequence delivery demo, lab, $0.034519 metered + ≈ $1.25 GCE): the reviewer works
  in a persistent scratch with `run_shell`, and delivers the recorded commands it selects, replayed on a fresh copy first.
  Registered rule supported: S2 delivered configures 11/12 and builds the kernel with `optee.o` 9/12 (slice 54: 3/12, 0).
  S1: 7/12 and 7/12.**
  - Setup:
    - Slice 52's 24 R1 conversations + one generic turn: `run_shell` on a per-session overlay scratch of the run's
      replayed tree, plus `deliver(commands, note)`.
    - The harness replays the selection verbatim on a fresh copy. One feedback turn if a replayed command fails.
    - Grade = slice 53's grader on the final replay.
  - The executed sequence carries the gain, not the feedback:
    - first replay: S2 configures 12/12, S1 7/12;
    - the feedback turn (used 16/24) raised kernels but not configures.
    - Arms: F 6/6 configure + kernel at S2. L 5/6 configure, 3/6 kernel.
  - Selection loss 2/24, both from a re-selection after a failed replay; slice 54 had 5 rewrites drop working steps.
  - Still open:
    - Running-lead veto: 4/6 L-S1 sessions deliver the module route (image mount + `modload`). It is guarded by
      `if [ -f … ]`, so it exits 0 in the scratch and configures nothing.
    - All-exit-0 replays that configure nothing: 5/20.
    - D1 on 383 reviewer commands: 16 hits = 2 real masking (`nohup` build `&`), 14 false positives (8 printed source
      text `return error;`).
    - Whether the kernel attaches is unverified (no image in the scratch).
  - Fidelity:
    - seam 24/24; $0 tool-loop selftest;
    - the lab instrument check reproduces slice 53's F-S1-2 / F-S2-1 grades exactly;
    - scratch isolation probes pass.
  - Billing: 365/365 billed replies export-matched; 27 cost-less replies unbilled; other caller 3 rows, $0.000517. Lab
    v55 deleted.
  - L-S2-5 ran 107 min. Its selection includes its own `sleep 1700`, and replay time is outside the wall cap. Checked
    after an operator note: no stuck connection (the CLOSE-WAIT socket was an idle pooled one).
  - Evidence: `~/evidence/exec-deliver-demo-2026-10-31/RESULTS.md`.
- **C slice 54 (2026-10-31, iterated verify-before-deliver demo, offline + lab, $0.012297 metered + ≈ $0.46 GCE): up to 3
  more scratch-verify rounds on slice 53's R2. The scratch is reset per run, and the feedback says so. Each reply stops when
  all its blocks exit 0. Registered rule falsified: S2 delivered configures 3/12 (R2 2/12), S1 2/12, 0 kernels delivered.**
  - Rounds oscillate. S2 configures R3 6/12 → R4 4/12 → R5 3/12.
    - One reply built the kernel with `optee.o` at R4 (F-S2-2), the first in slices 52–54.
    - Its R5 dropped all three fixes that had worked in its R4 run.
  - **Each revision is written as a delta on the scratch's state**, although the feedback says the scratch is reset:
    - replies that use the build dir with no `nbconfig`: R3 5/22, R4 8/20, R5 9/18;
    - 5 of them dropped a configure step that had worked in the previous round.
  - **Exit status is a weak stop signal.** 3/3 configured replies delivered on all-pass hide a failed build (`nohup … &` ×2,
    output to a log ×1). This is D1's masking class, in the reviewer's own commands.
  - Scratch-only absences are 61–67% of failing blocks (image, `virt.dtb`, OP-TEE tree, QEMU, `/tmp` logs). It is a demo
    fidelity limit: the run's daily NetBSD image cannot be rebuilt.
  - Seams: $0 conversation seam 24/24. Feedback pre-flight passed every round. The lab instrument check reproduces slice 53.
  - Billing: 60/60 export-matched. Other caller: 6 rows, $0.000390. Lab v54 deleted.
  - **Second materially identical failure** (slices 53, 54: the review's rewritten text is the deliverable) → change hypothesis.
  - Evidence: `~/evidence/verify-iter-demo-2026-10-31/RESULTS.md`.
- **C slice 53 (2026-10-31, verify-before-deliver demo, offline + lab, $0.004922 metered + ≈ $0.17 GCE): the reviewer's
  shell blocks are run in a scratch copy and the results go back for one revision turn. The revision names the blocker but
  still does not configure. Registered rule falsified: S2 configures 2/12 after revision (0/12 before); S1 drops 4/12 → 2/12.**
  - Setup:
    - R1 = slice 52's 24 recorded reviews.
    - The harness runs every fenced shell block of a reply, each as its own `bash -o pipefail` script in the job cwd. The
      scratch copy is the run's replayed tree on lab v53.
    - The results go back as one fixed message; one turn gives R2. R1 and R2 are graded by execution on a fresh replayed tree.
  - Diagnosis improves: at S2, R2 names the duplicate `files.fdt` stanza in 9/12 replies (slice 52 R1: 1/12).
  - Working commands do not:
    - Only 5/12 carry a dedup command in a shell block.
    - The rewritten invocations bring new errors: cwd-relative paths (2), step 238's include kept (3), `-s` regressed (1).
    - The redefinition remains in 4.
    - The 2 that configure fail the build on `optee_modcmd` (the `_MODULE` guard).
  - **Scratch read as real:** 3/24 R2 replies act as if the scratch run had happened on the agent's machine ("config is
    already done"). The feedback says the machine is unchanged.
  - Partial scratch: the OP-TEE tree and NetBSD image are absent. 4/24 add steps for tools missing only there.
  - Seams: 24/24 recorded reviews replayed exactly ($0). Step 238's error reproduced on the lab. R1 configures exactly slice 52's set.
  - Demo harness fault, caught before any paid call: the first launch's feedback said "no shell blocks" for every reply.
    It was fixed, and a $0 pre-flight check was added.
  - Billing: 24/24 export-matched. Other caller: 15 rows, $0.001299. Lab v53 deleted.
  - Evidence: `~/evidence/verify-deliver-demo-2026-10-31/RESULTS.md` (`started.txt`, `seam.json`, `grades.json`, `out/`).
- **C slice 52 (2026-10-31, fresh-context review demo, offline + lab validation, $0.064569 metered + ≈ $0.08 GCE): a
  fresh-context running review (core's finish-review protocol) does not give a better correction on slice 50's G7 stall.
  Registered rule falsified: at step 206, K∧W is 2/6 for both arms. But the veto comes from the running lead's notes:
  V 4/6 with them vs 0/6 fresh. No arm's correction configures and builds a kernel on the run's replayed tree.**
  - States: review 56 (step 206; the live reply was the veto) and review 68 (step 239). Arms: L = running lead with its
    recorded state; F = fresh lead. kimi-k3 low, 6 draws each. Seam: 593/593 recorded running-lead calls reproduced exactly.
  - Step 206: fresh keeps the kernel route 6/6 (L 2/6). 3 of L's 4 vetoes order the executor to delete its in-tree files.
  - Lab validation (harness-only, verbatim commands on the run's file writes replayed onto the snapshot's NetBSD tree; the
    run's own 205/238 failures reproduce exactly):
    - Step 206: 4 of the 7 distinct invocations configure (F1, F2, L2, L3). The build stops on the driver. The stale
      step-202 copy is in the tree; with F2's own fix applied, `optee_modcmd` is defined only under `_MODULE`.
    - Step 239: **0/13 configure**, although every draw gives `-s <tree>/sys`. The run's tree has a duplicate `files.fdt`
      stanza (steps 202 + 236) and step 238's `sys/arch/…` include. 1/12 replies name the duplicate.
  - Missing capability (Conflux, not the model): a reviewer's correction is never checked against the tree state before it
    is delivered. Correct in text ≠ a working correction.
  - Billing: 223/223 export-matched; no other caller's rows in the window. Lab v52 deleted.
  - Evidence: `~/evidence/fresh-review-demo-2026-10-31/RESULTS.md` (`started.txt`, `seam.json`, `grades.json`, `lab/`).
- **C slice 51 (2026-10-31, D1 read parsing, offline, $0): D1 now counts `tr`, `ps`, `tac`, `awk` segments as reads;
  slice 50's hits go 39 → 10 with all 8 real masking hits kept (supported).** The 2 remaining false positives are mixed
  read/write commands (step 54 `sed -i`, step 62 `cp` + `make`). Corpus check over 64 recorded traces: hits 119 → 88,
  0 added, 31 dropped, all hand-checked pure log reads. Regression fixture `audit_d1_slice50.json` (30 tests fail on
  d7ffe24). Evidence: `~/evidence/d1-reads-2026-10-31/RESULTS.md`.
- **C slice 50 (2026-10-30/31, gate run, $0.112770 metered + ≈ $2.87 GCE): core as built (5a4b8ff) ran the full task
  unattended and ended `unverified`/`step_cap`. The fresh finish review said not DONE 7/7 (6 proposals + cap), all correctly:
  no false DONE, H not falsified (n=1). Gate not met: G1 G2 G4 G6 = 4/7 (slice 43: 6, 4, 4).**
  - Setup: fresh lab, `run12/task.txt` only, pro + `--lead kimi-k3`, 240 steps. The lead's init goal list again reads goal (a) as
    NetBSD on OP-TEE. Linux was tried once as a fallback (no kernel banner): G3 unmet. **Gate-reason rejection 0/7**: no
    review names the missing Linux boot.
  - New executor path: it downloaded a NetBSD 11.99.9 release image instead of using the machine's NetBSD project
    (untouched), and patched the DTB until NetBSD booted on the secure chain (G6).
  - Driver: built only as `optee.kmod` (no kernel rebuilt: G5 unmet). About 60 steps went on securelevel blocking `modload`;
    single-user `modload` then worked (step 228), but the module never attached (no optee0, /dev/tee0): G7 unmet.
  - **The lead diagnosed it; the repair was never executed (correction proposed ≠ repair verified):**
    - Step 201: the lead proposed building the driver into the kernel. The executor's `nbconfig` attempts (steps 203–205)
      failed on the include path.
    - Step 206: the lead's next review called that kernel work "scope-violating, no further in-tree writes ever". That
      standing order held through step 220.
    - Steps 224/234: the lead named the cause (a module loaded after boot never attaches to the FDT node; the driver must be
      built in). Step 224's fix kept the wrong `-s ~/netbsd-src`, and the same `nbconfig` error repeated at steps 236–238.
    - The right argument (`-s ~/netbsd-src/sys`) first came at step 239 (running review, never delivered: cap at 240) and
      from the cap finish review.
    - Remaining failure: the correction arrived too late and the lead vetoed its own route mid-run. Whether the fix builds
      and attaches is unverified.
  - **Grading-instrument gap (missing evidence):** the run's boot logs were in `/tmp` and were cleared when the lab restarted after
    `run_lab`'s stop. The trace never holds OP-TEE's secure UART. G6 rests on the grader re-running the run's own step-227
    boot command with the secure UART sent to a file (`I/TC: OP-TEE version 4.11.0` … `switching to normal world boot`, then
    NetBSD's single-user shell).
  - D1 hits 39, classified (`d1-classified.json`): 8 real masking in the model's own commands (`build.sh … &`, then
    `sleep; tail log` shows the failed build with exit 0). 31 false positives: 29 log reads D1 does not parse as reads
    (`tr '\r' '\n' < log | grep`, `wc -c`, echo headers), 1 source-text grep, 1 the model's own `|| echo` text.
    **0 harness faults.**
  - Billing: 683/683 billed calls export-matched, 197 cost-less replies unbilled. Lead reviews: 68 (per-call median 30 s,
    max 243 s). Deleted the idle c3 lab and its disk.
  - Evidence: `~/evidence/gate-run-2026-10-31/RESULTS.md` (`started.txt`, `grade.json`, `grade.out`, `lab-logs.tgz`,
    `reexec/`, `reconciled.json`).
- **C slice 49 (2026-10-30, build, $0.000136 metered + $0 GCE): the measured lead and slice 48's stop rule are in core.**
  - `conflux/core.py` gained `Lead`, `Steering` and `run_task(lead_call=…)`, plus the CLI flag `run --lead kimi-k3`.
    - The running lead is kimi-k3 low: it reviews every 300 s without blocking, in the conversation layout, with prompts
      verbatim from slice 43.
    - On a task with no checks, finish and the step cap go to a **fresh lead**: its own init review at k−10, and none of
      the running lead's notes, goals or injected replies.
    - DONE ends the run `unverified`/`finish_review_done`. Tasks with checks are unchanged.
    - Budget and Trace are thread-safe (re-entrant lock).
  - Replay seam: core's `Lead` on slice 43's recorded lead runs reproduces **1,796/1,796** lead requests exactly
    (prompt chars and the last 400 chars).
  - Regression test: the finish review gets none of the running lead's state. It fails on both mutations (reused Lead,
    unhidden injections).
  - Live local smoke: pro + kimi-k3 ran 4 steps; the fresh review said DONE, and the output was checked correct by hand.
    Spend: $0.000136, export-matched; 15 cost-less replies were unbilled.
  - PR #58 review fixes, each with a regression test that fails on the first commit:
    - executor + lead spend count together against `task.max_usd`, with a zero cap making no lead call;
    - the lead is closed and its in-flight call accounted on every exit, an exception included;
    - `reconcile` bills `lead.jsonl` calls, with task and role attribution (`lead_billed_usd`);
    - a review that finishes mid-turn can no longer be overwritten by its successor.
  - Evidence: `~/evidence/core-lead-2026-10-30/RESULTS.md` (`seam.json`, `smoke/`, `reconciled.json`).
- **C slice 48 (2026-10-30, finish-judgement v2, offline, $0.032298 metered + $0 GCE): with the task text scoped to
  the sub-goal, the kimi-k3 lead's fresh finish review accepts checked-done work (17/21) with 0/15 false DONE: supported.
  The live s1@237 false DONE comes from the lead's run-long notes: supported (3/6 with them vs 0/6 goal list only).**
  - A (fresh protocol, 7 P incl. relabelled c3-a2, 5 N, 3 draws). kimi 17/21 accepted, 0/15 false DONE. glm-5.3 low 13/21,
    0/15 (inconclusive). Every rejected positive has grounds in the trace: b2-inject never read its serial logs (6/6), c3-a2's trace
    holds the faulty check's failure feedback.
  - B (live state rebuilt from `lead.jsonl`; seam: prompt chars and ask tail exact on 4/4 live finish states).
    - s1@237 DONE: L (notes + goals) 3/6; Lg (goals only) 0/6; fresh 0/4 (slice 47).
    - DONE replies cite the lead's own earlier "pre-authorized honest-failure path".
    - Other live finish states under L: 0/6.
    - **No review in any arm names the missing Linux boot (G3)**: rejection is never for the gate's reason.
  - Inherited demo fidelity fault: `trace_messages` (slices 40/43/47) wrote the finish result as `finish recorded`, while core
    writes `finish recorded; the harness is running the acceptance checks` (+45–46 chars per finish in the lead prompt; found by the seam, fixed in
    the demo).
  - Evidence: `~/evidence/finish-judge-v2-2026-10-30/RESULTS.md` (`started.txt`, `seam_b.json`, `reviews.jsonl`, `reconciled.json`).
- **C slice 47 (2026-10-30, finish-judgement demo, offline, $0.004527 metered + $0 GCE): the kimi-k3 lead's finish
  review is not a supported stop rule (registered rule falsified: P accepted 6/12, false DONE 0/20, s1@237 0/2); glm-5.3
  low inconclusive (7/12, 1/20). The acceptance half of the instrument is confounded; rejection holds.**
  - 16 recorded states labelled by executed checks: 6 P (sub-goal checks passed), 6 fixture N, 4 gate N (incl. s1@237).
    2 draws each, slice 43's review protocol.
  - Confound (design flaw): fixture goals open "Overall task …; this one is: …" while the review asks about the
    *whole* task. 4/6 of kimi's rejected positives say the sub-goal is done and the overall task is not. The other 2
    (b2-inject) rightly note that the run never read its serial logs. 0/6 rejections are unfounded.
  - c3-a2's N label is wrong: its check required a file OP-TEE lacks, fixed in slice 3. glm's DONE there is correct.
  - Holds: 0 false DONE on the 9 validly labelled refuted states (36 reviews, both models). The replay rejects s1@237
    4/4, while the live lead said DONE: the live false DONE came from its run-long notes and goal list. DONE on one
    state flips between draws (b1b-31, c4-a2, c3-a1).
  - Demo faults: a deadlock in demo code (deferred-settlement callback under a non-reentrant lock; the operator saw it
    as a hang) and a missing `traces/` dir. Both fixed and redrawn; recorded as missing evidence, not results.
  - Core fix (operator request; regression tests fail on the old core):
    - a lost reply (server closed the connection, read timeout) now takes `surplus_post`'s availability backoff
      instead of ending the task `provider_0` after one retry;
    - the whole reply body is bounded by the request limit (a trickling server blocked past it);
    - earlier lost attempts come back in `conflux_lost` and are deferred to the export by `run_task`.
  - Holds did not clear: `fiat_held` went $1.87 → $4.10 with nothing of ours in flight; available + held stayed
    $30.71, so they are reservations, not spend. The other caller's deepseek-v4-pro traffic (129 rows) was in the window.
  - Evidence: `~/evidence/finish-judge-demo-2026-10-30/RESULTS.md` (`started.txt`, `reviews.jsonl`, `reconciled.json`).
- **C slice 46 (2026-10-30, build-wait demo, offline, $0): a harness wait for the executor's own background jobs would
  not free material steps or wall clock; both registered rules falsified, no core change.**
  - Recorded slice-43/40 traces, pre-registered counterfactuals. W2b = a poll waits for the job's end, harness deadline.
    It frees **11, 18, 0** steps (s1, s2b, s3; rule ≥ 12 in 2/3). The verdict is fragile: without the 3 hand-audit
    overrides s1 = 13. W2a (bounded by the poll's own `timeout_s`) frees 0 everywhere.
  - W1 (early-return sleep) frees ≥ 5.8, 1.4, 0.2% of wall (rule ≥ 10% in 2/3); upper bounds are 12.6, 19.1, 1.2%. Most
    slept time was real build time.
  - s3 ran builds in the foreground with large `timeout_s` and polled 3 times. s1's peeks fed 6 mid-build kills.
  - Checked, not a harness defect: a timed-out command's process group is killed with its `&` jobs, and the result
    says so (`timed out … (process group killed)`, since slice 2). s3:9 acted on it; s1:186 ignored it (≈ 1 step).
  - Evidence: `~/evidence/build-wait-demo-2026-10-30/RESULTS.md` (`started.txt`, `scan.py`, `audit.json`).
- **Exploratory re-grade on a task-text reading (2026-10-30, $0, recorded grades only; not the gate).** Goal (a) in
  `task.txt` ("Get QEMU set up with OP-TEE") does not name Linux. Fixtures are grading references (MISSION 773b964), so
  this re-scores the counted runs without G3 (Linux/xtest boot). It also uses **G1′ = OP-TEE sources obtained, any
  method** (inferred from G2): the qemu_v8 manifest is a fixture recipe. **Binding gate unchanged:** MISSION still
  requires the Linux boot (G3), and the registered 0–7 verdicts stand (39 falsified, 40 falsified, 43 inconclusive).
  - T-scale (0–6: G1′ G2 G4 G5 G6 G7), exploratory:
    - slice 39: lead 3, 3 vs pro alone 3, 3, 3;
    - slice 40: 5, 4, 3;
    - slice 43: 6, 5, 5.
  - Task reading of goal (a) (G2 ∧ G6): lead at 240 steps 3/3, at 120 steps 1/3, pro alone 0/3.
  - lead-s1 meets every T-scale milestone (6/6). On the binding gate, its DONE is still a false acceptance (G3 not met).
    Caveats:
    - OP-TEE liveness in the driver boot rests on the CALLS_UID reply. The secure-UART log is not in the trace, and the lab was deleted.
    - The userland client demo failed.
    - GET_OS_REVISION returned 0xffffffff.
  - **Measured cost drivers** (slice 43 traces, `scan.py` → `scan.json`). The 240-step cap binds: s2b and s3 hit it.
    - Fixed `sleep ≥ 60` waits (model `exec` with `sleep N`, N ≥ 60, not running qemu; `scan.json` `fixed_sleep`):
      **s1 37 commands, 8,100 s (16% of steps, 41% of wall clock); s2b 37, 11,160 s (15%, 35%)**; s3 1, 60 s (0%).
    - History growth: prompts reach 329–393k tokens. Latency per step rises 1.5–3× after step 120. It costs wall clock, not steps.
  - Evidence: `~/evidence/cost-drivers-2026-10-30/REGRADE.md` (`scan.py`, `scan.json`).
- **C slice 45 (2026-10-30, lead init-probe demo, live, $0.000754 metered + ≤ $0.38 GCE): giving the kimi-k3 lead its
  own `run_shell` probes on a fresh lab before the init goal list does not add goal (a)'s Linux proof; registered rule
  falsified in both arms.**
  - Arms: T0 = probes only (≤ 15, web via the proxy), T1 = T0 + "read the setup documentation of the software the task names".
    Linux/xtest boot goal with goal (b) kept (hand audit): **T0 0/6, T1 0/6** (lenient 1/6; rule ≥ 3/6). Goal (b) kept 12/12.
  - The lead probes little and generically: median 2 of 15, host census + web, **0/43 probes looked under `/home`** for the
    machine's NetBSD project. T1 read NetBSD man pages, not OP-TEE's. One T0 draw read OP-TEE's `qemu_v8.mk`/manifest and
    still wrote NetBSD as the normal world. Across slices 44–45: 0/32 non-c3 lists derive the gate's Linux boot.
  - **Demo harness fault (MISSION a58a30e):** the demo's own cap guard held cost-less replies at ceiling bounds and refused
    10 draws with 0 calls ($0.32 vs $0.000013 billed). Recorded as missing evidence and redrawn under `core.Budget`
    (export settlement); RESOURCES now says caps always use it. kimi-k3 in a tool loop: 21/44 replies without cost, all unbilled.
  - Evidence: `~/evidence/lead-probe-demo-2026-10-30/RESULTS.md` (`started.txt`: pre-registration + 3 amendments).
- **C slice 44 (2026-10-30, per-goal check demo, offline, $0.001096 metered + $0 GCE): asking the kimi-k3 lead, after
  its init turn, for each goal's executed check does not add goal (a)'s Linux proof; registered rule falsified.**
  - One generic added turn (P1: "for each goal, the executed check that would show it is done; rewrite the goal list";
    P2: + "runnable without the later goals") on the 6 recorded init conversations of slices 40/43, 2 draws each.
  - Linux/xtest boot goal with goal (b) kept: **P1 2/12, P2 2/12** (rule ≥ 6/12), all from c3, whose init reply already
    proposed the stock Linux/xtest boot; **0/20 from the other inputs**. Goal (b) kept 24/24.
  - Goal (a)'s derived check is OP-TEE's secure-world banner (`I/TC: OP-TEE version`) in 19/20 non-c3 lists, with a
    NetBSD boot in 15/20: a stable literal reading of `task.txt`, the same one the old `lab/` run reported as goal (a) done.
  - Second materially identical failure (slice 42 review, slice 44 checks): no third prompt variant on the goal list.
  - Unattributed caller still active on the shared key after slice 43 (57 rows, $0.009536, ledger "not Conflux").
  - Evidence: `~/evidence/acceptance-check-demo-2026-10-30/RESULTS.md` (24/24 export-matched).
- **C slice 43 (2026-10-29/30, step-cap demo on full `task.txt`, $0.378958 metered (export) + ≤ $8.07 GCE): a kimi-k3
  low lead at 240 steps (was 120) scores 6, 4, 4 of G1–G7 (median 4): registered rule inconclusive (≥ 5 / ≤ 3).**
  - Every counted run gained after step 120 (+2, +2, +3, paired): G5 3/3, G6 2/3, and the **first G7**: lead-s1's driver
    attached and its CALLS_UID SMC got OP-TEE's API UID words back. G3 (Linux) still 0/3, G1 1/3: goal (a) stays lost.
  - First live finish reviews: 18/19 finish proposals answered not DONE; 1 DONE (lead-s1) is a **false acceptance under
    the gate** (no Linux; it accepted a failed client demo and a wrong GET_OS_REVISION). Reviews median 178–248 s, 1/154 > 10 min.
  - Offline: the lead named 4/7 of slice 40's masked failures and made "exit 0 ≠ success" a standing rule.
  - **Harness fault, fixed in core (MISSION a58a30e):** lead-s2 ended `run_budget` at step 107 on $1.59 of usage × ceiling
    settlements vs $0.029 billed (14 replies without `buyer_cost_micro`; 25/25 such replies never reach the export, the
    balance moves by exactly the export total). Core now leaves such costs `pending` and settles them from export rows
    (`Budget.resolve`; `"unbilled"` at 0 after 10 min); regression test replays lead-s2's 6 pro replies. lead-s2 not counted,
    lead-s2b replaced it; lead-s3 ran on a frozen checkout of the registered core.
  - **Floor audit:** `scripts/provider_probe.py` sent paid requests without `X-Min-Discount` (fixed, tested); core always
    sends it. The 60%-discount kimi-k3.1-pro rows (10-29) and 1,076 deepseek-v4-pro rows (10-30) come from an unidentified
    caller on the shared key, not from this controller (ledger row "not Conflux"). Missing input (founder): who else holds
    `surplus.key`; a dedicated key or a key-level floor in the Surplus dashboard closes it.
  - Evidence: `~/evidence/step-cap-demo-2026-10-29/RESULTS.md` (`grade-lead-*.json`, `started.txt`).
- **C slice 42 (2026-10-29, goal-list review demo, offline, $0.001207 metered + $0 GCE): a different-family review of
  the kimi-k3 lead's initial goal list does not restore goal (a)'s Linux proof; registered rule falsified.**
  - Inputs: slice 40's 3 recorded init replies (goal (a) read as "QEMU + OP-TEE with NetBSD as normal world"), generic
    request "does it cover everything the task asks for, read the way the user most likely means it? corrected list".
  - Linux/xtest boot goal with goal (b) kept: glm-5.3 low **2/15** (rule ≥ 8), kimi-k3 low self-review 5/15, no
    review 0/9; reference build env (qemu_v8/repo): 0, 3, 0. Every hit came from c3's reply, whose free-text next
    steps already named the stock qemu_v8 boot; from c1/c2 0/10 per model. Review promotes, never derives. Build nothing.
  - Evidence: `~/evidence/goal-review-demo-2026-10-29/RESULTS.md` (36/36 export-matched).
- **C slice 41 (2026-10-29, D1 classification of slice 40's 25 hits, $0): 12 are real masking in the executor's own
  commands, 6 were audit false positives (now fixed), 7 are residual false positives, and one harness fault was fixed.**
  - Harness fault H1: with a trailing `cmd &`, a background child's late stderr pushed the `__CONFLUX_PIPESTATUS=` marker
    off the end, so `pipestatus`/`failed_cmds` were lost and the marker was shown to the model (3/1,553 execs).
    `_split_pipestatus` now takes the last marker line anywhere. Regression tests on recorded stderr, local, and a
    fake-remote lab fail on the old parser.
  - D1 false positives fixed: `sleep N && tail log` is a read (5), cross-prefixed `strings` (1). Residual (recorded
    only): file text from mixed read+write commands (4), `touch … || echo` writability probes (3), and the model's own
    echo text (1 in slice 39). An echo-literal exemption was dropped in review: it hid a tool error whose text equals
    an unexecuted `|| echo` fallback (regression test). After the fix slice 40 has 19 hits, slice 39 is unchanged (11),
    and no hit was added.
  - Real masking (model, for the lead/critic): `curl -s` without `-f`, `… &`, `| tee log; echo EXIT $?` inside
    `sh -c`, `|| true`.
  - Evidence: `~/evidence/d1-slice40-classify-2026-10-29/RESULTS.md`.
- **C slice 40 (2026-10-29, lead-factor demo on full `task.txt`, $0.198894 metered (export) + ≤ $2.71 GCE): a
  non-blocking kimi-k3 (`reasoning_effort=low`) lead, in place of glm-5.3 low, still does not pass the registered rule
  (lead 4, 3, 3 vs slice 39's controls 3, 2, 3; median 3 ≤ 3: falsified). But it alone reached G5 (kernel rebuilt with
  the driver, 2/3 vs 0/5 slice-39 runs) and G6 (NetBSD on OP-TEE firmware, 1/3 vs 0/5); G7 (driver attaches) 0/3.**
  - Factor choice by the registered rule: glm-5.3 now refuses `medium` (HTTP 400, accepts only low/high/max), so the
    lead model changed. Offline finish replay of slice 39's 3 false control finishes: **0/6 false DONE** for glm-5.3 low
    and 0/6 for kimi-k3 low. Whether a lead accepts a genuine DONE is unmeasured (no complete run exists).
  - Lead runs lose goal (a): G1 1/3, no Linux boot (G3 0/3). Executors follow the lead's numbered steps and work in the
    machine's NetBSD tree (2/3). No executor proposed finish (all ran to the 120-step cap). Review latency grows with the
    trace: median 275/290/424 s, max 406/655/779 s, so 2/3 runs had reviews past the 10-min cadence bound.
  - Unclassified: D1 hits 15/10/0. In lead-c1 most are masking in the model's own commands (`&`, `|| …`, `curl -s`
    printing a 404 with exit 0), plus a source-text false positive.
  - Evidence: `~/evidence/lead-factor-demo-2026-10-29/RESULTS.md` (`started.txt`, `grade-lead-c*.json`).
- **C slice 39 (2026-10-28/29, other-model-leads demo on full `task.txt`, $0.377811 metered (export) + ≤ $5.23 GCE): a
  non-blocking GLM-5.3 lead does not move milestones vs pro alone; registered rule falsified (lead 2, 2 vs control 3, 2,
  3 of G1–G7; lead-b3 futility-stopped). False DONE: 0/2 lead runs vs 3/3 controls that called finish with false
  success claims, but neither lead run ever proposed finish (both ran to the 120-step cap, 0 retries), so whether the
  lead rejects a premature finish is untested.**
  - Design as measured (founder decisions cda6dac, a594bbc, 68ad22c): conversation layout (data first, one goal per
    turn), review every ≥ 300 s of wall clock, never blocking pro; glm-5.3 at `reasoning_effort=low` (reviews 100–285 s;
    default effort took 17–20 min per review, pf rubric equal). Lead runs went further in kind (driver wired into the
    machine's NetBSD tree; OP-TEE booted to U-Boot) but not to the next milestone; lead goal lists add scope.
  - Harness faults fixed in core (regression tests fail on the old core): model-max output and input-only admission
    (90b27cd), `X-Min-Discount: 90` (5ee7a8b), no-seller replies waited out up to 4 h and never ending a run, unbilled
    errors at $0, admission on settled spend only. Pair 1 (step-counter blocking lead) was cut by provider outages; the
    blocking design is retired. All demo runs before the fixes are archived, not counted.
  - Evidence: `~/evidence/other-model-leads-demo-2026-10-28/RESULTS.md` (`started.txt` = registration history).
- **C slice 38 (2026-10-28, probe-and-replan demo, $0.071824 metered (balance delta, export-matched) + $0.07 GCE):
  stopped by founder decision (MISSION a7322df) before any re-plan reply; outcome is missing evidence.** Stage 1 ran
  slice 37's 21 test commands verbatim on c3 as harness probes (c3 restored, TERMINATED). Raw observations: U-Boot as
  BL33 boots in 4/4, `-d int` shows NetBSD entered at EL1 and silent, both TF-A rebuilds fail on a missing
  cross-compiler in PATH, no gdb on the lab. 2 stage-2 K3.1-pro requests were billed with no reply recorded (1 killed
  externally, 1 stopped). Not resumed. Evidence: `~/evidence/probe-replan-demo-2026-10-28/RESULTS.md`, `STOPPED.txt`.
- **C slice 37 (2026-10-28, hypothesis-plan demo, $0.467867 metered (balance delta; export $0.359383) + $0 GCE): a
  K3.1-pro one-shot "competing hypotheses, each with its cheapest test" plan on pro's b2 stall never tests the BL33
  kernel setting; hypothesis falsified, stage 2 not run.**
  - Setup: slice 35's observable trace to step 20, flattened, plus a generic request (no task-specific words). n=5.
  - P1 (a test that builds TF-A with that setting = 1): **0/5** (4 valid, 1 truncated twice). Slice 34 (legacy
    decider prompt, clipped slice-27 trace, so not a like-for-like baseline): 2/5. The rule (≥ 3/5) failed, and with 0 P1 plans the pro hand-back stage (lab) did not run.
  - Post-hoc: **12/12 hypotheses come with an executable QEMU-boot test (0 pure reads)**. 4/4 plans include a U-Boot-as-BL33
    control boot. 3/4 name the real mechanism (x0 not pointing at the DTB at kernel entry) and test it with a QEMU exec
    trace or a gdb break at entry. 2/4 reconstruct a full TF-A make line from the trace. None maps x0 to the build setting.
  - Demo accounting fault, fixed in-run: replies without cost were settled at list-ceiling bounds and blocked samples;
    re-settled from the balance delta (amendments in `started.txt`).
  - Evidence: `~/evidence/hypothesis-plan-demo-2026-10-28/RESULTS.md`.
- **C slice 36 (2026-10-28, model-switch takeover demo, $0.473384 metered (balance delta; export $0.131383) + $0.40
  GCE): a different-family model taking over pro's stalled b2 run with tools does not fix it; hypothesis falsified.**
  - Setup: K3.1-pro and GLM-5.3 each got slice 35's observable trace to step 20, no developer prose, and the
    remaining 10 steps on c3, through `run_task` (demo-only initial-messages seam; offline seam check 4/4).
  - Results: K3.1-pro **0/2** accepted (rule ≥ 2/3; pro baseline 0/2; run 3 skipped). GLM-5.3 0/2 (exploratory).
    0 builds in all 4 runs; 0/40 replies named the BL33 kernel setting.
  - What happened: both models reproduced the reading stall (TF-A headers, SPD, toolchain). K3.1-pro run 2 decided
    "rebuild" at step 30 without the setting, as pro did. In the tool loop both reason briefly (≤ 280 tokens) and
    are valid, fast and cheap: K3.1 ≈ $0.004/step cached, GLM ≈ $0.0001/step; 0/40 truncations. So switching
    changes who reads, not what is read. Build nothing.
  - Accounting fault: 7 replies without `buyer_cost_micro` are absent from the usage export and from `recent_usage`;
    the balance delta is recorded.
  - **Surplus credit is $8.23, below the weekly cap**: it binds paid work.
  - Evidence: `~/evidence/takeover-demo-2026-10-28/RESULTS.md`.
- **C slice 35 (2026-10-28, harness fix + live re-measure, $0.001271 metered + $0.17 GCE): reasoning passback fixed;
  pro's b2 stall survives it (failed `step_cap`, n=1); hypothesis falsified.** Harness fault (MISSION c36f507):
  `run_task` now passes each assistant turn's `reasoning_content` back; regression test fails on the old loop. Live
  pro b2 on c3 (slice 27's tasks, no injection), with reasoning delivered on every turn (request-side log): 70 commands,
  0 builds, 0 writes. At step 24 pro read the BL33 kernel setting at its default and **dismissed it in reasoning**. At
  steps 26–27 it decided to rebuild (slice 27 never did), with a flag list that omits that setting, then hunted the
  toolchain until the cap. The b2 stall is a wrong belief, not lost context: **model fault, unconfounded**. With
  slice 22 (b1b 0/5) and slice 34 (b2 0/6), passback has not moved pro off a stall in any measurement. D1 0 hits;
  30/30 export-matched. c3 unchanged.
  - Still confounded: b1 (c10/c11/slice 18, flash) and b3 (slice 31). Re-measure them live when a lab run is due anyway.
  - Evidence: `~/evidence/pro-b2-passback-c3-2026-10-28/RESULTS.md`.
- **C slice 34 (2026-10-28, work item D demo, $0.590990 metered + $0 GCE): a different-family decider does not
  reliably turn pro's b2 stall into the experiment; hypothesis falsified at n=5.** Legacy `DECIDER_PROMPT` verbatim
  (`conflux-baseline-20261026`), slice 27's trace to step 20 (no reasoning), only the model varied; rule ≥ 3/5 and
  ≥ pro + 2. Hypothesis-testing decision (flagged TF-A rebuild + boot): pro 0/5, **kimi-k3.1-pro 2/5** (both grounded
  in the executor's step-11 output), kimi-k3 and glm-5.3 **0/5 valid** (reason to the 24000-token cap, no JSON,
  20/20). K3.1-pro is ≈ $0.055/call (≈ 370× pro). Post-hoc: pro given K3.1-pro's 2 decisions builds 0/12 in the next
  step, with and without reasoning passback. It adopts the decision and hunts for the original make line, which neither
  model has (= slice 28/29 recipe-free). Build nothing.
  - Instrument fault caught in-run: the first 29 calls used `core.MAX_TOKENS` 8192 (legacy decider: 24000), 26/29
    truncated; archived, counted in spend, re-run at 24000.
  - Evidence: `~/evidence/decider-critic-demo-2026-10-28/RESULTS.md` (71/71 export-matched).
- **C slice 33 (2026-10-28, single-model baseline demo, $0.001184 metered + $0.10 GCE): a pro planner given only `run12/task.txt` derives
  none of the machine-specific spec; hypothesis unverified (1/3 probe samples, 2 lost to GCE stockouts).** Rubric of 17
  fixture items, pre-registered, hand-audited (regex in brackets): no probes (N) 7, 5, 5 (9, 7, 8); with ≤ 20 runtime
  probes on a fresh clean-snapshot lab (P0) 4 (7). 0/4 specs located the NetBSD project: no NetBSD tree, obj dir,
  tooldir or ownership. P0's 20 probes were a host census, and none looked under `/home` or searched for NetBSD. Its
  plan builds a standalone module, with no kernel, firmware or NetBSD boot. Known without probes: `repo init …
  qemu_v8.xml`, `build.sh -m evbarm64`, an fdt attach stanza. Never derived: NetBSD as TF-A BL33, the BL33 kernel
  flag, `linaro,optee-tz`, a no-OP-TEE control. N1 wrote 3 always-pass checks (`|| echo`). Build nothing.
  - Demo-harness faults fixed in the demo: truncated/invalid specs are now resubmitted. A stockout leaves
    `devbox-lab up`'s boot disk behind, so every retry fails `already exists`; the disk is now deleted before a
    retry. `core.run_lab` does not retry, so it is unaffected.
  - Evidence: `~/evidence/spec-derivation-demo-2026-10-28/RESULTS.md` (`audit.md`; 19/19 export rows).
- **C slice 32 (2026-10-28, single-model baseline demo (pro diagnosing pro; MISSION 6eafcd8), $0.002378 metered + $0.45 GCE): a fresh pro diagnostic sub-run with runtime probes
  does not produce the b2 correction: 0/3 grounded passes, hypothesis falsified.** This is a
  reachable-with-developer-written-spec instrument: the input is the fixture's b2 text plus slice 27's trace to step 20.
  c3 was reset to the slice-27 state (no-flag TF-A rebuilt, b2 check 2 fails, old job dirs archived and removed).
  Each of the 3 sequential, isolated diagnoses had ≤ 10 probes. All 30 probes were reads (0 builds, 0 boots). None
  called `correct`; 19 more probes were denied after the cap. All 3 named the right flag hypothesis in their
  reasoning and never tested it: the executor's "names it, reads on" stall again. Do not build it.
  - Demo harness fault caught before any paid call: TF-A `realclean` failed silently and relinked slice 30's flagged
    objects (b2 passed). Fixed by `rm -rf build/qemu`.
  - Evidence: `~/evidence/self-diagnosis-demo-2026-10-28/RESULTS.md`.
- **C slice 31 (2026-10-28, run, $0.017228 metered + $0.62 GCE): pro's first b3 run fails at the step cap (40 steps,
  100 commands, 0 writes, 0 builds); hypothesis falsified.** No injection, but its starting state includes slice
  30's developer-helped b2 firmware. Pre-check: b1a, b1b and b2 pass, b3 fails. At step 19 pro correctly named the
  problem: the driver matches only `linaro,optee-tz`, which is absent without OP-TEE. Steps 20–40 read TF-A, OP-TEE
  DT and NetBSD fdt code without acting. This is the 4th reading stall (flash b1, pro b1, pro b2, pro b3). Model fault;
  D1 0 hits; 40/40 export-matched.
  - Before any further b3 run: check 2 fails on pro's driver because it `#define`s the OP-TEE UID words for a
    comparison, which the task text does not forbid. Fix the task text or the check, then re-validate harness-only.
    Pro's "no attach under OP-TEE" premise came from a 4 KB-clipped log, so it is unverified (missing evidence).
  - Evidence: `~/evidence/pro-b3-c3-2026-10-28/RESULTS.md`.
- **C slice 30 (2026-10-28, hook + run, $0.007037 metered + $0.21 GCE): with slice 29's correction M injected once at
  step 20, pro's live b2 is accepted at the step cap (30/30, 0 steps to spare).** The correction was developer-authored,
  so b2 is not done (founder decision 2026-10-28). Harness: `Task.inject_step`/`inject`
  appends one `user` message before that step's model call and traces it (`inject` row); 2 regression tests fail on old
  code. The evidence sentence was restated as the slice-27 harness diagnosis, the rest verbatim. Pre-check b1a/b1b pass, b2 fail.
  - Steps 1–19: 50 reads chasing the original flags (= slices 27–29). After the correction: 5 steps of input checks,
    step 25 ran the recipe verbatim, which was a **no-op in-tree** (`Nothing to be done`). The recipe was verified
    out-of-tree, and TF-A does not track flag/BL33 changes. Pro ran `realclean` itself (27), rebuilt (28), copied the
    bios (29), boot-tested (30); the cap checks passed.
  - D1 0 hits; 30/30 export-matched. c3 now holds the flagged b2 firmware; its TF-A build dir was rebuilt for NetBSD.
  - Evidence: `~/evidence/pro-b2-inject-c3-2026-10-28/RESULTS.md`.
- **C slice 29 (2026-10-28, replay + continuation demo, $0.000971 metered + $0.03 GCE): a b2 correction that carries
  slice 27's verified make line gets pro to build; one without it does not, even within 2 steps.** Same prefix as slice
  28, pro, all 26 calls export-matched. Rule: flagged TF-A build (`make` + `ARM_LINUX_KERNEL_AS_BL33=1`).
  - M (correction + recipe, 1 step): **3/5**, rule ≥ 4/5 not passed by one; the other 2 `ls` the recipe's inputs.
    Post-hoc, those 2 continued on c3 build in 5/6 step-2 draws (5/5 samples by step 2).
  - C2 (slice 28's recipe-free correction, its draws' reads executed on c3, 3 draws each): **0/5 samples, 0/15 draws**;
    all 15 keep reconstructing the toolchain and the original flags.
  - Evidence: `~/evidence/b2-recipe-continuation-demo-2026-10-28/RESULTS.md`.
- **C slice 28 (2026-10-28, replay demo, $0.000423 metered + $0 GCE): pro adopts a grounded b2 correction but does
  not build in the next step; the rule is not passed at 1 step (2-step outcome unmeasured).** Slice 27 prefix at
  K=20 (symptom confirmed), pro, n=5 per arm; replay exact (35,233 prompt tokens = recorded). Flagged TF-A build in
  the next reply: control 0/5, correction 0/5. All 5 correction replies plan the flagged rebuild in their reasoning,
  then look for the cross-compiler and the original make flags. Slice 26's make line is not in this session. Control
  names the flag in its reasoning in 4/5 draws, yet 4/5 keep reading TF-A hand-off code (= slice 27's
  over-diagnosis). No live b2. Evidence: `~/evidence/b2-correction-demo-2026-10-28/RESULTS.md`.
- **C slice 27 (2026-10-28, diagnosis + run, $0.001710 metered + $0.32 GCE): the BL33 cause is verified; pro's b2
  continuation fails at the step cap again (2nd identical b2 failure).** Pre-check b1a pass, b1b pass, b2 fail.
  - Harness-only: two out-of-tree TF-A builds with pro's slice-26 flags, booted 150 s each. Without
    `ARM_LINUX_KERNEL_AS_BL33=1`, serial0 ends after BL31 (= slice 26). With it, NetBSD prints the b1b kernel's banner
    and autoconfigures. So pro's recipe plus that one flag meets b2's boot markers.
  - Live b2, pro, unchanged task: `failed step_cap` (30), 77 commands, **0 builds, 0 writes**. It re-confirmed the
    symptom with 3 boots, then read TF-A hand-off code; at step 30 it asked whether the kernel wants a DTB in x0.
    Model fault (over-diagnosis); 30/30 export-matched; D1 0 hits. Tree unchanged.
  - Evidence: `~/evidence/pro-b2-c3-2026-10-28/RESULTS.md`.
- **C slice 26 (2026-10-28, run + D1 fix, $0.001540 metered + $0.42 GCE): pro's b1b continuation is accepted; b2, its
  first live run, fails at the step cap.** Pre-check b1a pass, b1b fail, b2 fail.
  - b1b `accepted checks_passed` at step 31: it fixed the include via `sudo sed`, and a 600 s build timed out (its
    own choice); the 900 s rerun built in 609 s.
  - b2 (same session) `failed step_cap` (30): 19 steps before the first TF-A build (`SPD=opteed`, BL32 = OP-TEE
    v2 images, BL33 = `netbsd.img`). OP-TEE reaches `switching to normal world` and NetBSD prints nothing.
  - Likely, untested: no `ARM_LINUX_KERNEL_AS_BL33=1`, which legacy ctl-run-3 and slice 9's control build set. Model fault.
  - 13/31 b1b replies had no `buyer_cost_micro` and are absent from the export (unbilled so far).
  - **D1 false positive fixed:** build.sh's banner `MAKECONF file: … (File not found)` matched on a successful build.
    `core.BENIGN_TEXT` exempts it; the fixture case fails on old code; over 34 traces only that hit changes (11 → 10).
  - Evidence: `~/evidence/pro-b1b-b2-c3-2026-10-28/RESULTS.md`.
- **C slice 25 (2026-10-28, run + D1 fix, $0.001667 metered + $0.18 GCE): with head+tail output pro acts on ownership
  one step after the denial; b1b still `failed step_cap` (model fault in its own rewrite).** Pre-check b1a pass, b1b fail.
  Step 13's build.sh showed 11 `Permission denied` in the 1 KB head (0 in the last 3 KB); step 14 pro ran `sudo chown`,
  by step 24 it had `chown -R dev:dev` the whole obj tree, built as dev, hit the 2 known `-Werror` errors (step 26),
  fixed them via `sudo sed`/`sudo dd` rewrite, and the rebuild (step 37) failed on its new `#include <arm/smccc.h>`
  (header is `arm/arm/smccc.h`); step cap at 40. 40/40 export-matched. **D1 false-positive class fixed:** all 9 D1 hits
  since `failed_cmds` exists (slice 7) had `failed_cmds ≥ 1` in the header the model saw; `core.audit` now skips them
  (10 older hits incl. both demo true positives unchanged; 2 fixture cases fail on old code). **c3 state changed:** obj
  tree now owned by `dev`. Evidence: `~/evidence/pro-b1b-headtail-2026-10-28/RESULTS.md`.
- **C slice 24 (2026-10-28, harness-only + fix, $0 metered + $0.01 GCE): the 4 KB tail cut build.sh's `Permission
  denied` on slice 21 step 12; harness fault, fixed.** Read slice 21's 7 build.sh job files on c3 (no rerun): step 12's
  output (stderr only, 4966 B) starts with 3 `Permission denied` lines on the darrenhidalgo-owned tooldir wrapper
  `bin/nbmake-evbarm`; `tail -c 4096` dropped them. In the other 6 pro's own `tail -N`/`grep | head` had already
  dropped the denial (model behaviour, `MODELS.md`). Fix: output over 4096 B returns its first 1024 B + an
  omission marker + its last 3072 B (`core._clip`, local and lab); regression test replays the recorded output (old
  code 4/4 fail). Evidence: `~/evidence/tail-cut-check-2026-10-28/RESULTS.md`.
- **C slice 23 (2026-10-28, continuation demo + offline trigger, $0.000203 metered + $0 GCE): pro acts on the
  adopted correction; a plain ownership trigger is mostly redundant; the 4 KB output tail may hide the cause.**
  Slice 22's 3 correction samples that read `ls -d tooldir.*/` first, continued one step with the recorded listing
  (3 draws each): 8/9 draws run the task's build.sh via `sudo -n -u darrenhidalgo` (3/3 samples) → **5/5 overall; the
  rule fired.** Offline trigger (`Permission denied`, command under darrenhidalgo's home, no sudo) on 6 b1/b1b traces:
  5 firings, all genuine, but 3 were self-fixed by pro within 2 steps (s18, s20). The pre-registered build rule fails
  (redundancy); a post-hoc "no sudo 2 steps after a denial" variant fires only on s21 (steps 23, 39), but it was fitted on
  these traces. Nothing built. **Harness-fault candidate:** s21's 7 build.sh-as-dev runs each returned a full
  `core.TAIL` (4096 B) of one echoed nbmake line + `*** [cleandirkernlib] Error code 1`, with no `Permission denied`; the
  full output is missing evidence (only on c3). Evidence: `~/evidence/correction-continuation-demo-2026-10-28/RESULTS.md`.
- **C slice 22 (2026-10-28, replay demo, $0.000645 metered + $0 GCE): neither reasoning carry-back nor a grounded
  correction passes its rule on pro's b1b ownership stall.** Planning found that `run_task` replays assistant turns
  without `reasoning_content`. Pro's `content` is empty on 39/40 replies (flash: 38/40), so the executor never sees
  its own reasoning, although DeepSeek's thinking-mode guide says to pass it back. Slice 21 prefix at step 23, pro,
  n=5 per arm, all complete and valid (B's delivery was verified by +3,083 prompt tokens). Ownership action
  (`sudo`/`chown`): control 0/5; reasoning replayed 0/5 (the same 3/5 `NETBSDSRCDIR` detour); correction
  (requirement + `Permission denied` evidence + `sudo -n -u darrenhidalgo`) 2/5. All 5 correction replies adopt it
  in their reasoning; the other 3 list the tooldir first. Neither rule fired; nothing built. H1 is falsified at this
  prefix; it is untested on flash's b1 stall. Evidence: `~/evidence/reasoning-carry-demo-2026-10-28/RESULTS.md`.
- **C slice 21 (2026-10-28, run + D1 fix, $0.001201 metered + $0.16 GCE): pro reruns b1b, `failed step_cap`;
  model fault.** Setup restored the 2-error driver; pre-check b1a pass, b1b fail. Under `usage_bound` the 7 no-cost
  replies were settled at $0.274 and the run reached the cap (fix holds). Pro ran `build.sh` 9× as `dev`, never with
  sudo: the darrenhidalgo-owned compile dir's `cleandir` failed; it named ownership at steps 22–23, then chased a
  `NETBSDSRCDIR` error its own hand-run `nbmake` caused. Never reached `optee.c`; 0 edits. D1 false positive (`nbmake
  -n` dry run) fixed: `READ_ONLY` covers `…make … -n`, fixture case. Lab stop now in a `finally` (3 failure paths
  tested). Evidence: `~/evidence/pro-b1b-rerun-2026-10-28/RESULTS.md`.
- **C slice 20 (2026-10-28, run + harness fixes, $0.000670 metered + $0.11 GCE): pro's b1b repair cut off by a
  harness fault.** Harness: per-model admission ceilings `core.CEILINGS` (flash; pro 2e-6/7.6e-6; unknown model
  refused before any call); D1 now treats `git -c/-C … diff|log|…` as a read (slice-19 step-2 false positive, fixture
  case). Live b1b, pro, c3 (pre-check b1a pass, b1b fail): `unverified task_budget` at step 28. Pro built at step 15
  (flash: 25), read both errors at 16, and edited from step 17 (6 fragile scripted edits; step 27: "write the whole
  file cleanly"). **Harness fault:** 7/27 pro replies had no `buyer_cost_micro` (not in the export either). Each was
  settled at its request bound ($0.08–0.24), $0.94 charged for $0.0007 billed. Fix: settle at usage × ceilings
  (`usage_bound`); a regression test replays the 27 recorded calls (old code: `task_budget` at step 28). The hypothesis
  is untested, not falsified. Evidence: `~/evidence/pro-b1b-run-2026-10-28/RESULTS.md`.
- **C slice 19 (2026-10-28, demo + fixture, $0.000040 metered + $0.19 GCE): b1 split; flash builds pro's driver but
  never fixes it.** Fixture: `b1-driver-build` → `b1a-driver-source` + `b1b-kernel-build` (b1a's check + the build
  check). b1a's check needs a `files*` stanza (`device optee`, `attach optee at fdt`, `file <x>.c … optee`) whose
  `.c` is new and has `CFATTACH_DECL` (critic: a GENERIC64 line alone passed). Harness-only on c3: b1a pass, b1b
  fail; config-only and stanza-only clones fail b1a. Live b1b (pre-review check 1; the new one also passes on this
  tree), flash, c3 as pro left it: `failed step_cap`. Flash ran `build.sh -T …` at step 25 (79 s): 2 `-Werror`
  errors in pro's `optee.c` (unused `faa`, unused `optee_smc_call`). It predicted both at step 24 and restated them
  at steps 36/40, yet made **no edit** (27 later reads drift to b3: optee_msg, PTAs, shm, DMA). Model fault, no
  harness fault. D1 false positive at step 2 (`git diff; …; cat optee.c` flagged on the source text "failed").
  Flash's write stall now spans c10, c11, slices 12–16 and 19: it is not the b1 writer or repairer.
  Evidence: `~/evidence/b1b-flash-run-2026-10-27/RESULTS.md`.
- **C slice 18 (2026-10-27, demo, $0.001838 metered + $0.18 GCE): pro in flash's seat writes b1 but runs out of
  steps before the build.** One live b1 run on c3, `deepseek-v4-pro`, else as c11 (wrapper sets pro admission
  ceilings and `max_usd` 1.00; nothing built). `failed step_cap`: check 1 **passed** (new `sys/dev/fdt/optee.c`,
  `files.fdt` stanza, GENERIC64 `optee* at fdt?`), check 2 failed — no `build.sh` ever ran, so whether the driver
  compiles is unverified. 61 on-scope reads before the first write (step 26); 6 steps repairing its own edits.
  Flash wrote nothing in c10/c11. Billed $0.000046/call (≈ 25× flash), max latency 71 s. Model behaviour, no harness
  fault (D1 hit = a real Permission denied the model then fixed). With flash ceilings the fixture's `max_usd` 0.15
  would refuse pro mid-run (bound peaked at $0.33/call). Evidence: `~/evidence/pro-b1-run-2026-10-27/RESULTS.md`.
- **C slice 17 (2026-10-27, harness fix, $0): a slow provider reply no longer ends a task.** `CHAT_TIMEOUT` 180 → 900 s
  (flash replies measured up to 713 s); `run_task` retries a status-0 call (transport error/timeout) once, each attempt
  admitted, settled and traced with `attempt`; no retry past the lab deadline, HTTP errors not retried. Regression test
  reproduced `unverified provider_0` before the fix. Evidence: `~/evidence/chat-timeout-2026-10-27/RESULTS.md`.
- **C slice 16 (2026-10-27, demo, $0.001272 metered + $0 GCE): a stronger executor in flash's seat also reads.
  Hypothesis falsified; nothing built.**
  - Replayed c11/b1 (flash's history) at k=10/20/30 and sampled one next reply from `deepseek-v4-pro` (n=5 per k),
    `glm-5.3` and `kimi-k3` (n=3 at k=20/30), all via Surplus. Plausible admissible writes: **pro 0/15, glm 0/6,
    kimi 0/6** (flash 0/20). All 50 commands are reads; no denial, truncation or `finish`.
  - Scope separates them: pro's reads stay on b1 (9/10 at k=20/30; it names `sys/dev/fdt/optee_fdt.c`, `files.fdt`,
    GENERIC64) yet opens "a few more references first"; glm/kimi follow flash's b3 drift at k=30 (0/6 b1).
  - The one-step measure is saturated (0/47 over four models): it cannot tell "writes at k+3" from "never writes".
    Whether pro finishes b1 needs a multi-step live run. Pro billed ≈ $0.000057/call; max latency 81 s.
  - Evidence: `~/evidence/stronger-executor-demo-2026-10-27/RESULTS.md` (`demo.py`, `samples.jsonl`, `labels.json`,
    `reconciled.json`; 30/30 export-matched).
- **C slice 15 (demo, $0.000074): failing-check feedback before `finish` does not make flash write b1** (control,
  last-step and every-step feedback each 0/10; 6/10 reasonings dismiss the checks as "failed as expected since no
  work yet"). Prompt-level nudges to flash on b1 are exhausted. Evidence: `~/evidence/feedback-demo-2026-10-27/`.
- **C slice 14 (demo, $0.008170): more output headroom does not make flash's truncated driver writes executable.**
  Complete admissible edits at max_tokens 8192 2/9 vs 16384 0/9; reasoning grows to fill the limit; 2 heredocs hit
  `MAX_COMMAND`. `MAX_TOKENS` stays 8192. **Live-run risk:** 10/18 calls took > 180 s (max 713 s); in `run_task` one
  chat timeout ends the task `unverified provider_0`. 2 calls hit a slow list-priced seller ($0.0023–0.0057).
  Evidence: `~/evidence/headroom-demo-2026-10-27/RESULTS.md`.
- **C slice 13 (demo, $0.001352): scope framing, a read cap and a pro plan each fail** (0 plausible writes, n=10
  each). Denied reads, flash writes token files; `echo … > f` matches `READ_ONLY`. The 3 real driver writes hit 8192
  completion tokens. Diagnosis handed to `codex exec`: flash stalls between understanding and implementing.
  Evidence: `~/evidence/b1-arms-demo-2026-10-27/RESULTS.md` (`codex-diagnosis.md`).
- **C slice 12 (demo, $0.000084): telling flash its step budget does not make it write** (0/30 incl. a policy
  sentence; reasoning cites "only 10 steps left" and reads on). Evidence: `~/evidence/overexplore-demo-2026-10-27/`.
- **C slice 11 (run c11, $0.000073 + $0.19 GCE): b1 `failed` at the step cap; model fault, 2nd identical failure.**
  0 truncations with `MAX_TOKENS` 8192; all 76 commands were reads (b2/b3 scope); no write, no `finish`.
  Evidence: `~/evidence/core-runs/2026-10-27-c11/RESULTS.md`. Lab c3 stopped, disk kept, NetBSD tree untouched.
- **C slice 10 (run c10, $0.000055 + $0.23 GCE): b1 failed; harness fault fixed** — `MAX_TOKENS` 2048 cut off tool
  calls (now 8192; truncation is named to the model as `truncated_at_max_tokens`, and a truncated reply with no call
  is not a finish). GCE stockouts happen: retry the lab start. Evidence: `~/evidence/core-runs/2026-10-27-c10/`.
- **C slice 9 (harness-only, $0.58 GCE): goal (b) cut into b1–b3** (`tests/fixtures/core_loop/optee_goal_b.json`:
  b1 driver build, b2 TF-A+OP-TEE firmware booting NetBSD, b3 driver proof incl. a no-SPD control boot, packaged
  QEMU only). Every check validated on c3 against untouched, reference and faked trees. Residual: the model has root.
  Labs need `build.sh -T <tooldir>`. Evidence: `~/evidence/core-runs/2026-10-27-c9/RESULTS.md`.
- **C slice 8 (run c8, $0.000034 + $0.25 GCE): flash accepted on a3 (at the step cap; it does not stop) and a4
  (24 steps).** D1 false positive on `strings` fixed. Evidence: `~/evidence/core-runs/2026-10-27-c8/`.
- **C slices 6–7 ($0.07 GCE):** every command runs under `set -o pipefail`; results carry `pipestatus` and
  `failed_cmds` (ERR trap), shown to the model. a1–a4 re-validated harness-only. Not covered: `|| true`, tools that
  exit 0 with warnings. Evidence: `~/evidence/core-runs/2026-10-27-c{6,7}/`.
- **F step 1 ($0): D1 self-audit runs at the end of every task** (`core.audit`, `python -m conflux.core audit`).
  Evidence: `~/evidence/self-audit-d1-2026-10-27/`; fixture `tests/fixtures/core_loop/audit_d1_cases.json`.
- **C slices 1–5 (2026-10-27):** `conflux/core.py` is one explicit loop (flash proposes `run_shell`/`finish`;
  deterministic admission, policy, execution, acceptance; `accepted`/`failed`/`unverified`; export reconciliation).
  `lab_shell` drives `devbox-lab` VMs; egress is tunnelled through a controller proxy. Default executor
  `deepseek-v4.1-flash` (billed < 1 micro-USD/call). Goal (a) cut into a1–a4 with executed checks; wrong checks
  cost whole sub-goals twice, so **every check passes harness-only on a real tree before a paid run**.
  Evidence: `~/evidence/core-runs/2026-10-27-c{1,1b,2,3,4,5}/`.
- **A (2026-10-27, $0): run 12's NetBSD stall came from two deterministic transformations**, both fixed: T1
  `decider._shell_effects()` turned non-path operands into phantom paths (`tests/test_run12_scope_mapping.py`); T2
  no-verdict soundness checks (HTTP 402) were stored as `postcheck_failed`, now `unverified`
  (`tests/test_run12_t2_unverified.py`). Evidence: `~/evidence/optee-ctl-runs/run12/`,
  `tests/fixtures/run12_netbsd/manifest.json`, `~/evidence/analysis/run12-netbsd/`.
- **Known contract violation (PR #1):** `conflux/verifier.py` `_parse_point` still accepts digit scores; pinned by
  strict xfail in `tests/test_letter_scale_contract.py`.
- **Next action:**
  0. ~~Snapshot contamination~~: fixed for gate runs in slice 65. Pass
     `--lab-clean tests/fixtures/core_loop/optee_lab_residue.txt`, and check the summary for `lab.clean.exit == 0`.
     A clean snapshot replacing the fixture needs the founder (no `compute.snapshots.create`).
  1. ~~Scratch side channel~~: fixed in slice 64. First live exercise in slice 69: 0 executor commands touch
     `conflux-scratch`.
  2. **On hold (open founder question above): no per-criterion verdict in core until MISSION records it.** **False DONE against the gate: hold derived criteria fixed (slice 68).** The open finish review drops Gl's Linux
     criterion 16/16 at s61, but keeps goal (a) correctly at c8 12/12. Per criterion as written, it holds it (slice 67).
     - Next demo: a separate acceptance check beside the open review, which keeps leading (MISSION a7322df). Pre-trace
       criteria are judged as written, by a model other than the lead, and code computes DONE = open DONE ∧ every
       criterion MET. States: c8 (goal-(a) criteria only), s61@132/127, and the legacy `optee-ctl-runs/lab/` false DONE
       once a seam exists. Registered falsifier: c8 goal-(a) rejects ≥ 3/6, or s61 DONE ≥ 2/12.
     - Derivation reliability is the limit after that: Gl derives Linux in only 4/6 draws, and a list without it gives
       no protection (Gl1 false DONE 3/4 here).
     - c8 (`criteria-verdict-demo-2026-11-01/demo.py` `rebuild_c8`) is the acceptance state. The grading reference is
       never given to a model.
  3. **Attribution:** the clean baseline exists (slice 69: G7 from `task.txt` alone). Next is a `--no-scratch` control
     gate run, to isolate the lead's verify sessions. Other gaps open in slice 69, not blocked on the founder:
     - the TA session (open_session ITEM_NOT_FOUND after 5 kmod generations): a self-correction target, once goal (b)'s
       bar (item 6) says it is required;
     - whether a loadable module counts as G5 (`task.txt` asks for "a NetBSD driver").
  4. **Stale deliveries:** s60 5/5 and s61 3/3 arrived 22–55 steps late. Count contradictions across runs before
     building any guard.
  5. **History growth** (prompts to ~390k tokens, latency 1.5–3× after step 120): measure a generic old-output
     compaction on the recorded traces before any core change.
  6. **Open, non-blocking:**
     - Goal (b)'s proof bar: is a TA session required, or is an attach with OP-TEE answers (G7) enough?
     - The completion gate also needs item E's held-out comparisons and an unmerged promotion PR to `main`.
  7. **Carried from before slice 60:** widen slice 52's veto finding before building a fresh-context running review.
