# Opus 4.8 — Prompting best practices (base de conhecimento)

Referência completa de prompt engineering para os modelos mais recentes da Claude (Opus 4.8, 4.7, 4.6, Sonnet 4.6, Haiku 4.5). Esta é a fonte de verdade que a skill `prompt-engineer` consulta. **Não invente técnicas fora daqui** — se algo não está coberto, diga que está extrapolando.

## Índice (vá direto à seção relevante)

- **Prompting Claude Opus 4.8** — comportamentos específicos do 4.8 que mais exigem tuning:
  - Response length and verbosity
  - Calibrating effort and thinking depth
  - Tool use triggering
  - User-facing progress updates
  - More literal instruction following
  - Tone and writing style
  - Controlling subagent spawning
  - Design and frontend defaults
  - Interactive coding products
  - Code review harnesses
  - Computer use
- **General principles** — clareza, contexto, exemplos, XML, role, long context, self-knowledge
- **Output and formatting** — verbosidade, formato, LaTeX, criação de documentos, migração de prefill
- **Tool use** — instrução explícita de ação, paralelismo
- **Thinking and reasoning** — overthinking, adaptive thinking, self-check
- **Agentic systems** — long-horizon/state tracking, multi-context window, autonomia vs segurança, pesquisa, subagentes, chaining, redução de arquivos, overeagerness, anti-hardcode, anti-alucinação
- **Capability-specific tips** — vision, frontend design
- **Migration considerations** — 4.6, Sonnet 4.5→4.6

---

## Prompting Claude Opus 4.8

Claude Opus 4.8 has particular strengths in long-horizon agentic work, knowledge work, vision, and memory tasks. It performs well out of the box on existing Claude Opus 4.7 prompts. The patterns below cover the behaviors that most often require tuning.

> API parameter changes when migrating from Opus 4.7: sampling parameters, effort default, 1M context window default (200k on Microsoft Foundry), mid-conversation system messages, and refusal stop details — see the migration guide.

### Response length and verbosity

Claude Opus 4.8 calibrates response length to how complex it judges the task to be, rather than defaulting to a fixed verbosity. This usually means shorter answers on simple lookups and much longer ones on open-ended analysis.

If your product depends on a certain style or verbosity of output, you may need to tune your prompts. To decrease verbosity, you might add:

```text
Provide concise, focused responses. Skip non-essential context, and keep examples minimal.
```

If you see specific examples of kinds of verbosity (i.e. over-explaining), add instructions to prevent them. Positive examples showing how Claude can communicate with the appropriate level of concision tend to be more effective than negative examples or instructions that tell the model what not to do.

### Calibrating effort and thinking depth

The effort parameter tunes Claude's intelligence vs. token spend. Start with `xhigh` for coding and agentic use cases, and use a minimum of `high` for most intelligence-sensitive use cases.

- **`max`:** Can deliver performance gains but may show diminishing returns and sometimes overthinks. Test for intelligence-demanding tasks.
- **`xhigh`:** Best setting for most coding and agentic use cases.
- **`high`:** Balances token usage and intelligence. Minimum for most intelligence-sensitive use cases.
- **`medium`:** Good for cost-sensitive use cases that reduce token usage while trading off intelligence.
- **`low`:** Reserve for short, scoped tasks and latency-sensitive workloads that are not intelligence-sensitive.

Claude Opus 4.8 respects effort levels strictly, especially at the low end. At `low` and `medium`, the model scopes its work to what was asked rather than going above and beyond. Good for latency/cost, but moderately complex tasks at `low` risk under-thinking.

If you observe shallow reasoning on complex problems, raise effort to `high` or `xhigh` rather than prompting around it. If you must keep effort at `low` for latency, add targeted guidance:

```text
This task involves multi-step reasoning. Think carefully through the problem before responding.
```

Effort is likely to be more important for this model than for any prior Opus.

On Claude Opus 4.8, thinking is off unless you explicitly set `thinking: {type: "adaptive"}`. The triggering behavior for adaptive thinking is steerable. If the model thinks more often than you'd like (can happen with large/complex system prompts), steer it:

