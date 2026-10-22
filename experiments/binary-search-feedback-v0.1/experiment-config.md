# Binary Search Coaching Feedback Loop — Experiment Configuration v0.1

**Date:** 2026-10-21 (client time)
**Status:** Baseline captured; no skill changes made.
**Skill version:** Draft v0.1 (from Phase A findings; current skill has no embedded version).
**Invocation:** Explicit only; allow_implicit_invocation=false.
**SHA-256:** SKILL.md 6E222AE6BA2F9A37B119939558A2DE0F7808C9C0D07EAB133B8ADEAED7602491; openai.yaml 427A04D05D98A36597401B19412F907C58E5B975622CAC1CACFFCB2DBD57441A.
**Dependencies:** Skill directory contains only SKILL.md and agents/openai.yaml. No code, test runner, retrieval client, database, or judge integration was found.
**Available for experiment:** Conversation-based coaching, subagents for student/evaluator roles, local PowerShell/Python execution for student-authored code and test inputs. No external retrieval needed for the selected tasks.

## Student profile

Complete beginner to competitive programming and binary search; may know basic programming and loops. No assumed understanding of complexity, invariants, monotonic predicates, binary search on the answer, or feasibility functions. Student receives no rubric or solution in advance.

## Coaching problem

There are n packages in a fixed order, with positive integer weights. A ship can carry a contiguous sequence of packages in one day if their total weight is at most its capacity C. Packages cannot be reordered or split. Given n, the weights, and D days (1 <= D <= n), find the minimum integer capacity that ships every package within D days. Use n <= 200,000 and 1 <= weight[i] <= 1,000,000,000. Input format may be agreed during coaching; the student should first reason about the task, not receive a solution.

## Independent transfer problem

Given n distinct integer stall positions and k cows (2 <= k <= n), place all k cows in stalls to maximize the minimum distance between any two placed cows. Use n <= 200,000 and positions in [0, 1,000,000,000]. Student gets the statement only at final transfer assessment, with no step-by-step hints.

## Scoring rubric (private evaluator)

Score each competency 0-3: 0 incorrect/not demonstrated; 1 substantial coaching needed; 2 limited hints; 3 independently explained and justified. Record exact transcript evidence. Competencies: search space, monotonicity, feasibility predicate, bounds/invariants, update rules, implementation, edge cases, correctness proof, complexity analysis, independent transfer. Score code and explanation separately. Passing criteria: >=2 on every core competency; level 3 for implementation and correctness reasoning; transfer attempted without stepwise guidance and competency demonstrated at >=2; run relevant executable tests if available. Maximum five sessions. Do not infer learning from coach explanations or confidence alone.

## Session protocol

Baseline first; save complete student/coach transcript. Student and coach interact without evaluator commentary. Evaluator receives transcript only after a session and produces evidence-linked findings. No skill edits before baseline. Approved changes only, in a separate draft. Rerun relevant checks after any approved change. Keep project status iterative.
