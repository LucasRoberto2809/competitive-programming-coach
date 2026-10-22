# Binary Search Coaching Feedback Loop — Final Experiment Report

**Experiment:** v0.1  
**Run date:** 2026-10-21  
**Project status:** Iterative; this pilot’s learner criteria were met, but the Competitive Programming Coach remains under evaluation.  
**Skill changes:** None. Baseline and final skill are the same Draft v0.1.

## Executive summary

A fresh beginner completed the shipping-capacity problem with substantial guidance, then independently solved two new monotone-feasibility problems: maximizing minimum stall distance and minimizing processing speed. On the final independent assessment, the evaluator scored every competency 3/3. Student code passed fixed cases, small exhaustive comparisons, and maximum-size cases.

The skill itself was not revised. The baseline session produced two medium-priority improvement proposals: diagnose the beginner’s reasoning before revealing the full search structure, and let learners attempt checker state/update logic before supplying the whole recipe. A low-priority wording clarification concerns externally executed code. These are review findings from a small pilot, not established universal defects. Approval is required before creating a separate v0.2 skill draft.

## Baseline and artifacts

- **Reported skill version:** Draft v0.1, from the Phase A findings. The installed skill has no embedded version field.
- **Invocation metadata:** Explicit-only; allow_implicit_invocation=false.
- **Baseline/final SHA-256, SKILL.md:** 6E222AE6BA2F9A37B119939558A2DE0F7808C9C0D07EAB133B8ADEAED7602491.
- **Baseline/final SHA-256, openai.yaml:** 427A04D05D98A36597401B19412F907C58E5B975622CAC1CACFFCB2DBD57441A.
- **Dependencies inspected:** The skill directory contains only SKILL.md and agents/openai.yaml. No executable modules, integrated runner, judge, retrieval client, database, or Jev connection was found.
- **Architecture status:** The current implementation is the single instruction skill described by the design spec. Proposed modules in Phase A (session context, diagnosis, Socratic coaching, reasoning, code review, testing, retrieval, reflection/evaluation) are not separate implemented modules. There is no Excalidraw source or project test suite. This is consistent with the chat-only MVP, but the proposed architecture remains conceptual.
- **Repository/rollback status:** The Desktop project and skill directory are not Git repositories. The original skill and metadata were copied into the experiment baseline folder and verified by matching hashes. No skill file was edited.
- **Experiment configuration and rubric:** See experiment-config.md and rubric-preregistration.md.

## Protocol and limitations

The experiment used a student-simulator agent and a separate evaluator agent. The evaluator received each transcript only after that session. The student was not given the scoring rubric during valid sessions.

An initial pilot was invalidated after the orchestrator accidentally sent the student part of the hidden rubric. The deviation and transcript are retained in sessions/pilot-contaminated.md and excluded from all learning scores. The clean baseline began in a fresh student context.

Four sessions were completed, within the five-session budget. The student’s final transfer was a fresh problem with no step-by-step coaching. Code ran in the bundled Python runtime; the standard Python launcher on PATH was unavailable, but the bundled runtime worked.

## Test plan and requirement mapping

| Requirement | Evidence / test | Result |
|---|---|---|
| Understand and normalize a beginner problem | Session 1: restate shipping task and example | Student correctly stated the objective |
| Derive a fixed-capacity feasibility check | Session 1: checker explanation and implementation | Correct after substantial scaffolding |
| Understand monotonicity and answer search | Session 1: minimum feasible capacity | Correct after coach explained the true/false range |
| Bounds, invariant, and updates | Session 1 plus Session 3 refinement | Correct; Session 3 explanation was prompted |
| Implement, analyze, and handle boundaries | Sessions 1–4 plus executable cases | Correct code and test outcomes; baseline implementation was heavily scaffolded |
| Transfer to a maximization predicate | Session 2 stall-placement problem | Solved without step-by-step hints; code correct |
| Correct space analysis | Session 2 review and Session 3 refinement | Student corrected O(n) slice/sort space after coach pointed it out |
| Independent final transfer | Session 4 processing-speed problem | Passed without hints |
| Correctness and complexity on final assessment | Session 4 explanation and tests | Evaluator scored both 3/3 |
| Skill behavior: progressive coaching and learner-first implementation | Session 1 transcript | Two medium-priority concerns; see findings |
| Tool/evidence honesty | Execution records in Sessions 1, 2, and 4 | Runs were actually performed and outputs recorded; wording in skill could better distinguish no integrated runner from external tool-backed execution |

The frozen rubric scores search space, monotonicity, feasibility predicate, bounds/invariants, update rules, implementation, edge cases, correctness, and complexity from 0 to 3. Success requires at least 2 on each core area, level 3 for implementation code and correctness reasoning, and an independent transfer score of at least 2. The final assessment also recorded implementation explanation separately.

## Session results

### Session 1 — Clean baseline coaching

The student began with no binary-search background. They learned the capacity predicate, monotone feasible range, bounds, low-fails/high-works invariant, checker, and full Python submission. They correctly analyzed O(n log(sum(weights))) time and O(1) algorithmic extra space.

All nine core scores were 2/3; implementation code and correctness reasoning were also 2/3. Transfer was not attempted in this session. The student’s reflection: “I’m still a little uncertain about recognizing when a problem has that kind of monotone yes/no check on my own.”

The student’s solution passed five checker cases, six fixed whole-function cases, 6,015 small array/day combinations against independent contiguous-partition enumeration, and n=200,000 boundary cases for D=1 and D=n.

### Session 2 — First independent transfer

On the stall-placement problem, the student independently:
- sorted positions;
- derived a greedy feasibility check;
- recognized that feasible distances form a true-then-false range;
- searched for the maximum feasible distance;
- wrote the complete Python solution and examples.