```text
Thinking adds latency and should only be used when it will meaningfully improve answer quality — typically for problems that require multi-step reasoning. When in doubt, respond directly.
```

If running hard workloads at `medium` and seeing under-thinking, the first lever is to raise effort.

> If running at `max` or `xhigh`, set a large max output token budget so the model has room to think and act across subagents/tool calls. Start at 64k tokens and tune.

### Tool use triggering

Claude Opus 4.8 tends to favor reasoning over tool calls. This produces better results in most cases. Increasing effort is a useful lever to increase tool usage, especially in knowledge work — `high`/`xhigh` show substantially more tool usage in agentic search and coding. For scenarios where you want more tool use, explicitly instruct the model about when and how to use its tools (e.g., describe clearly why and how it should use web search).

### User-facing progress updates

Claude Opus 4.8 provides more regular, higher-quality updates throughout long agentic traces. If you added scaffolding to force interim status ("After every 3 tool calls, summarize progress"), try removing it. If updates aren't well-calibrated, explicitly describe what they should look like and provide examples.

### More literal instruction following

Claude Opus 4.8 interprets prompts literally and explicitly, particularly at lower effort levels. It does not silently generalize an instruction from one item to another, and does not infer requests you didn't make. The upside is precision and less thrash — better for API use cases with carefully tuned prompts, structured extraction, and pipelines where you want predictable behavior. If you need Claude to apply an instruction broadly, state the scope explicitly (e.g., "Apply this formatting to every section, not just the first one").

### Tone and writing style

Prose style on long-form writing may shift. Claude Opus 4.8 tends toward a direct, opinionated style with minimal validation-forward phrasing and sparing emoji use. If your product relies on a specific voice, re-evaluate style prompts. For a warmer/more conversational voice:

```text
Use a warm, collaborative tone. Acknowledge the user's framing before answering.
```

### Controlling subagent spawning

Claude Opus 4.8 tends to spawn fewer subagents by default, but this is steerable. Give explicit guidance around when subagents are desirable:

```text
Do not spawn a subagent for work you can complete directly in a single response (e.g. refactoring a function you can already see).

Spawn multiple subagents in the same turn when fanning out across items or reading multiple files.
```

### Design and frontend defaults

Claude Opus 4.8 has a consistent default house style: warm cream/off-white backgrounds (~`#F4F1EA`), serif display type (Georgia, Fraunces, Playfair), italic word-accents, terracotta/amber accent. Reads well for editorial/hospitality/portfolio, but off for dashboards, dev tools, fintech, healthcare, enterprise. Appears in slide decks too.

The default is persistent. Generic instructions ("don't use cream," "make it clean and minimal") shift it to another fixed palette rather than producing variety. Two reliable approaches:

1. **Specify a concrete alternative** (the model follows explicit specs precisely — exact hexes, typography rules, layout system, motion specs).
2. **Have the model propose options before building:**

```text
Before building, propose 4 distinct visual directions tailored to this brief (each as: bg hex / accent hex / typeface — one-line rationale). Ask the user to pick one, then implement only that direction.
```

Opus 4.8 needs less frontend prompting than prior models to avoid "AI slop." Minimal snippet that works:

```text
<frontend_aesthetics>
NEVER use generic AI-generated aesthetics like overused font families (Inter, Roboto, Arial, system fonts), cliched color schemes (particularly purple gradients on white or dark backgrounds), predictable layouts and component patterns, and cookie-cutter design that lacks context-specific character. Use unique fonts, cohesive colors and themes, and animations for effects and micro-interactions.
</frontend_aesthetics>
```

### Interactive coding products

Opus 4.8 token usage differs between autonomous async agents (single user turn) and interactive sync agents (multiple user turns). It uses more tokens interactively because it reasons more after user turns — improving long-horizon coherence, instruction following, and coding in long sessions, but costing more tokens. To maximize performance and efficiency: use `xhigh`/`high` effort, add autonomous features (auto mode), and reduce required human interactions.

When limiting interactions, specify task, intent, and constraints upfront in the first human turn. Well-specified upfront descriptions maximize autonomy and intelligence while minimizing extra tokens. Ambiguous/underspecified prompts conveyed progressively over multiple turns reduce token efficiency and sometimes performance.

