from __future__ import annotations

import os

from .whole_pipeline import (
    parse_args,
    run,
    stage_baseline as stage_baseline_without_ontology,
    stage_phase3_rag,
    stage_phase4_eval,
)
from dotenv import load_dotenv
load_dotenv()


def stage_baseline() -> None:
    """Build the ontology, then run the baseline pipeline stages."""
    run(["python3", "om_n_om/build_ontology.py"])
    stage_baseline_without_ontology()


def main() -> None:
    args = parse_args()
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")

    run_extras = args.phase3_and_4 or args.phase3_and_4_only

    if args.phase3_and_4_only:
        print("\n=== RUNNING PHASE 3 + PHASE 4 ONLY (skipping ontology + baseline) ===")
        print("\n=== STAGE 7-9: PHASE 3 RAG COMPLETION ===")
        stage_phase3_rag(api_key)
        print("\n=== STAGE 10: PHASE 4 EVALUATION ===")
        stage_phase4_eval()
        return

    print("\n=== ONTOLOGY + STAGE 1-6: BASELINE PIPELINE ===")
    stage_baseline()

    if run_extras:
        print("\n=== STAGE 7-9: PHASE 3 RAG COMPLETION ===")
        stage_phase3_rag(api_key)
        print("\n=== STAGE 10: PHASE 4 EVALUATION ===")
        stage_phase4_eval()
    else:
        print("\n=== Phase 3 RAG + Phase 4 evaluation skipped ===")
        print("  Use --phase3-and-4 to enable both.")
        print("  data/eu_ai_act_final_RAG.ttl will be identical to data/eu_ai_act_final.ttl")

    print("\n=== Pipeline complete ===")
    print("  Ontology : om_n_om/aiact_ontology.ttl")
    print("  Pre-RAG  : data/eu_ai_act_final.ttl")
    print("  Post-RAG : data/eu_ai_act_final_RAG.ttl")
    if run_extras:
        print("  Eval     : data/evaluation/evaluation_results.json")


if __name__ == "__main__":
    main()