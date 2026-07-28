---
name: tech-social-writer
description: Research, draft, and review evidence-grounded Chinese technology posts and short X threads. Use for AI papers, models, GitHub projects, industry events, or fragmented author ideas when the result must stay factual, explain technical details in plain language, preserve the author's established voice, and avoid generic AI prose.
---

# Tech Social Writer

Turn source evidence into one useful public idea. Prefer a narrow, supported post over a complete-looking summary.

## Workflow

1. Build the evidence boundary before choosing an angle.
2. Separate source facts, source-authored conclusions, editorial inferences, and unknowns.
3. Select one claim that is both supported and worth explaining.
4. Draft for the requested format and information budget.
5. Run fact-checking as a separate pass after drafting.
6. Apply only minimal voice and Chinese prose corrections after facts are stable.

## Evidence boundary

- Treat a number, version, quote, benchmark result, date, attribution, comparison, or causal statement as a claim requiring direct source support.
- Do not strengthen “the source reports” into “this proves”.
- Do not turn correlation, a benchmark result, or a project claim into an industry-wide conclusion.
- Do not use model memory to update current model versions or market positions.
- Mark an unsupported idea as editorial inference or remove it.
- Never invent first-person use, reading, conversations, emotions, or personal experience.
- Keep the subject, test context, and comparison baseline in any sentence that reports
  a relative number. Brevity never justifies turning one benchmark result into a general claim.

## Writing decision

- Start with the most concrete fact or judgment. Do not introduce the topic twice.
- Explain only the technical details needed to understand that judgment.
- Define a necessary term by its action or effect, not with a textbook definition.
- Keep source facts and the author's interpretation distinguishable in normal prose.
- Name the project or actor before using “it” or stating a result.
- Stop when the central idea is complete. Do not add a generic industry outlook.

## Format budget

- `short_post`: one central claim, one evidence cluster, one explanation or judgment.
- `thread`: 3–4 posts that progress through claim, evidence, mechanism, and implication or limit.
- `article`: one thesis with evidence-bearing sections; do not inflate a short idea.

## Stage references

- Read [references/voice-profile.md](references/voice-profile.md) when selecting angles or drafting.
- Read [references/fact-check.md](references/fact-check.md) only for the independent post-draft verification pass.
- Read [references/chinese-edit.md](references/chinese-edit.md) when drafting or cleaning a Chinese draft.

Do not merge generation and verification into one task. A fluent draft is not evidence that its claims are true.