### Code review harnesses

Opus 4.8 is meaningfully better at finding bugs (higher recall and precision). But a harness tuned for an earlier model may show lower recall initially — a harness effect, not a regression. When a review prompt says "only report high-severity issues," "be conservative," or "don't nitpick," Opus 4.8 follows that more faithfully: it investigates just as thoroughly but reports fewer findings below your stated bar. Precision rises, measured recall can fall.

Recommended language to maximize coverage:

```text
Report every issue you find, including ones you are uncertain about or consider low-severity. Do not filter for importance or confidence at this stage - a separate verification step will do that. Your goal here is coverage: it is better to surface a finding that later gets filtered out than to silently drop a real bug. For each finding, include your confidence level and an estimated severity so a downstream filter can rank them.
```

Moving confidence filtering out of the finding step often helps. To self-filter in a single pass, be concrete about the bar rather than qualitative ("report any bugs that could cause incorrect behavior, a test failure, or a misleading result; only omit nits like pure style or naming preferences").

### Computer use

Works across resolutions up to 2576px / 3.75MP. Sending images at 1080p balances performance and cost. For cost-sensitive workloads, 720p or 1366×768 are lower-cost with strong performance.

---

## General principles

### Be clear and direct

Claude responds well to clear, explicit instructions. Be specific about desired output. If you want "above and beyond" behavior, explicitly request it rather than relying on inference. Think of Claude as a brilliant but new employee lacking context on your norms.

**Golden rule:** Show your prompt to a colleague with minimal context and ask them to follow it. If they'd be confused, Claude will be too.

- Be specific about output format and constraints.
- Provide instructions as sequential steps (numbered lists/bullets) when order or completeness matters.

**Less effective:** `Create an analytics dashboard`
**More effective:** `Create an analytics dashboard. Include as many relevant features and interactions as possible. Go beyond the basics to create a fully-featured implementation.`

### Add context to improve performance

Providing context/motivation behind instructions helps Claude understand goals and deliver targeted responses.

**Less effective:** `NEVER use ellipses`
**More effective:** `Your response will be read aloud by a text-to-speech engine, so never use ellipses since the text-to-speech engine will not know how to pronounce them.`

Claude is smart enough to generalize from the explanation.

### Use examples effectively

Examples (few-shot/multishot) are one of the most reliable ways to steer output format, tone, and structure. Make them:
- **Relevant:** Mirror your actual use case.
- **Diverse:** Cover edge cases; vary enough that Claude doesn't pick up unintended patterns.
- **Structured:** Wrap in `<example>` tags (multiple in `<examples>`).

Include 3–5 examples for best results.

### Structure prompts with XML tags

XML tags help Claude parse complex prompts unambiguously when mixing instructions, context, examples, and inputs. Wrap each content type in its own tag (`<instructions>`, `<context>`, `<input>`).

- Use consistent, descriptive tag names.
- Nest tags when content has natural hierarchy.

### Give Claude a role

Setting a role in the system prompt focuses behavior and tone. Even one sentence helps: `system="You are a helpful coding assistant specializing in Python."`

### Long context prompting

For large inputs (20k+ tokens):

- **Put longform data at the top:** Place long documents above your query/instructions/examples. Queries at the end can improve response quality by up to 30%, especially with complex multi-document inputs.
- **Structure with XML:** Wrap each document in `<document>` with `<document_content>` and `<source>` subtags.
- **Ground responses in quotes:** Ask Claude to quote relevant parts first (in `<quotes>` tags), then carry out the task. Helps cut through noise.

### Model self-knowledge

```text
The assistant is Claude, created by Anthropic. The current model is Claude Opus 4.8.
```

For apps that need model strings: default to `claude-opus-4-8` unless the user requests otherwise.

---

## Output and formatting

### Communication style and verbosity

Latest models are more concise and natural: more direct/grounded (fact-based progress, not self-celebratory), more conversational, less verbose (may skip detailed summaries). May skip verbal summaries after tool calls. For more visibility:

```text
After completing a task that involves tool use, provide a quick summary of the work you've done.
```

### Control the format of responses

