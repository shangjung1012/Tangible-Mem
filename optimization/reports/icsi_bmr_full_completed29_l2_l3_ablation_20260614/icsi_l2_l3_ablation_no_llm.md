# ICSI L2/L3 Ablation No-LLM

Same top-60 L1 evidence for both variants; only prompt-visible topic surface changes.

## Summary

| Variant | Expected L1 recall | Avg context tokens | Visible L2 hit | Visible L3 hit |
|---|---:|---:|---:|---:|
| l1_only | 0.8958 | 7252.6 | 0.0 | 0.0 |
| l1_plus_l2_l3_surface | 0.8958 | 7358.35 | 1.0 | 0.85 |

Average token delta from L2/L3 surface: `105.75`

## Per Query

| Query | L1 recall | L1 tokens | L1+topic tokens | L2 hit | L3 hit |
|---|---:|---:|---:|---:|---:|
| icsi-heldout-q001 | 0.75 | 7321 | 7450 | 1.0 | 1.0 |
| icsi-heldout-q002 | 1.0 | 7190 | 7280 | 1.0 | 1.0 |
| icsi-heldout-q003 | 0.5 | 7834 | 7960 | 1.0 | 1.0 |
| icsi-heldout-q004 | 1.0 | 7099 | 7208 | 1.0 | 1.0 |
| icsi-heldout-q005 | 1.0 | 7454 | 7577 | 1.0 | 1.0 |
| icsi-heldout-q006 | 0.6667 | 7430 | 7565 | 1.0 | 1.0 |
| icsi-heldout-q007 | 1.0 | 7436 | 7517 | 1.0 | 1.0 |
| icsi-heldout-q008 | 1.0 | 6662 | 6751 | 1.0 | 1.0 |
| icsi-heldout-q009 | 0.75 | 6830 | 6930 | 1.0 | 1.0 |
| icsi-heldout-q010 | 0.5 | 7080 | 7213 | 1.0 | 1.0 |
| icsi-heldout-q011 | 1.0 | 7704 | 7806 | 1.0 | 1.0 |
| icsi-heldout-q012 | 0.75 | 7089 | 7221 | 1.0 | 1.0 |
| icsi-heldout-q013 | 1.0 | 7891 | 7972 | 1.0 | 1.0 |
| icsi-heldout-q014 | 1.0 | 6854 | 6951 | 1.0 | 1.0 |
| icsi-heldout-q015 | 1.0 | 7471 | 7579 | 1.0 | 1.0 |
| icsi-heldout-q016 | 1.0 | 7168 | 7287 | 1.0 | 0.0 |
| icsi-heldout-q017 | 1.0 | 7726 | 7869 | 1.0 | 0.0 |
| icsi-heldout-q018 | 1.0 | 6711 | 6809 | 1.0 | 0.0 |
| icsi-heldout-q019 | 1.0 | 6484 | 6522 | 1.0 | 1.0 |
| icsi-heldout-q020 | 1.0 | 7618 | 7700 | 1.0 | 1.0 |
