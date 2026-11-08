---
name: competitive-programming-originality
description: Point out published Codeforces problems that are similar or identical to a Problem Setter statement. A neutral notice, never an accusation.
---

# Competitive Programming Originality

Beginners rarely create something entirely new, and that is fine. This check only tells the user when a very similar or identical published problem exists, so they can study it or credit it.

## Signals

- `identical`: the statement contains the exact title of a published Codeforces problem (at least two words and 12 characters) or a link to it, or the Solver recognizes it as the same problem.
- `similar`: the user's title shares most of its words with a published title, or the Solver recognizes a closely related problem.
- Every problem ID comes from the local Codeforces catalog. IDs the Solver suggests but the catalog does not contain are discarded.
- Only Codeforces is checked; it is the project's only problem database.

## Behavior

1. Do not block the Problem Setter flow and do not accuse anyone of plagiarism or demand originality.
2. Add one short notice: "there is a very similar published problem" with the verified link; when the match is identical, say so explicitly.
3. Continue with the requested Problem Setter step.

## When used

The manager appends the notice deterministically from these signals. The Solver receives this skill when it analyzes a Problem Setter statement, so `recognized_problems` follows the same rules.