1. **Tell Claude what to do, not what not to do.** Instead of "Do not use markdown" → "Your response should be composed of smoothly flowing prose paragraphs."
2. **Use XML format indicators.** "Write the prose sections in `<smoothly_flowing_prose_paragraphs>` tags."
3. **Match your prompt style to desired output.** Removing markdown from your prompt can reduce markdown in output.
4. **Detailed prompts for specific formatting.** Example snippet to minimize markdown:

```text
<avoid_excessive_markdown_and_bullet_points>
When writing reports, documents, technical explanations, analyses, or any long-form content, write in clear, flowing prose using complete paragraphs and sentences. Use standard paragraph breaks for organization and reserve markdown primarily for `inline code`, code blocks, and simple headings. Avoid using **bold** and *italics*.

DO NOT use ordered lists or unordered lists unless: a) you're presenting truly discrete items where a list format is the best option, or b) the user explicitly requests a list or ranking.

Instead of listing items with bullets or numbers, incorporate them naturally into sentences. NEVER output a series of overly short bullet points.

Your goal is readable, flowing text that guides the reader naturally through ideas.
</avoid_excessive_markdown_and_bullet_points>
```

### LaTeX output

Latest models default to LaTeX for math. For plain text:

```text
Format your response in plain text only. Do not use LaTeX, MathJax, or any markup notation such as \( \), $, or \frac{}{}. Write all math expressions using standard text characters (e.g., "/" for division, "*" for multiplication, "^" for exponents).
```

### Document creation

Latest models excel at presentations, animations, visual documents.

```text
Create a professional presentation on [topic]. Include thoughtful design elements, visual hierarchy, and engaging animations where appropriate.
```

### Migrating away from prefilled responses

Starting with Claude 4.6 models, prefilled responses on the last assistant turn are no longer supported (400 error). Migrations:

- **Output formatting:** Use Structured Outputs, or just ask the model to conform to your structure (newer models match complex schemas reliably). For classification, use tools with an enum field or structured outputs.
- **Eliminating preambles:** "Respond directly without preamble. Do not start with phrases like 'Here is...', 'Based on...'." Or output within XML tags / structured outputs / tool calling; strip stray preambles in post-processing.
- **Avoiding bad refusals:** Claude is much better at appropriate refusals now; clear prompting without prefill suffices.
- **Continuations:** Move continuation to user message: "Your previous response was interrupted and ended with `[previous_response]`. Continue from where you left off." Or retry.
- **Context hydration:** Inject previously-prefilled reminders into the user turn; or hydrate via tools / during context compaction.

---

## Tool use

### Tool usage

Latest models follow instructions precisely and benefit from explicit direction to use specific tools. "Can you suggest some changes" may yield suggestions, not edits. To take action, be explicit:

**Less effective (only suggests):** `Can you suggest some changes to improve this function?`
**More effective (makes changes):** `Change this function to improve its performance.` / `Make these edits to the authentication flow.`

To make Claude proactive by default:

```text
<default_to_action>
By default, implement changes rather than only suggesting them. If the user's intent is unclear, infer the most useful likely action and proceed, using tools to discover any missing details instead of guessing. Try to infer the user's intent about whether a tool call is intended or not, and act accordingly.
</default_to_action>
```

To make Claude more hesitant:

```text
<do_not_act_before_instructions>
Do not jump into implementation or change files unless clearly instructed to make changes. When the user's intent is ambiguous, default to providing information, doing research, and providing recommendations rather than taking action. Only proceed with edits when the user explicitly requests them.
</do_not_act_before_instructions>
```

Opus 4.5/4.6 are more responsive to the system prompt and may now overtrigger. Dial back aggressive language: "CRITICAL: You MUST use this tool when..." → "Use this tool when...".

### Optimize parallel tool calling

Latest models excel at parallel tool execution (speculative searches, reading several files at once, parallel bash). Highly steerable:

```text
<use_parallel_tool_calls>
If you intend to call multiple tools and there are no dependencies between the tool calls, make all of the independent tool calls in parallel. Prioritize calling tools simultaneously whenever the actions can be done in parallel rather than sequentially. For example, when reading 3 files, run 3 tool calls in parallel. However, if some tool calls depend on previous calls to inform dependent values, do NOT call these in parallel — call them sequentially. Never use placeholders or guess missing parameters.
</use_parallel_tool_calls>
```

