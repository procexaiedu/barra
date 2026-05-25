---
name: opus-4-7-prompting
description: Best practices for writing and reviewing prompts, system prompts, personas, and agent/LLM instructions that target Claude Opus 4.7 (and the Claude 4.6 / 4.x latest family). Use this skill whenever the user is authoring, editing, debugging, tuning, or migrating any prompt intended to run on a Claude 4.x model — even if they never say "prompt engineering." Trigger on requests like "write a system prompt for...", "improve / tighten this prompt", "why is the model ignoring my instruction", "the model got too verbose / too terse", "tune the persona", "my prompt worked on 4.6 but acts weird on 4.7", "the agent stopped using its tools", "it spawns too many subagents", or any prompt-quality, instruction-following, verbosity, effort, or tool-triggering issue on a Claude 4.x model. Also use it before shipping a system prompt to production.
---

# Prompting Claude Opus 4.7

Opus 4.7 is the most capable generally available Claude. It runs well on existing Opus 4.6 prompts, but a handful of behavioral shifts mean prompts tuned for older models can misfire. This skill helps you **author** a new prompt for 4.7 and **review/upgrade** an existing one.

The single most important thing to internalize, and the root cause of most 4.7 surprises:

> **4.7 follows instructions literally and does exactly what you asked — no more, no less.** Where 4.6 inferred what you probably meant and filled reasonable gaps, 4.7 takes you at your word. This is a feature (precision, predictability, less thrash), but it punishes vague prompts and rewards explicit ones. The job is precision, not length — a good 4.7 prompt is not a longer one.

Everything below follows from that.

## How to use this skill

Figure out whether the user is **writing** a new prompt or **reviewing/fixing** an existing one, then jump into the matching workflow. Keep edits minimal and explain *why* each change maps to a specific 4.7 behavior — that reasoning is the value you add, and it lets the user generalize.

For depth beyond this file, load the references on demand:
- `references/foundations.md` — model-agnostic core techniques (clarity, examples, XML structure, roles, long-context layout, output/format control, prefill migration). Read when authoring from scratch or when a formatting/structure problem is the issue.
- `references/agentic-and-api.md` — effort & adaptive-thinking API config, tool-use & subagent steering, autonomy/safety, research, coding & code-review harnesses, computer use, frontend design. Read for anything agentic, API-level, or coding-harness related.
- `references/snippets.md` — a copy-paste library of ready-to-drop prompt blocks, each tagged with the symptom it fixes. Pull from here instead of rewriting common blocks by hand.

## The 4.7 behavior cheat-sheet

Map a symptom to its lever. This table is the fastest path during a review; the sections after it explain the high-frequency ones.

| Symptom / goal | What changed in 4.7 | Lever |
|---|---|---|
| Instruction applied to only the first item | Won't silently generalize | State scope: "apply to **every** section, not just the first" |
| Too verbose, or too terse | Self-calibrates length to perceived task complexity | Add explicit concision/expansion instruction + a positive example |
| Shallow reasoning on a hard task | Respects `effort` strictly, esp. at low/medium | Raise `effort` to `high`/`xhigh` — don't prompt around it |
| Agent stopped using tools | Uses tools less, reasons more | Raise effort, or explicitly say when/how to use each tool |
| Too many / too few subagents | Spawns fewer by default | Give explicit when-to-delegate guidance |
| Forced "every 3 calls, summarize" feels stale | Progress updates are better natively | Remove the scaffolding; describe desired updates if needed |
| Tone colder / fewer emoji than before | More direct, less validation-forward | Add an explicit warmth/voice instruction |
| Every UI looks cream + serif | Strong default "house style" | Specify a concrete alternative palette/type, or ask it to propose options first |
| Code review finds fewer bugs | Honors "only high-severity / don't nitpick" literally | Tell it the finding stage is **coverage**, not filtering |
| Prefilled assistant turn → 400 error | Last-turn prefill no longer supported | Use structured outputs / direct instructions (see foundations) |
| `temperature`/`top_p`/`top_k` ignored or rejected | Sampling params removed | Steer variety via prompting, not sampling |

## Authoring a prompt for 4.7

1. **Pin the target.** Confirm the model is 4.7 (or 4.x latest), the surface (raw API, an app, Claude Code), and whether the run is **autonomous** (one user turn, runs to completion) or **interactive** (many turns). This drives effort, max_tokens, and how much you front-load.

