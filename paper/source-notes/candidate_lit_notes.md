# Candidate Literature Notes for Sections 3-5

These notes are append-only candidates. They are not selected citations until reviewed in the literature sheet.

## AI Chains: Transparent and Controllable Human-AI Interaction by Chaining Large Language Model Prompts

- Identifier: https://doi.org/10.1145/3491102.3517582
- Status: candidate
- Source query: inspectable AI systems; steering AI systems; transparent controllable LLM interaction
- Supports: 3.1 Design Goals; 3.2 System Overview; 4.4 Sidecar Feedback and Human Correction Workflow
- Why it matters: LLM-chain interface work for transparency, controllability, and debugging intermediate outputs.

## PromptChainer: Chaining Large Language Model Prompts through Visual Programming

- Identifier: https://doi.org/10.1145/3491101.3519729
- Status: candidate
- Source query: inspectable AI systems; steering AI systems; AI workflow debugging
- Supports: 3.1 Design Goals; 4.2 Retrieval Trace; 4.4 Sidecar Feedback and Human Correction Workflow
- Why it matters: Visual prompt-chain authoring work that foregrounds intermediate artifacts and debugging granularity.

## ModelTracker: Redesigning Performance Analysis Tools for Machine Learning

- Identifier: https://doi.org/10.1145/2702123.2702509
- Status: candidate
- Source query: inspectable AI systems; interactive machine learning debugging
- Supports: 4.1 Memory Representation as an Inspectable Substrate; 4.3 Memory Explorer and Topic Observatory
- Why it matters: ModelTracker supports performance analysis by making model behavior inspectable for debugging.

## Interacting with Predictions: Visual Inspection of Black-box Machine Learning Models

- Identifier: https://doi.org/10.1145/2858036.2858529
- Status: candidate
- Source query: inspectable AI systems; visual inspection of black-box machine learning
- Supports: 4.1 Memory Representation as an Inspectable Substrate; 4.3 Memory Explorer and Topic Observatory
- Why it matters: Prospector is relevant as an interactive inspection system for model predictions and local changes.

## “Why Should I Trust You?”: Explaining the Predictions of Any Classifier

- Identifier: https://doi.org/10.1145/2939672.2939778
- Status: candidate
- Source query: explainable AI; prediction explanation; model debugging
- Supports: 3.1 Design Goals; 4.2 Retrieval Trace
- Why it matters: LIME is a foundational explanation method for inspecting model decisions and trust calibration.

## Explanation in artificial intelligence: Insights from the social sciences

- Identifier: https://doi.org/10.1016/j.artint.2018.07.007
- Status: candidate
- Source query: explainable AI; human-centered explanations; explanation social sciences
- Supports: 3.1 Design Goals; 4.2 Retrieval Trace
- Why it matters: Synthesizes social-science explanation principles that can ground human-readable trace design.

## Gestalt: integrated support for implementation and analysis in machine learning

- Identifier: https://doi.org/10.1145/1866029.1866038
- Status: candidate
- Source query: interactive machine learning tooling; implementation and analysis support
- Supports: 3.2 System Overview; 4.1 Memory Representation as an Inspectable Substrate
- Why it matters: Gestalt supports the design rationale for moving between implementation artifacts and analysis views.

## Human-Centered Tools for Coping with Imperfect Algorithms During Medical Decision-Making

- Identifier: https://doi.org/10.1145/3290605.3300234
- Status: candidate
- Source query: human feedback correction AI systems; user control imperfect algorithms
- Supports: 3.1 Design Goals; 4.4 Sidecar Feedback and Human Correction Workflow
- Why it matters: Shows how domain users can steer and refine imperfect algorithmic retrieval during use.

## Toward Practices for Human-Centered Machine Learning

- Identifier: https://doi.org/10.1145/3530987
- Status: candidate
- Source query: human-centered machine learning practices; human feedback AI systems
- Supports: 3.1 Design Goals; 5 Use Case Walkthrough
- Why it matters: Provides broader HCML practices for placing user goals and values into ML system design.

## Principles of mixed-initiative user interfaces

- Identifier: https://doi.org/10.1145/302979.303030
- Status: candidate
- Source query: mixed-initiative user interfaces; steering AI systems; human correction workflow
- Supports: 3.1 Design Goals; 4.4 Sidecar Feedback and Human Correction Workflow
- Why it matters: Mixed-initiative interaction is relevant to sidecar feedback and shared-control framing.

## Seven Failure Points When Engineering a Retrieval Augmented Generation System

- Identifier: https://doi.org/10.1145/3644815.3644945
- Status: candidate
- Source query: RAG debugging retrieval trace; retrieval provenance and evidence trace
- Supports: 4.2 Retrieval Trace; 5 Use Case Walkthrough
- Why it matters: RAG failure-point analysis motivates operational trace inspection and component-level diagnosis.

## Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks

- Identifier: https://arxiv.org/abs/2005.11401
- Status: needs-review
- Source query: RAG debugging retrieval trace; retrieval provenance and evidence trace
- Supports: 3.2 System Overview; 4.2 Retrieval Trace
- Why it matters: Foundational RAG paper establishing parametric plus non-parametric memory and retrieval provenance needs. arXiv metadata verified; BibTeX intentionally left blank until manual selection/review.