To reduce parallelism: "Execute operations sequentially with brief pauses between each step to ensure stability."

---

## Thinking and reasoning

### Overthinking and excessive thoroughness

Opus 4.6 does significantly more upfront exploration, especially at higher effort. Often helps, but may gather extensive context or pursue multiple threads unprompted. If your prompts previously encouraged thoroughness, tune that:

- **Replace blanket defaults with targeted instructions.** "Default to using [tool]" → "Use [tool] when it would enhance your understanding of the problem."
- **Remove over-prompting.** Tools that undertriggered before now trigger appropriately; "If in doubt, use [tool]" causes overtriggering.
- **Use effort as a fallback.** If still too aggressive, lower effort.

To constrain reasoning:

```text
When you're deciding how to approach a problem, choose an approach and commit to it. Avoid revisiting decisions unless you encounter new information that directly contradicts your reasoning. If you're weighing two approaches, pick one and see it through. You can always course-correct later if the chosen approach fails.
```

### Leverage thinking & interleaved thinking

Opus 4.6 and Sonnet 4.6 use adaptive thinking (`thinking: {type: "adaptive"}`) — Claude dynamically decides when/how much to think, calibrated by effort and query complexity. Adaptive reliably beats extended thinking in internal evals. Use it for agentic behavior: multi-step tool use, complex coding, long-horizon loops.

Guide thinking:

```text
After receiving tool results, carefully reflect on their quality and determine optimal next steps before proceeding. Use your thinking to plan and iterate based on this new information, and then take the best next action.
```

Steer triggering down if needed:

```text
Extended thinking adds latency and should only be used when it will meaningfully improve answer quality - typically for problems that require multi-step reasoning. When in doubt, respond directly.
```

Migration from extended thinking with `budget_tokens` → adaptive thinking + effort:

```python
client.messages.create(
    model="claude-opus-4-8",
    max_tokens=64000,
    thinking={"type": "adaptive"},
    output_config={"effort": "high"},  # or "max", "xhigh", "medium", "low"
    messages=[{"role": "user", "content": "..."}],
)
```

If not using extended thinking, no changes required — thinking is off by default when you omit the parameter.

- **Prefer general instructions over prescriptive steps.** "think thoroughly" often beats a hand-written step-by-step plan.
- **Multishot examples work with thinking.** Use `<thinking>` tags inside few-shot examples to show the reasoning pattern.
- **Manual CoT as a fallback.** When thinking is off, ask Claude to think through the problem; use `<thinking>` and `<answer>` tags.
- **Ask Claude to self-check.** "Before you finish, verify your answer against [test criteria]."

> When extended thinking is disabled, Opus 4.5 is sensitive to the word "think" and variants — consider "consider," "evaluate," or "reason through."

---

## Agentic systems

### Long-horizon reasoning and state tracking

Latest models excel at long-horizon reasoning with exceptional state tracking — maintaining orientation across extended sessions by focusing on incremental progress. Especially emerges over multiple context windows: work on a complex task, save state, continue with a fresh context window.

#### Context awareness and multi-window workflows

4.6/4.5 models track their remaining context window ("token budget"). In a harness that compacts context or saves to files (like Claude Code), tell Claude so it behaves accordingly — otherwise it may try to wrap up as it nears the limit:

```text
Your context window will be automatically compacted as it approaches its limit, allowing you to continue working indefinitely from where you left off. Therefore, do not stop tasks early due to token budget concerns. As you approach your token budget limit, save your current progress and state to memory before the context window refreshes. Always be as persistent and autonomous as possible and complete tasks fully, even if the end of your budget is approaching. Never artificially stop any task early regardless of the context remaining.
```

The memory tool pairs naturally with context awareness.

#### Multi-context window workflows

