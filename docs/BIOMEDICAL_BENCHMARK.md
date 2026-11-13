# Phase 2 biomedical benchmark

The first benchmark contains eight terminology tasks with 17 required atomic
variants and twelve original study summaries with four independently scored
dimensions. The corpus is in `tools/benchmarks/biomedical-v1.jsonl`. Its
synthetic descriptions and reference labels are versioned development
fixtures. The study labels follow §12 of the project specification. Clinical
terminology cases include the ECMO examples from §5 and familiar spelling,
inflection and abbreviation cases. The NLM's [publication type definitions](https://www.nlm.nih.gov/mesh/2023_pubtypes.html)
provide additional context for study designs.

## Run a comparison

From the repository root, generate prompts with
`python -m scripts.biomedical_benchmark prompts`. Feed each prompt to each
candidate with the same instructions and decoding settings. Only the prompt
text is model input. Keep the exact returned text in a JSON object keyed by
case ID. An empty response is represented by an empty string. Score each file
with `python -m scripts.biomedical_benchmark score responses.json`.

The score records corpus, prompt and raw response hashes. Preserve the model
revision, weight checksum, engine build, prompt rendering, decoding settings,
Windows hardware and measured runtime alongside real candidate scores. The
reference-answer tests verify the scorer. Actual model evaluation, comparison
and application integration are tracked in [P2-01](https://github.com/studeployed/RESEARCH-Y/issues/122).

## Interpret the results

Terminology scores report required variants recovered, known incorrect
substitutions and unlisted proposals. Unlisted proposals need review before
interpretation. Case and repeated whitespace are normalized. Hyphenated,
spaced and unspaced expressions stay distinct. Study scores report exact
agreement by dimension and across all four dimensions. The combined SRMA
label is equivalent to specifying both systematic review and meta-analysis.
Invalid JSON or a
malformed answer gets zero credit and stays in its denominator.

The benchmark includes a protocol without results, a new analysis of
existing observations, a review pooling earlier studies, an RCT published
as a conference abstract, a society guideline and a title with insufficient
evidence. These cases exercise scoped distinctions. Clinical deployment
accuracy and default unreviewed classification thresholds require broader
validation. The scorer operates on local files outside research projects.
