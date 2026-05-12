# LLM Baseline Evaluation Report

**Model:** `gpt-4.1-mini`  **Temperature:** 0.2  **Total calls:** 30

## Aggregate scores

| Condition | Recall | Hallucinations |
|---|---|---|
| LLM-only (no context)     | 0.485 | 0 |
| LLM + pre-RAG KG context  | 0.536 | 0 |
| LLM + post-RAG KG context | 0.569 | 0 |

## Per-CQ scores

| CQ | LLM-only | +pre-RAG | +post-RAG | KG pre | KG post |
|---|---|---|---|---|---|
| **CQ1** | 0.90 | 0.90 | 0.90 | 8 rows | 8 rows |
| **CQ3** | 0.71 | 0.43 | 0.43 | 8 rows | 8 rows |
| **CQ8** | 0.67 | 1.00 | 1.00 | 1 rows | 1 rows |
| **CQ9** | 0.38 | 0.50 | 0.50 | 11 rows | 11 rows |
| **CQ10** | 0.67 | 0.50 | 0.50 | 5 rows | 5 rows |
| **LLM1** | 0.50 | 0.83 | 0.83 | 1 rows | 1 rows |
| **LLM2** | 0.60 | 0.60 | 0.60 | 2 rows | 2 rows |
| **LLM6** | 0.00 | 0.17 | 0.17 | 4 rows | 4 rows |
| **LLM7** | 0.00 | 0.00 | 0.33 | 0 rows | 7 rows |
| **LLM10** | 0.43 | 0.43 | 0.43 | 1 rows | 1 rows |