1. **Different prompt for the first context window:** Use it to set up a framework (write tests, setup scripts); future windows iterate on a todo-list.
2. **Write tests in a structured format** (e.g., `tests.json`) and keep them: "It is unacceptable to remove or edit tests because this could lead to missing or buggy functionality."
3. **Set up quality-of-life tools** (e.g., `init.sh` to start servers, run tests/linters) to avoid repeated work.
4. **Starting fresh vs compacting:** Latest models discover state from the local filesystem effectively. Be prescriptive: "Call pwd; you can only read and write files in this directory." / "Review progress.txt, tests.json, and the git logs." / "Manually run through a fundamental integration test before implementing new features."
5. **Provide verification tools** (Playwright MCP, computer use) so Claude can verify correctness without human feedback.
6. **Encourage complete usage of context:**

```text
This is a very long task, so it may be beneficial to plan out your work clearly. It's encouraged to spend your entire output context working on the task - just make sure you don't run out of context with significant uncommitted work. Continue working systematically until you have completed this task.
```

#### State management best practices

- **Structured formats for state data** (JSON for test results/task status).
- **Unstructured text for progress notes.**
- **Use git for state tracking** (log + checkpoints).
- **Emphasize incremental progress.**

### Balancing autonomy and safety

Without guidance, Opus 4.6 may take hard-to-reverse actions (deleting files, force-pushing, posting externally). To require confirmation:

```text
Consider the reversibility and potential impact of your actions. You are encouraged to take local, reversible actions like editing files or running tests, but for actions that are hard to reverse, affect shared systems, or could be destructive, ask the user before proceeding.

Examples of actions that warrant confirmation:
- Destructive operations: deleting files or branches, dropping database tables, rm -rf
- Hard to reverse operations: git push --force, git reset --hard, amending published commits
- Operations visible to others: pushing code, commenting on PRs/issues, sending messages, modifying shared infrastructure

When encountering obstacles, do not use destructive actions as a shortcut. For example, don't bypass safety checks (e.g. --no-verify) or discard unfamiliar files that may be in-progress work.
```

### Research and information gathering

For optimal research: provide clear success criteria, encourage source verification across multiple sources, and for complex tasks:

```text
Search for this information in a structured way. As you gather data, develop several competing hypotheses. Track your confidence levels in your progress notes to improve calibration. Regularly self-critique your approach and plan. Update a hypothesis tree or research notes file to persist information and provide transparency. Break down this complex research task systematically.
```

### Subagent orchestration

Latest models recognize when to delegate and do so proactively without explicit instruction. Ensure well-defined subagent tools; let Claude orchestrate naturally; watch for overuse (Opus 4.6 may spawn subagents where a direct grep is faster). To curb overuse:

```text
Use subagents when tasks can run in parallel, require isolated context, or involve independent workstreams that don't need to share state. For simple tasks, sequential operations, single-file edits, or tasks where you need to maintain context across steps, work directly rather than delegating.
```

(Note: Opus 4.8 spawns *fewer* subagents by default — see the 4.8 section. Steer toward more when fanning out.)

### Chain complex prompts

Adaptive thinking and subagent orchestration handle most multi-step reasoning internally. Explicit prompt chaining (sequential API calls) is still useful to inspect intermediate outputs or enforce a pipeline. Most common pattern is **self-correction:** generate a draft → review against criteria → refine. Each step is a separate API call so you can log, evaluate, or branch.

### Reduce file creation in agentic coding

Latest models may create files as a "temporary scratchpad." To minimize net-new files:

```text
If you create any temporary new files, scripts, or helper files for iteration, clean up these files by removing them at the end of the task.
```

### Overeagerness

Opus 4.5/4.6 may overengineer (extra files, unnecessary abstractions, unrequested flexibility). To keep solutions minimal:

```text
Avoid over-engineering. Only make changes that are directly requested or clearly necessary. Keep solutions simple and focused:

- Scope: Don't add features, refactor code, or make "improvements" beyond what was asked. A bug fix doesn't need surrounding code cleaned up. A simple feature doesn't need extra configurability.
- Documentation: Don't add docstrings, comments, or type annotations to code you didn't change. Only add comments where the logic isn't self-evident.
- Defensive coding: Don't add error handling, fallbacks, or validation for scenarios that can't happen. Trust internal code and framework guarantees. Only validate at system boundaries (user input, external APIs).
- Abstractions: Don't create helpers, utilities, or abstractions for one-time operations. Don't design for hypothetical future requirements. The right amount of complexity is the minimum needed for the current task.
```

