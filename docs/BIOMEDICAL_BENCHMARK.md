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
reference-answer tests verify the scorer. This document records the first
Windows comparison. Application integration is tracked in
[P2-01](https://github.com/studeployed/RESEARCH-Y/issues/122).

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

## Windows candidate comparison, 13 November 2026

The [retained evaluation](evidence/biomedical-windows-20261113.json) contains
80 measured synthetic responses, per-case timings, build and weight checksums,
prompt and stdout hashes, raw model text and recomputable scores. Both model
files used official Q8_0 weights and six CPU threads on an Intel Core i9-14900HX.
Each case started a fresh process. Times below include model loading.

| Candidate | Answer format | Expected terms recovered / 17 | All four labels correct / 12 | Invalid responses / 20 | Seconds |
|---|---|---:|---:|---:|---:|
| Qwen3-0.6B | Prompt only | 0 | 0 | 13 | 25.5 |
| Qwen3-1.7B | Prompt only | 1 | 1 | 16 | 59.3 |
| Qwen3-0.6B | JSON schema | 3 | 0 | 0 | 25.2 |
| Qwen3-1.7B | JSON schema | 4 | 2 | 0 | 56.5 |

The 1.7B structured run correctly labelled original research in 8 cases,
study design in 5, publication format in 4 and population in 12. It proposed
19 distinct unlisted terms summed across cases. Their scientific suitability
needs researcher judgement. The structured schema contains the public
classification vocabulary and no case answers. All model-derived results
remain provisional. This comparison provides no validated confidence threshold
for autonomous scientific classification. The 1.7B structured candidate
is the stronger of these two for a research preview. The owner approved
this model for the optional [local desktop assistant](DESKTOP.md).

Run `python -m scripts.run_biomedical_candidate --help` for paths and checksum
arguments. Repeat with `--structured` to constrain answer format. The model
renderer uses Qwen3's non-thinking ChatML turn. The driver removes the pinned
engine's end-of-generation trailer and preserves the candidate's Markdown and
other formatting. An initial invocation with engine logging disabled produced
empty stdout and was discarded before scoring. The completed comparisons above
captured observable output.

Sources are the [official Windows engine build](https://github.com/ggml-org/llama.cpp/releases/tag/b12360),
[Qwen3-0.6B weights](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/tree/23749fefcc72300e3a2ad315e1317431b06b590a)
and [Qwen3-1.7B weights](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/tree/90862c4b9d2787eaed51d12237eafdfe7c5f6077).