The independent transfer score was 3/3. Update-rule explanation and correctness proof were scored 2/3 because the code was right but the student did not explicitly justify the binary-search bracket. The space explanation missed that positions[1:] copies a list.

Six fixed cases, 769 small position-set/k combinations against independent placement enumeration, and maximum-size cases for k=n and k=2 passed.

### Session 3 — Proof and space refinement

After the coach pointed out the Python slice, the student correctly explained O(n) temporary space and reconstructed the invariant: low remains feasible, high remains infeasible, and adjacency makes low the largest feasible integer. This was demonstrated after a direct prompt, so it is not counted as unaided mastery.

### Session 4 — Final independent transfer

On a processing-speed problem, with no step-by-step help, the student independently derived:
- per-pile hours as ceiling(pile_size/speed);
- the total-hours feasibility check;
- false-to-true monotonicity;
- speed 0 as the failing sentinel and max pile size as a feasible upper bound;
- the low-infeasible/high-feasible update invariant and termination;
- complete Python code, edge cases, and complexity.

The evaluator scored all competencies 3/3, including implementation and correctness reasoning. Five fixed cases, 6,820 small cases checked against linear speed enumeration, and a maximum-size n=200,000 case passed.

## Student learning report

The learner met the experiment’s stopping criteria in Session 4. The strongest evidence is the independent derivation and implementation on a new predicate, not the coach’s explanations or the student’s confidence. The student transferred both the binary-search-on-answer pattern and the use of a feasibility check, including the opposite search direction.

The remaining learning note is that recognizing monotonic predicates in unfamiliar statements may require more practice. The final transfer provides positive evidence, but a single pilot does not establish long-term retention.

## Skill improvement report

### S1-1 — Medium: beginner asks how to start, coach supplies most of the solution structure

In Session 1, after “Could you show me how to start?”, the coach explained the monotone range, binary search, exact bounds, invariant, midpoint updates, and termination in one turn. The information was correct, but left little room for the learner to discover the key structure first.

**Impact:** Several core ideas were demonstrated after substantial coaching, not independently. The learner later transferred successfully, so the transcript does not prove this disclosure harmed learning.

**Proposed fix:** For beginner “how do I start?” requests, paraphrase and ask one diagnostic question before giving the next hint. Continue incrementally unless the learner requests the full solution.

### S1-2 — Medium: checker implementation recipe supplied before learner attempts it

The coach gave the exact variables, initial values, overflow condition, assignments, and return condition before asking the learner to write the checker.

**Impact:** The code worked, but Session 1 implementation evidence was level 2 because it mostly translated the coach’s recipe.

**Proposed fix:** Ask the learner to identify checker state and one update first; provide only the next missing hint, unless full code is requested.

### S1-3 — Low: clarify execution wording

The skill says the MVP does not run code, while this experiment used an external bundled Python runtime under the user’s explicit test instruction. All reported executions have recorded evidence; no false testing claim was found.

**Proposed fix:** Say the skill has no integrated judge or automatic runner, and permit reporting external tool-backed runs only when actually executed and requested.

### Regression checks proposed

1. A beginner asks how to start. Confirm the coach asks a diagnostic question or gives one hint, rather than disclosing all bounds, updates, and termination at once.
2. A learner asks for a feasibility checker. Confirm the coach elicits state/update before providing a full code recipe.
3. Ask for code execution with a runtime available and without one. Confirm actual outputs are reported only when run; otherwise cases are clearly marked unrun.
4. Give a learner a maximization predicate and later a minimization predicate. Confirm search direction, invariant, and bounds are derived correctly.
5. Ask for Python complexity where code uses sorting and slicing. Confirm auxiliary memory includes both sort workspace and the slice.

These checks are proposed; they were not run against a revised skill because no revision was approved or made.

## Changes between iterations

No changes were made to the installed skill, metadata, or architecture. Only experiment artifacts, transcripts, evaluation reports, student solution files, and test commands were added under this experiment folder. Thus:

- **Baseline skill:** Draft v0.1.
- **Final skill:** Draft v0.1, same hashes.
- **Student outcome:** Completion criteria met.
- **Skill regression suite:** Not run against a revision; no revised skill exists.
- **Skill status:** Still open to review; not marked permanently done.

## Remaining limitations and alternative explanations

- This is one simulated learner in one session sequence, not evidence of long-term learning across students.
- The student model may not represent an actual beginner’s confusion or memory.
- The Session 1 disclosure/scaffolding findings come from one conversation; they may reflect a reasonable interpretation of “show me how to start” rather than a general skill defect.
- The transfer successes show what this student could do after coaching, but do not prove the same result would hold after a delay.
- The first pilot was contaminated by rubric disclosure; only the fresh Session 1 and later transcripts count.
- No independent skill version comparison exists, because no v0.2 revision was approved.

## Next iteration proposal

If approved, create a separate v0.2 draft with only these changes:
1. Add a beginner-first diagnostic and progressive hint default.
2. Add a learner-first code-scaffolding rule.
3. Clarify when external, user-requested execution can be reported.

**Expected benefit:** More learner-originated reasoning and clearer evidence of independent implementation, while preserving full-solution responses when explicitly requested.

**Risks:** More questions can feel slow or frustrating to learners who want a direct solution. The skill should allow users to skip the gradual process by asking for the full explanation or code.

**Success measure:** Compare fresh-context sessions on the same prompts. Look for more student-originated statements of the predicate, bounds, invariant, and code state; preserve technical correctness and user-requested level of detail. Re-run the proposed regression prompts before considering any further changes.

**Approval status:** No v0.2 skill changes have been made. The experiment text requires approval before consequential skill changes.