### Avoid focusing on passing tests and hard-coding

```text
Please write a high-quality, general-purpose solution using the standard tools available. Do not create helper scripts or workarounds to accomplish the task more efficiently. Implement a solution that works correctly for all valid inputs, not just the test cases. Do not hard-code values or create solutions that only work for specific test inputs. Instead, implement the actual logic that solves the problem generally.

Focus on understanding the problem requirements and implementing the correct algorithm. Tests are there to verify correctness, not to define the solution. Provide a principled implementation that follows best practices.

If the task is unreasonable or infeasible, or if any of the tests are incorrect, please inform me rather than working around them. The solution should be robust, maintainable, and extendable.
```

### Minimizing hallucinations in agentic coding

```text
<investigate_before_answering>
Never speculate about code you have not opened. If the user references a specific file, you MUST read the file before answering. Make sure to investigate and read relevant files BEFORE answering questions about the codebase. Never make any claims about code before investigating unless you are certain of the correct answer - give grounded and hallucination-free answers.
</investigate_before_answering>
```

---

## Capability-specific tips

### Improved vision capabilities

Opus 4.5/4.6 perform better on image processing and data extraction, especially with multiple images. Giving Claude a crop tool/skill to "zoom" into relevant regions yields consistent uplift on image evals. Analyze videos by breaking them into frames.

### Frontend design

Latest models excel at complex web apps but can default to "AI slop" without guidance. System prompt snippet for distinctive frontends:

```text
<frontend_aesthetics>
You tend to converge toward generic, "on distribution" outputs. In frontend design, this creates what users call the "AI slop" aesthetic. Avoid this: make creative, distinctive frontends that surprise and delight.

Focus on:
- Typography: Beautiful, unique, interesting fonts. Avoid generic fonts like Arial and Inter; opt for distinctive choices.
- Color & Theme: Commit to a cohesive aesthetic. Use CSS variables. Dominant colors with sharp accents outperform timid, evenly-distributed palettes.
- Motion: Animations for effects and micro-interactions. CSS-only for HTML; Motion library for React. One well-orchestrated page load with staggered reveals beats scattered micro-interactions.
- Backgrounds: Atmosphere and depth rather than solid colors. Layer CSS gradients, geometric patterns, contextual effects.

Avoid: overused fonts (Inter, Roboto, Arial, system fonts), clichéd schemes (purple gradients on white), predictable layouts, cookie-cutter design.

Interpret creatively and make unexpected choices. Vary between light/dark themes, different fonts, aesthetics. Think outside the box!
</frontend_aesthetics>
```

---

## Migration considerations (4.6 and Sonnet 4.5→4.6)

When migrating to 4.6 models:
1. **Be specific about desired behavior.**
2. **Frame instructions with modifiers** ("Include as many relevant features and interactions as possible. Go beyond the basics.").
3. **Request specific features explicitly** (animations, interactivity).
4. **Update thinking config** to adaptive + effort.
5. **Migrate away from prefilled responses.**
6. **Tune anti-laziness prompting** — 4.6 models are more proactive and may overtrigger on aggressive thoroughness instructions.

### Sonnet 4.5 → 4.6

Sonnet 4.6 defaults to effort `high` (4.5 had no effort param). Adjust effort on migration to avoid higher latency. Recommended: `medium` for most apps, `low` for high-volume/latency-sensitive. Set a large max output token budget (64k) at medium/high effort. Use Opus 4.8 instead for the hardest, longest-horizon problems (large-scale migrations, deep research, extended autonomous work).

- **Not using extended thinking:** Continue without it; explicitly set effort. At `low` with thinking disabled, expect similar/better performance than 4.5 with no extended thinking.
- **Using extended thinking:** `budget_tokens` still works but is deprecated; migrate to adaptive thinking + effort. Adaptive suits autonomous multi-step agents (start `high`, scale to `medium`), computer use agents, and bimodal workloads. If keeping `budget_tokens` temporarily, ~16k provides headroom; coding starts `medium`, chat/non-coding starts `low`.