## Ragas: Automated Evaluation of Retrieval Augmented Generation

- Identifier: https://arxiv.org/abs/2309.15217
- Status: needs-review
- Source query: RAG debugging retrieval trace; retrieval evaluation
- Supports: 4.2 Retrieval Trace; 5 Use Case Walkthrough
- Why it matters: RAGAS provides component metrics for context relevance and answer faithfulness. arXiv metadata verified; BibTeX intentionally left blank until manual selection/review.

## ARES: An Automated Evaluation Framework for Retrieval-Augmented Generation Systems

- Identifier: https://arxiv.org/abs/2311.09476
- Status: needs-review
- Source query: RAG debugging retrieval trace; retrieval evaluation; human annotations
- Supports: 4.2 Retrieval Trace; 5 Use Case Walkthrough
- Why it matters: ARES evaluates RAG components separately and can inform trace/evidence quality checks. arXiv metadata verified; BibTeX intentionally left blank until manual selection/review.

## RAGBench: Explainable Benchmark for Retrieval-Augmented Generation Systems

- Identifier: https://arxiv.org/abs/2407.11005
- Status: needs-review
- Source query: RAG debugging retrieval trace; retrieval provenance and evidence trace
- Supports: 4.2 Retrieval Trace; 5 Use Case Walkthrough
- Why it matters: RAGBench/TRACe is relevant to explainable and actionable RAG evaluation signals. arXiv metadata verified; BibTeX intentionally left blank until manual selection/review.

# Verified Candidate Literature Notes for Sections 3-5

These papers were selected to support the revised Section 3-5 argument after DOI/arXiv verification. They are used only after their BibTeX entries are present in `paper/references.bib` and the source audit passes.

## AI Chains: Transparent and Controllable Human-AI Interaction by Chaining Large Language Model Prompts

- Identifier: https://doi.org/10.1145/3491102.3517582
- Status: verified-selected
- Source query: inspectable AI systems; steering AI systems; transparent controllable LLM interaction
- Supports: 3.1 Design Goals; 3.2 System Overview; 4.4 Sidecar Feedback and Human Correction Workflow
- Why it matters: Supports the design rationale for exposing intermediate AI steps, controllability, and debugging subcomponents.

## PromptChainer: Chaining Large Language Model Prompts through Visual Programming

- Identifier: https://doi.org/10.1145/3491101.3519729
- Status: verified-selected
- Source query: inspectable AI systems; steering AI systems; AI workflow debugging
- Supports: 3.1 Design Goals; 4.2 Retrieval Trace; 4.4 Sidecar Feedback and Human Correction Workflow
- Why it matters: Supports visual programming and multi-granularity debugging of LLM chains as a precedent for inspecting memory and retrieval workflows.

## ModelTracker: Redesigning Performance Analysis Tools for Machine Learning

- Identifier: https://doi.org/10.1145/2702123.2702509
- Status: verified-selected
- Source query: inspectable AI systems; interactive machine learning debugging
- Supports: 4.1 Memory Representation as an Inspectable Substrate; 4.3 Memory Explorer and Topic Observatory
- Why it matters: Supports inspecting model behavior through interactive diagnostic views rather than only aggregate scores.

## Interacting with Predictions: Visual Inspection of Black-box Machine Learning Models

- Identifier: https://doi.org/10.1145/2858036.2858529
- Status: verified-selected
- Source query: inspectable AI systems; visual inspection of black-box machine learning
- Supports: 4.1 Memory Representation as an Inspectable Substrate; 4.3 Memory Explorer and Topic Observatory
- Why it matters: Supports local and visual inspection of black-box model behavior, relevant to Memory Explorer and Topic Observatory.

## Human-Centered Tools for Coping with Imperfect Algorithms During Medical Decision-Making

- Identifier: https://doi.org/10.1145/3290605.3300234
- Status: verified-selected
- Source query: human feedback correction AI systems; user control imperfect algorithms
- Supports: 3.1 Design Goals; 4.4 Sidecar Feedback and Human Correction Workflow
- Why it matters: Supports interface mechanisms that let domain users refine imperfect algorithmic retrieval during use.

## Principles of mixed-initiative user interfaces

- Identifier: https://doi.org/10.1145/302979.303030
- Status: verified-selected
- Source query: mixed-initiative user interfaces; steering AI systems; human correction workflow
- Supports: 3.1 Design Goals; 4.4 Sidecar Feedback and Human Correction Workflow
- Why it matters: Supports the sidecar correction workflow as a mixed-initiative boundary between automation and direct human control.

## Seven Failure Points When Engineering a Retrieval Augmented Generation System

- Identifier: https://doi.org/10.1145/3644815.3644945
- Status: verified-selected
- Source query: RAG debugging retrieval trace; retrieval provenance and evidence trace
- Supports: 4.2 Retrieval Trace; 5 Use Case Walkthrough
- Why it matters: Supports the need to inspect retrieval failures during operation rather than treating RAG as a hidden reliable component.

## Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks

- Identifier: https://arxiv.org/abs/2005.11401
- Status: verified-selected
- Source query: RAG debugging retrieval trace; retrieval provenance and evidence trace
- Supports: 3.2 System Overview; 4.2 Retrieval Trace
- Why it matters: Foundational RAG reference for contrasting traditional retrieved-passage context with layered, inspectable meeting memory.
