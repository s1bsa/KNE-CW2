from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], *, required: bool = True) -> None:
    """Run a subprocess, streaming output. Exits on failure if required."""
    print(f"\n>>> {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=REPO_ROOT)
    if proc.returncode != 0:
        msg = f"  [error] {cmd[1]} exited with code {proc.returncode}"
        if required:
            print(msg + " — aborting")
            sys.exit(proc.returncode)
        print(msg + " — continuing")


def stage_baseline() -> None:
    """Stages 1-6: produce baseline TTL outputs."""
    run(["python3", "running_pipeline/structured_pipeline.py"])
    run(["python3", "running_pipeline/html_pipeline.py"])
    run(["python3", "running_pipeline/summary_pipeline.py"])
    run(["python3", "pipeline/sparql/run_all_constructs.py"])
    run(["python3", "pipeline/merging/merge_all_ttl.py"])
    run(["python3", "pipeline/merging/build_final_kg.py"])


def stage_phase3_rag(api_key: str | None) -> None:
    """Stages 7-9: gap analysis + RAG completion + rebuild final TTLs."""
    if not api_key:
        print("\n[phase 3] OPENAI_API_KEY not provided — skipping RAG stages.")
        print("         Use --api-key or set OPENAI_API_KEY.")
        return

    os.environ["OPENAI_API_KEY"] = api_key

    run(["python3", "pipeline/evaluation/gap_analysis.py"])
    run(["python3", "pipeline/evaluation/rag_enhance_kg.py"])
    run(["python3", "pipeline/merging/build_final_kg.py"])


def stage_phase4_eval() -> None:
    """Stage 10: run cheap evaluation metrics only."""
    eval_script = "pipeline/evaluation/evaluate_kg.py"
    if not (REPO_ROOT / eval_script).exists():
        print(f"\n[phase 4] {eval_script} not found — skipping evaluation.")
        return

    run(["python3", eval_script])

    print()
    print("─" * 70)
    print("Cheap evaluation metrics complete.")
    print()
    print("For the FULL evaluation (NER benchmark + LLM baseline), run these")
    print("two scripts manually. They are not run by the orchestrator because")
    print("they have specific prerequisites:")
    print()
    print("  1. NER benchmark (~15s, free, needs spaCy en_core_web_sm):")
    print("     python3 pipeline/evaluation/ner_benchmark.py")
    print()
    print("  2. LLM baseline (~30s, ~$0.10, needs OPENAI_API_KEY):")
    print("     python3 pipeline/evaluation/llm_baseline.py")
    print()
    print("Both write to data/evaluation/ alongside evaluate_kg.py output.")
    print("─" * 70)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="End-to-end pipeline orchestrator with optional Phase 3 RAG and Phase 4 evaluation"
    )

    parser.add_argument(
        "--phase3-and-4",
        action="store_true",
        help="Enable Phase 3 RAG completion (stages 7-9) AND Phase 4 cheap evaluation (stage 10)",
    )
    parser.add_argument(
        "--phase3-and-4-only",
        action="store_true",
        help="Skip baseline and run only Phase 3 + Phase 4 stages",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="OpenAI API key for Phase 3 / LLM-based scripts (overrides OPENAI_API_KEY env var)",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")

    run_extras = args.phase3_and_4 or args.phase3_and_4_only

    if args.phase3_and_4_only:
        print("\n=== RUNNING PHASE 3 + PHASE 4 ONLY (skipping baseline) ===")
        print("\n=== STAGE 7-9: PHASE 3 RAG COMPLETION ===")
        stage_phase3_rag(api_key)
        print("\n=== STAGE 10: PHASE 4 EVALUATION ===")
        stage_phase4_eval()
        return

    print("\n=== STAGE 1-6: BASELINE PIPELINE ===")
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
    print("  Pre-RAG  : data/eu_ai_act_final.ttl")
    print("  Post-RAG : data/eu_ai_act_final_RAG.ttl")
    if run_extras:
        print("  Eval     : data/evaluation/evaluation_results.json")


if __name__ == "__main__":
    main()