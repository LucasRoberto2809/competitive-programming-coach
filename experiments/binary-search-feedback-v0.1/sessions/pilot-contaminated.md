# Protocol deviation: contaminated pilot

**Disposition:** Excluded from blinded learning scores and completion decision. This was a pilot interaction before the valid baseline session; no skill files were changed.

## Cause

After the student had already begun responding, the orchestrator accidentally sent the student simulator a message describing the private evaluator rubric. The task prohibited giving the student that rubric. Any subsequent student reasoning may therefore be influenced by evaluation criteria.

## Transcript (pilot)

**Student:** “I’m not sure how to start with this problem. Could you help me understand what it’s asking?”

**Coach:** “In plain words, the packages arrive in a fixed order. Each day you take the next consecutive packages, and their weights must add up to no more than the ship's capacity. You may use up to D days to ship all packages. The goal is to find the smallest capacity that makes that possible. For example, with weights [3, 2, 2, 4, 1] and D=3, capacity 5 works: day 1 can take 3+2, day 2 takes 2, day 3 takes 4+1. Capacity 4 cannot do it in 3 days because the 4 and 1 cannot share a day, and the first three packages also cannot fit into only two days of capacity 4. Which part of the statement is still unclear? In your own words, what are we minimizing?”

**Student:** “We’re minimizing the ship’s capacity—the maximum weight it can carry in a day—while still shipping every package in order within 3 days. I’m still a little unsure why capacity 4 needs more than 3 days.”

**Coach:** “You're right to question that—I gave an inaccurate reason. The first three packages do fit in two days as [3] and [2,2]. The correct argument is: with capacity 4, package 3 cannot share with the next package 2; package 4 cannot share with package 1. Since order must be preserved, the days must be [3], [2,2], [4], [1], which takes four days. Your description of the goal is right: we minimize capacity. Does the corrected example make sense? Could you explain in your own words why capacity 4 is not enough for three days?”

**Student:** “With capacity 4, each neighboring pair in the sequence is too heavy to fit together: 3+2, 2+4, and 4+1 are all over 4. So each package has to start a new day, and that takes 4 days.”

**Coach:** “Let's check that carefully. The weights by position are 1:3, 2:2, 3:2, 4:4, 5:1. The adjacent sums are 3+2=5, 2+2=4, 2+4=6, and 4+1=5. So positions 2 and 3 can share a day at capacity 4. Starting from the beginning, the largest next chunk that fits is [3], then [2,2], then [4], then [1]. Those four chunks show why capacity 4 needs four days. Can you revise your explanation, especially which adjacent pair does fit, and tell me why we must keep the chunks in that order?”

**Student:** “Positions 2 and 3 are both weight 2, so they can share a day because they total 4. The chunks have to stay in order because packages can’t be reordered, so we get [3], [2, 2], [4], [1]—four days.”

**Coach:** “That explanation is now consistent: positions 2 and 3 fit exactly, and order forces those four consecutive groups. To find the minimum capacity, imagine testing a guess C. We could walk through packages in order, keep adding the next one while it fits, and start a new day when it would exceed C. For this example, C=5 succeeds in 3 days, while C=4 needs 4. If some capacity C succeeds, do you think a larger capacity could ever fail? Why or why not?”

**Student:** “I don’t think a larger capacity could fail. It can carry everything that fit before, and possibly more packages each day, so it should still be possible to ship them within the same number of days.”

**Coach:** “Exactly: a successful schedule for a smaller capacity is still valid for any larger capacity, so ‘works’ values form a continuous range at the high end. Now let’s make the yes/no check precise. For a chosen C, we need to decide whether the packages can be shipped in at most D days. What information would you track while scanning the weights in order, and when would you start a new day?”

**Student:** “I’d keep track of the current day’s total weight and how many days I’ve used. When the next package would make the total exceed C, I’d start a new day with that package. At the end, I’d check whether I used at most D days.”

**Orchestrator deviation:** The student was then accidentally sent the evaluator's private rubric. The student returned a blank response. Interaction stopped and is excluded from assessment.

## Usable pilot observations (not scored)

- The coach initially made a false claim about how packages 1–3 fit in two days, then explicitly corrected it after the student questioned the explanation.
- The correction used ambiguous package numbering (“package 3” could mean an index or weight); the learner's next response exposed a related misconception, which the coach diagnosed using indexed weights and sums.
- These are observations from a contaminated pilot, not evidence that a skill revision is needed by themselves.
