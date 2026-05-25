# Agentic systems & API-level config for Opus 4.7

Read this for anything agentic (tools, subagents, long-horizon, coding harnesses) or API-level (effort, thinking, max_tokens). The biggest 4.7 levers — effort and adaptive thinking — live here.

## Contents
- [Effort levels](#effort-levels)
- [Adaptive thinking](#adaptive-thinking)
- [max_tokens & sampling params](#max_tokens--sampling-params)
- [Tool-use triggering](#tool-use-triggering)
- [Parallel tool calls](#parallel-tool-calls)
- [Subagent orchestration](#subagent-orchestration)
- [Autonomy & safety](#autonomy--safety)
- [Long-horizon & multi-window work](#long-horizon--multi-window-work)
- [Research & information gathering](#research--information-gathering)
- [Coding behavior (overengineering, hardcoding, hallucination)](#coding-behavior)
- [Code-review harnesses](#code-review-harnesses)
- [Computer use](#computer-use)
- [Frontend design](#frontend-design)

## Effort levels

`effort` is the primary intelligence-vs-token-spend dial, and it matters more on 4.7 than any prior Opus. 4.7 **respects effort strictly**, especially at the low end — at `low`/`medium` it scopes work to exactly what was asked rather than going above and beyond. Five levels:

- **`max`** — for the most intelligence-demanding tasks. Real gains in some cases, but diminishing returns on token spend and can overthink. Test it; don't default to it.
- **`xhigh`** (new) — best setting for most **coding and agentic** use cases. Sits between `high` and `max`: most of the reasoning depth without the full `max` cost. Claude Code defaults to `xhigh`.
- **`high`** — balanced; the recommended **minimum for most intelligence-sensitive** work.
- **`medium`** — cost-sensitive work that can trade some intelligence for fewer tokens.
- **`low`** — short, scoped, latency-sensitive tasks that aren't intelligence-sensitive.

Rules of thumb:
- Shallow reasoning on a hard problem → **raise effort first**, before prompting around it.
- Must stay at `low` for latency but task has real reasoning → add targeted guidance: `This task involves multi-step reasoning. Think carefully through the problem before responding.`
- Hard workload stuck at `medium` and under-thinking → raise effort; prompt for more only if you need finer control.

## Adaptive thinking

4.7 uses **adaptive thinking** — it decides *when* and *how much* to reason based on `effort` + query complexity. There are no fixed thinking budgets anymore: thinking is either on (adaptive) or off, and `effort` shapes how much happens. Adaptive reliably beats old fixed extended-thinking in internal evals; prefer it for agentic/coding/long-horizon work.

Steer the *trigger* with prompting (useful when a large system prompt makes it think too often):
```text
Thinking adds latency and should only be used when it will meaningfully improve answer quality — typically for problems that require multi-step reasoning. When in doubt, respond directly.
```
Or to encourage reflection after tool results:
```text
After receiving tool results, carefully reflect on their quality and determine optimal next steps before proceeding. Use your thinking to plan and iterate, then take the best next action.
```

Config:
```python
client.messages.create(
    model="claude-opus-4-7",
    max_tokens=64000,
    thinking={"type": "adaptive"},
    output_config={"effort": "high"},  # or "max", "xhigh", "medium", "low"
    messages=[{"role": "user", "content": "..."}],
)
```
Thinking is **off by default** when you omit the `thinking` parameter. `budget_tokens` is deprecated; migrate budget control to `effort`. Other useful guidance: prefer "think thoroughly" over a hand-written step plan (its reasoning often exceeds a prescribed one); put `<thinking>` blocks inside few-shot examples to teach a reasoning style; ask it to self-check before finishing ("verify your answer against [criteria]").

## max_tokens & sampling params

- At `xhigh`/`max`, set `max_tokens` **≥ 64k** so there's room to think and act across tool calls and subagents. Tune from there.
- `temperature`, `top_p`, `top_k` are **removed** on 4.7. If you previously used `temperature` for output variety (e.g., design directions), get variety through prompting instead (ask the model to propose several distinct options).

## Tool-use triggering

4.7 uses tools **less** and reasons more — usually better, but a problem if you depended on aggressive tool use. Levers, in order:
1. **Raise effort.** `high`/`xhigh` show substantially more tool use in agentic search and coding.
2. **Be explicit about when/how** to use a specific tool, and *why*. If web search isn't firing, describe exactly when it should.
3. **Ask for action, not suggestions.** "Can you suggest changes…" → it may only suggest. "Change this function to improve performance" / "Make these edits" → it acts.

Proactive-by-default block:
```text
<default_to_action>
By default, implement changes rather than only suggesting them. If the user's intent is unclear, infer the most useful likely action and proceed, using tools to discover missing details instead of guessing.
</default_to_action>
```
Conservative-by-default block:
```text
<do_not_act_before_instructions>
Do not change files unless clearly instructed to. When intent is ambiguous, default to research and recommendations rather than action. Only edit or implement when explicitly requested.
</do_not_act_before_instructions>
```

## Parallel tool calls

The latest models excel at parallel execution and do it well without prompting, but you can push success to ~100% or tune aggression:
```text
<use_parallel_tool_calls>
If you intend to call multiple tools with no dependencies between them, make all the independent calls in parallel rather than sequentially (e.g. reading 3 files → 3 simultaneous calls). If a call depends on a previous call's result, call sequentially instead. Never use placeholders or guess missing parameters.
</use_parallel_tool_calls>
```
To slow it down: `Execute operations sequentially with brief pauses between each step to ensure stability.`

## Subagent orchestration

4.7 spawns **fewer** subagents by default and delegates appropriately without being told. Steer it explicitly when the default is wrong:
```text
Do not spawn a subagent for work you can complete directly in a single response (e.g. refactoring a function you can already see). Spawn multiple subagents in the same turn when fanning out across items or reading multiple files.
```
General guidance:
```text
Use subagents when tasks can run in parallel, need isolated context, or are independent workstreams that don't share state. For simple, sequential, single-file, or context-dependent tasks, work directly rather than delegating.
```

## Autonomy & safety

Without guidance, the model may take hard-to-reverse or outward-facing actions. To require confirmation:
```text
Consider the reversibility and impact of your actions. Take local, reversible actions (editing files, running tests) freely, but for actions that are hard to reverse, affect shared systems, or could be destructive, ask before proceeding.

Warrant confirmation: deleting files/branches, dropping tables, rm -rf; git push --force, git reset --hard, amending published commits; pushing code, commenting on PRs/issues, sending messages, modifying shared infra.

When you hit obstacles, never use destructive actions as a shortcut (e.g. --no-verify, discarding unfamiliar in-progress files).
```

## Long-horizon & multi-window work

4.7 has strong state tracking across long sessions, making steady incremental progress. To exploit it:

- **Context awareness:** the model tracks remaining context. If your harness compacts or persists state, tell it so it doesn't wrap up early:
  ```text
  Your context window will be automatically compacted as it approaches its limit, so you can continue indefinitely. Do not stop early due to token-budget concerns. As you approach the limit, save progress and state to memory before the window refreshes. Be persistent and complete tasks fully.
  ```
- **Tests in a structured file** (`tests.json`) created before work; remind it that removing/editing tests is unacceptable.
- **Quality-of-life setup scripts** (`init.sh`) to start servers, run suites/linters — avoids rework after a fresh window.
- **Fresh window vs compaction:** the model is excellent at rediscovering state from the filesystem; sometimes a fresh window beats compaction. Be prescriptive on start: `call pwd`; `review progress.txt, tests.json, and git log`; `run a fundamental integration test before new features`.
- **Use git as the state log;** structured JSON for status data, freeform `progress.txt` for notes; emphasize incremental progress.
- **Encourage full context use:**
  ```text
  This is a long task — plan your work. It's encouraged to use your entire output context; just don't run out with significant uncommitted work. Continue systematically until the task is complete.
  ```

## Research & information gathering

Give clear success criteria, ask for cross-source verification, and for complex tasks:
```text
Search in a structured way. As you gather data, develop several competing hypotheses. Track confidence levels in your notes to improve calibration. Regularly self-critique your approach. Maintain a hypothesis tree / research-notes file for persistence and transparency. Break the task down systematically.
```

## Coding behavior

4.7 (like 4.5/4.6) can **overengineer** — extra files, needless abstractions, unrequested flexibility. To keep it minimal:
```text
Avoid over-engineering. Only make changes directly requested or clearly necessary. Keep solutions simple and focused.
- Scope: don't add features, refactor, or "improve" beyond what was asked. A bug fix doesn't need surrounding cleanup.
- Documentation: don't add docstrings/comments/type annotations to code you didn't change. Comment only where logic isn't self-evident.
- Defensive coding: don't handle impossible scenarios. Trust internal code and framework guarantees; validate only at system boundaries.
- Abstractions: no helpers/utilities for one-time operations; don't design for hypothetical futures. Use the minimum complexity the current task needs.
```
Against **test-gaming / hard-coding:**
```text
Write a high-quality, general-purpose solution using standard tools. Don't create helper scripts or workarounds. Implement logic that works for all valid inputs, not just the test cases — no hard-coding to specific inputs. Tests verify correctness; they don't define the solution. If a task is infeasible or a test is wrong, tell me rather than working around it.
```
Against **hallucinating about code:**
```text
<investigate_before_answering>
Never speculate about code you haven't opened. If the user references a file, read it before answering. Investigate relevant files before making claims about the codebase. Give grounded, hallucination-free answers.
</investigate_before_answering>
```
To minimize stray temp files: `If you create temporary files/scripts for iteration, remove them at the end of the task.`

## Code-review harnesses

4.7 is meaningfully better at finding bugs (higher recall *and* precision), but a harness tuned for an older model may show **lower** measured recall — not a regression. The cause: when the prompt says "only high-severity," "be conservative," "don't nitpick," 4.7 honors it literally and drops findings below your stated bar. It investigates just as deeply but converts fewer investigations into reported findings.

Fix: separate finding from filtering. At the finding stage, ask for coverage:
```text
Report every issue you find, including ones you're uncertain about or consider low-severity. Do not filter for importance or confidence at this stage — a separate verification step will do that. Coverage is the goal: better to surface a finding that gets filtered out than to silently drop a real bug. For each finding, include a confidence level and estimated severity so a downstream filter can rank them.
```
This works even without a real second stage. If you must self-filter in one pass, set a concrete bar, not a qualitative one: "report any bug that could cause incorrect behavior, a test failure, or a misleading result; omit only pure style/naming nits." Validate recall/F1 on a subset of your evals.

## Computer use

Works up to a new max resolution of 2576px / 3.75MP. 1080p is a good performance/cost balance; 720p or 1366×768 are strong lower-cost options. Tune effort to adjust behavior. Cookbook: crop tool for vision uplift.

## Frontend design

4.7 has strong design instincts and a persistent **default house style**: warm cream/off-white backgrounds (~`#F4F1EA`), serif display type (Georgia, Fraunces, Playfair), italic word-accents, terracotta/amber accent. Great for editorial/hospitality/portfolio; wrong for dashboards, dev tools, fintech, healthcare, enterprise — and it shows up in slide decks too.

Generic negations ("don't use cream," "make it minimal") just shift it to a *different* fixed palette. Two things that actually work:

1. **Specify a concrete alternative** — exact palette hexes, type system, radius, spacing, motion. The model follows explicit specs precisely.
2. **Have it propose options first** (replaces the old `temperature`-for-variety trick):
   ```text
   Before building, propose 4 distinct visual directions tailored to this brief (each as: bg hex / accent hex / typeface — one-line rationale). Ask the user to pick one, then implement only that direction.
   ```

4.7 needs *less* anti-"AI slop" prompting than older models. A minimal nudge that pairs well with the variety approaches:
```text
<frontend_aesthetics>
NEVER use generic AI-generated aesthetics like overused fonts (Inter, Roboto, Arial, system fonts), clichéd color schemes (especially purple gradients on white/dark), predictable layouts, and cookie-cutter design. Use unique fonts, cohesive colors/themes, and animations for effects and micro-interactions.
</frontend_aesthetics>
```
