# Foundations — model-agnostic core techniques

These techniques apply across Claude's latest models. They're the substrate the 4.7-specific advice in `SKILL.md` sits on. Read this when authoring from scratch, or when the problem is structure/format rather than a 4.7 behavior quirk.

## Contents
- [Be clear and direct](#be-clear-and-direct)
- [Add context / motivation](#add-context--motivation)
- [Use examples (few-shot)](#use-examples-few-shot)
- [Structure with XML tags](#structure-with-xml-tags)
- [Give Claude a role](#give-claude-a-role)
- [Long-context layout](#long-context-layout)
- [Output & format control](#output--format-control)
- [LaTeX vs plain text](#latex-vs-plain-text)
- [Model self-knowledge](#model-self-knowledge)
- [Migrating away from prefill](#migrating-away-from-prefill)

## Be clear and direct

Treat Claude as a brilliant new hire with zero context on your norms. State the desired output format and constraints. Use numbered/bulleted steps when order or completeness matters. If you want "above and beyond" effort, ask for it — don't expect it to be inferred from a vague prompt.

**Golden rule:** show your prompt to a colleague with minimal context. If they'd be confused, so will Claude.

Less effective: `Create an analytics dashboard`
More effective: `Create an analytics dashboard. Include as many relevant features and interactions as possible. Go beyond the basics to create a fully-featured implementation.`

## Add context / motivation

Explaining *why* an instruction matters lets Claude generalize correctly instead of following it brittlely.

Less effective: `NEVER use ellipses`
More effective: `Your response will be read aloud by a text-to-speech engine, so never use ellipses — the engine won't know how to pronounce them.`

## Use examples (few-shot)

Examples are the most reliable way to steer format, tone, and structure. Include 3–5. Make them **relevant** (mirror the real use case), **diverse** (cover edge cases, vary enough that Claude doesn't latch onto an unintended pattern), and **structured** (each in `<example>` tags, the set in `<examples>`). You can ask Claude to critique your examples for relevance/diversity or to generate more from your seed set.

## Structure with XML tags

XML tags let Claude parse a prompt that mixes instructions, context, examples, and variable input without confusing one for another. Use consistent, descriptive names (`<instructions>`, `<context>`, `<input>`). Nest when there's natural hierarchy (`<documents>` → `<document index="n">`).

## Give Claude a role

A single role sentence in the system prompt focuses behavior and tone.

```python
client.messages.create(
    model="claude-opus-4-7",
    max_tokens=1024,
    system="You are a helpful coding assistant specializing in Python.",
    messages=[{"role": "user", "content": "How do I sort a list of dictionaries by key?"}],
)
```

## Long-context layout

For large inputs (20k+ tokens):

- **Long data at the top, query at the bottom.** Placing documents above the instructions/query can improve response quality by up to ~30%, especially with complex multi-document inputs.
- **Wrap documents in metadata tags:**
  ```xml
  <documents>
    <document index="1">
      <source>annual_report_2023.pdf</source>
      <document_content>{{ANNUAL_REPORT}}</document_content>
    </document>
  </documents>

  Analyze the report and recommend Q3 focus areas.
  ```
- **Ground in quotes.** For long-document tasks, ask Claude to first extract relevant quotes into `<quotes>` tags, then reason from those. This cuts through the surrounding noise.

## Output & format control

The four levers, in order of reach:

1. **Say what to do, not what to avoid.** "Compose your response as smoothly flowing prose paragraphs" beats "don't use markdown."
2. **XML format indicators.** "Write the prose sections in `<smoothly_flowing_prose_paragraphs>` tags."
3. **Match prompt style to desired output.** The formatting of your prompt influences the output — e.g., removing markdown from the prompt reduces markdown in the response.
4. **Detailed format spec for fine control.** For heavy markdown suppression, a block like:

```text
<avoid_excessive_markdown_and_bullet_points>
When writing reports, documents, technical explanations, or any long-form content, write in clear, flowing prose using complete paragraphs. Reserve markdown primarily for `inline code`, code blocks, and simple headings (###). Avoid **bold** and *italics*.

DO NOT use ordered or unordered lists unless (a) presenting truly discrete items where a list is genuinely best, or (b) the user explicitly asks for a list or ranking.

Incorporate items naturally into sentences instead of bulleting them. Readable, flowing text that guides the reader beats fragmented points.
</avoid_excessive_markdown_and_bullet_points>
```

For visibility into reasoning after tool calls (the latest models may skip verbal summaries):
```text
After completing a task that involves tool use, provide a quick summary of the work you've done.
```

## LaTeX vs plain text

The latest models default to LaTeX for math/technical notation. To force plain text:
```text
Format your response in plain text only. Do not use LaTeX, MathJax, or markup such as \( \), $, or \frac{}{}. Write math with standard characters ("/" for division, "*" for multiplication, "^" for exponents).
```

## Model self-knowledge

```text
The assistant is Claude, created by Anthropic. The current model is Claude Opus 4.7.
```
For apps that pick model strings: `default to Claude Opus 4.7 unless the user requests otherwise. The exact model string is claude-opus-4-7.`

## Migrating away from prefill

Prefilling the **last** assistant turn is unsupported on Claude 4.6+ (returns 400). Assistant messages *elsewhere* in the conversation are unaffected. Migrate by scenario:

- **Forcing JSON/format or classification** → use [Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) (schema-constrained), or just ask for the structure (newer models match complex schemas reliably, especially with retries). For classification, use a tool with an enum field or structured outputs.
- **Skipping a preamble** (`Here is the summary:`) → instruct directly: "Respond directly without preamble. Don't start with 'Here is…', 'Based on…', etc." Or emit inside XML tags / via tool calling, and strip stray preambles in post.
- **Steering around bad refusals** → usually unnecessary now; clear prompting in the user message suffices.
- **Continuations** → move the continuation into a user message with the cut-off text: "Your previous response was interrupted and ended with `[…]`. Continue from where you left off." Or just retry if there's no UX penalty.
- **Context hydration / role consistency** → inject what were prefilled reminders into the user turn; for agentic systems, hydrate via tools or during context compaction.
