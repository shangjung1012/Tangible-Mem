# Token Analysis

Data sources:

- Generation stage: `doc/evaluation_runs/all_questions_three_methods_all_transcripts.csv`
- Judge stage: `doc/evaluation_runs/all_questions_three_methods_scored.csv`

Rows: 14 questions.

Note: the CSV `*_total_tokens` values do not equal `*_input_tokens + *_output_tokens` in these runs, so the tables below use the recorded `*_total_tokens` columns as the authoritative total.

## Generation Stage

| Method | Variant | N | Context sum | Input sum | Output sum | Total sum | Avg total / row | Median | Min | Max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Structured | Answer | 14 | 20,201 | 28,640 | 7,224 | 62,996 | 4,499.7 | 4,724.0 | 2,564 | 5,577 |
| Structured | Evidence | 14 | 20,201 | 29,438 | 4,099 | 54,650 | 3,903.6 | 3,875.5 | 2,286 | 5,085 |
| RAG | Answer | 14 | 37,054 | 34,918 | 5,235 | 63,046 | 4,503.3 | 4,791.5 | 3,664 | 4,928 |
| RAG | Evidence | 14 | 37,054 | 35,716 | 3,438 | 62,453 | 4,460.9 | 4,421.0 | 3,928 | 5,083 |
| Full transcript | Answer | 14 | 1,379,448 | 1,089,074 | 9,670 | 1,133,214 | 80,943.9 | 80,742.0 | 79,568 | 82,642 |
| Full transcript | Evidence | 14 | 1,379,448 | 1,089,872 | 9,491 | 1,133,577 | 80,969.8 | 81,202.0 | 79,048 | 81,724 |

## Judge Stage

| Method | Variant | N | Input sum | Output sum | Total sum | Avg total / row | Median | Min | Max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Structured | Answer | 14 | 12,401 | 2,183 | 36,141 | 2,581.5 | 2,545.5 | 1,728 | 3,454 |
| Structured | Evidence | 14 | 9,262 | 2,050 | 30,716 | 2,194.0 | 2,183.0 | 1,541 | 2,847 |
| RAG | Answer | 14 | 10,412 | 2,076 | 31,355 | 2,239.6 | 2,213.0 | 1,282 | 3,004 |
| RAG | Evidence | 14 | 8,601 | 1,971 | 28,545 | 2,038.9 | 2,050.5 | 1,331 | 2,944 |
| Full transcript | Answer | 14 | 14,847 | 2,303 | 37,953 | 2,710.9 | 2,682.0 | 1,842 | 4,045 |
| Full transcript | Evidence | 14 | 14,654 | 2,172 | 36,859 | 2,632.8 | 2,564.0 | 1,422 | 4,267 |

## Combined By Method

| Method | Generation total | Judge total | Grand total | Avg grand / question |
|---|---:|---:|---:|---:|
| Structured | 117,646 | 66,857 | 184,503 | 13,178.8 |
| RAG | 125,499 | 59,900 | 185,399 | 13,242.8 |
| Full transcript | 2,266,791 | 74,812 | 2,341,603 | 167,257.4 |

## Combined By Variant

| Method | Answer generation | Answer judge | Answer subtotal | Evidence generation | Evidence judge | Evidence subtotal |
|---|---:|---:|---:|---:|---:|---:|
| Structured | 62,996 | 36,141 | 99,137 | 54,650 | 30,716 | 85,366 |
| RAG | 63,046 | 31,355 | 94,401 | 62,453 | 28,545 | 90,998 |
| Full transcript | 1,133,214 | 37,953 | 1,171,167 | 1,133,577 | 36,859 | 1,170,436 |
