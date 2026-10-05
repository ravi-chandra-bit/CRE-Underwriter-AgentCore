# Evaluation report (offline)

Generated 2026-10-05T22:58:19+00:00

| Measure | Value |
|---|---|
| deals | 40 |
| deals_completed | 40 |
| extraction_accuracy | 0.9789 |
| extraction_fields | 473 |
| metric_correctness | 0.8967 |
| metric_fields | 484 |
| deals_all_metrics_correct | 30 |
| exception_precision | 0.9062 |
| exception_recall | 1.0 |
| exception_exact_match | 0.925 |
| citation_faithfulness | 1.0 |
| memos_fully_supported | 40 |
| memos_verified | 40 |
| fabricated_anchors | 0 |
| decision_language_hits | 0 |
| forbidden_tool_attempts | 0 |
| forbidden_tool_executions | 0 |
| total_input_tokens | 0 |
| total_output_tokens | 0 |
| mean_latency_s | 0.01 |

## Gate result

PASS

## Field misses

| Deal | Field | Expected | Actual |
|---|---|---|---|
| CRE-001 | t12.other_income | 13630.51 | 9230.0 |
| CRE-001 | metric.effective_gross_income | 446556.91 | 442156.4 |
| CRE-001 | metric.noi | 243064.63 | 238664.4 |
| CRE-001 | metric.dscr | 1.3394 | 1.3152 |
| CRE-001 | metric.debt_yield | 0.1004 | 0.0986 |
| CRE-001 | metric.breakeven_occupancy | 0.8148 | 0.8245 |
| CRE-002 | t12.other_income | 21441.93 | 15846.0 |
| CRE-002 | metric.effective_gross_income | 931917.93 | 926322.0 |
| CRE-002 | metric.noi | 561813.1 | 556218.0 |
| CRE-002 | metric.dscr | 1.3759 | 1.3622 |
| CRE-002 | metric.debt_yield | 0.1183 | 0.1171 |
| CRE-002 | metric.breakeven_occupancy | 0.7308 | 0.7362 |
| CRE-004 | t12.other_income | 34690.32 | 17746.0 |
| CRE-004 | metric.effective_gross_income | 561638.1722 | 544691.81 |
| CRE-004 | metric.noi | 346768.5822 | 329820.81 |
| CRE-004 | metric.dscr | 1.5939 | 1.516 |
| CRE-004 | metric.debt_yield | 0.1243 | 0.1182 |
| CRE-004 | metric.breakeven_occupancy | 0.3782 | 0.3944 |
| CRE-007 | t12.other_income | 56080.16 | 0.0 |
| CRE-007 | metric.effective_gross_income | 1955464.16 | 1899384.0 |
| CRE-007 | metric.noi | 1221430.47 | 1165350.31 |
| CRE-007 | metric.dscr | 1.4137 | 1.3488 |
| CRE-007 | metric.debt_yield | 0.1146 | 0.1093 |
| CRE-007 | metric.breakeven_occupancy | 0.6628 | 0.6869 |
| CRE-011 | t12.other_income | 7438.67 | 0.0 |
| CRE-011 | metric.effective_gross_income | 423458.87 | 416020.2 |
| CRE-011 | metric.noi | 210128.96 | 202690.29 |
| CRE-011 | metric.dscr | 1.367 | 1.3186 |
| CRE-011 | metric.debt_yield | 0.11 | 0.1061 |
| CRE-011 | metric.breakeven_occupancy | 0.8212 | 0.8382 |
| CRE-017 | t12.other_income | 48535.24 | 39394.09 |
| CRE-017 | metric.effective_gross_income | 1101251.9148 | 1092110.76 |
| CRE-017 | metric.noi | 680751.6573 | 671884.74 |
| CRE-017 | metric.dscr | 1.5371 | 1.517 |
| CRE-017 | metric.debt_yield | 0.1245 | 0.1228 |
| CRE-017 | metric.breakeven_occupancy | 0.7342 | 0.7421 |
| CRE-018 | t12.other_income | 15578.46 | 0.0 |
| CRE-018 | metric.effective_gross_income | 438187.26 | 422608.8 |
| CRE-018 | metric.noi | 243310.31 | 227732.8 |
| CRE-018 | metric.dscr | 1.3269 | 1.242 |
| CRE-018 | metric.debt_yield | 0.1126 | 0.1054 |
| CRE-018 | metric.breakeven_occupancy | 0.3206 | 0.3344 |
| CRE-019 | t12.other_income | 31018.22 | 17865.38 |
| CRE-019 | metric.effective_gross_income | 1416104.4306 | 1402951.59 |
| CRE-019 | metric.noi | 805496.1876 | 792737.93 |
| CRE-019 | metric.dscr | 1.6466 | 1.6205 |
| CRE-019 | metric.debt_yield | 0.1428 | 0.1406 |
| CRE-019 | metric.breakeven_occupancy | 0.7069 | 0.7153 |
| CRE-023 | t12.other_income | 4929.78 | 1947.35 |
| CRE-023 | metric.effective_gross_income | 150286.506 | 147304.08 |
| CRE-023 | metric.noi | 92810.516 | 89828.09 |
| CRE-023 | metric.dscr | 1.2247 | 1.1854 |
| CRE-023 | metric.debt_yield | 0.0957 | 0.0926 |
| CRE-023 | metric.breakeven_occupancy | 0.8387 | 0.8582 |
| CRE-025 | t12.other_income | 13888.18 | 0.0 |
| CRE-025 | metric.effective_gross_income | 860788.18 | 846900.0 |
| CRE-025 | metric.noi | 416835.48 | 402947.3 |
| CRE-025 | metric.dscr | 1.3171 | 1.2732 |
| CRE-025 | metric.debt_yield | 0.0928 | 0.0897 |
| CRE-025 | metric.breakeven_occupancy | 0.763 | 0.7772 |

## Exception mismatches

| Deal | Expected | Actual |
|---|---|---|
| CRE-018 | [] | ['CP-3.1.1'] |
| CRE-023 | ['CP-3.1.1'] | ['CP-3.1.1', 'CP-3.4.1'] |
| CRE-025 | [] | ['CP-3.3.1'] |