2. **Write the plan you wish the model would infer.** 4.7 won't fill gaps for you, so put the spec, the intent, and the constraints in the *first* turn. For autonomous/agentic work especially, a complete upfront brief maximizes autonomy and token efficiency; ambiguous prompts dribbled over multiple turns hurt both. Vague in, vague out.

3. **State scope explicitly.** Anywhere an instruction could apply narrowly or broadly, say which: "for every file," "in all sections," "including low-confidence cases." This is the #1 source of "it only did part of it."

4. **Prefer positive instructions.** Tell it what to do, not what to avoid. "Write in flowing prose paragraphs" beats "don't use markdown." "Report every finding" beats "don't filter." Positive examples of the target behavior steer harder than prohibitions.

5. **Structure with XML, layout for long context.** Wrap distinct content in descriptive tags (`<instructions>`, `<context>`, `<examples>`, `<input>`). For 20k+ token inputs, put the long material at the **top** and the query/instructions at the **bottom** (can lift quality ~30%). See `references/foundations.md`.

6. **Set effort and max_tokens deliberately** (if you control the API). Start `xhigh` for coding/agentic, minimum `high` for intelligence-sensitive work, `low`/`medium` only for scoped, latency-sensitive, non-critical tasks. At `xhigh`/`max`, set `max_tokens` ≥ 64k so it has room to think and act. Use adaptive thinking (`thinking: {type: "adaptive"}`), not `budget_tokens`. Details in `references/agentic-and-api.md`.

7. **Add 3–5 examples** for format/tone/structure — relevant, diverse, each in `<example>` tags. This is still the most reliable steering lever.

8. **Decide voice on purpose.** 4.7's default is direct and opinionated with little validation-forward phrasing. If you need warmth, conversational tone, or a specific persona, say so explicitly — don't assume the old warmth carries over.

9. **Run the golden-rule check.** Hand the prompt (mentally) to a competent colleague with no context. If they'd be confused about scope, format, or what "done" means, so will 4.7. Tighten the ambiguous part.

## Reviewing / upgrading an existing prompt

1. **Get the model and the symptom.** What model is it running on, and what's actually wrong — wrong scope, wrong length, shallow reasoning, no tool use, wrong tone? Map the symptom through the cheat-sheet to a lever.

2. **Hunt legacy anti-patterns.** Prompts written for 4.5/4.6 (or GPT-style prompting) carry scaffolding that 4.7 doesn't need and can be actively hurt by:
   - **ALL-CAPS `MUST` / `CRITICAL` / `NEVER` walls** — 4.5+ is responsive to the system prompt and these now *over*trigger. Replace with normal phrasing + the reason ("Use this tool when…" instead of "CRITICAL: you MUST…").
   - **Anti-laziness / "be thorough" / "if in doubt, use [tool]"** — built to fix undertriggering on older models; now causes overtriggering and overthinking. Dial back or remove; lean on `effort` instead.
   - **Forced interim status updates** ("after every 3 tool calls, summarize") — native updates are good now; remove and only re-add a *described* format if truly needed.
   - **Prefilled last assistant turn** — returns a 400 on 4.6+. Migrate (see foundations).
   - **`temperature` / `top_p` / `top_k`** — removed on 4.7; steer via prompting.
   - **Negative formatting rules** ("don't use bullet points") — flip to positive.

3. **Check every instruction for scope.** If literal reading would apply it narrowly, add the scope word. This alone fixes a large share of "it ignored my instruction" reports.

4. **Right-size effort before prompting around behavior.** Shallow reasoning, missing tool use, and under-exploration are usually an `effort` problem first. Recommend raising effort before adding compensating prompt text.

5. **Propose minimal diffs with rationale.** Show before/after for each change and one line on which 4.7 behavior it targets. Don't rewrite the whole prompt unless asked — surgical edits the user can reason about beat a black-box rewrite.

## Quality bar before you call it done

A 4.7 prompt is ready when: scope is explicit everywhere it matters; formatting/voice asks are positive and (where it counts) exemplified; effort + max_tokens fit the workload; no legacy MUST-walls or anti-laziness cruft remain; and a no-context reader could follow it. When you make changes, do a quick concrete check — apply the prompt to one representative input and confirm the symptom is gone, rather than declaring victory from the diff alone.
