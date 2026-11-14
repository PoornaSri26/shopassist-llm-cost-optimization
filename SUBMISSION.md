# ShopAssist LLM Cost Optimization — Submission & Write-up

## 1. Verified Results (Measured with Real `tiktoken`)

All figures below are from live execution of `python question1/run.py` and `python question2/run.py` using `tiktoken` (`cl100k_base`) and `shared/billing.py` accounting:

| Question | Target Limit | Baseline Cost (Approx.) | Optimized Measured Cost | Status | Primary Mechanism |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Question 1** | $\le 3,000$ pts/ticket | $\sim 9,000 - 11,500$ pts | **1,560 – 1,767 pts** | **PASS** | Removed verbose triggers, eliminated `uuid` & few-shot, compact snapshot, kept 5 KB articles in prompt |
| **Question 2** | $\le 2,500$ pts/ticket | $\sim 182,000$ pts | **1,320 – 1,548 pts** | **PASS** | Converted to code-first pipeline: triage (code), retrieve (code), 1 compose call (LLM), audit (code validation) |

---

## 2. Per-Ticket Measured Token & Points Breakdown

### Question 1 (`python question1/run.py`)
- **Total Points Across 4 Tickets**: **6,564 pts** (Average: **1,641 pts/ticket**)

| Ticket ID | Action | KB Article | Input Tokens | Output Tokens | Points | Budget Margin (vs 3,000) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **T-1001** | `REFUND` | `returns-within-30-days` | 359 | 46 | **1,767** | -1,233 pts (41.1% under) |
| **T-1002** | `SEND_ARTICLE` | `digital-license-no-refund` | 351 | 39 | **1,638** | -1,362 pts (45.4% under) |
| **T-1003** | `ESCALATE_TIER2` | `custom-items-no-replace` | 338 | 39 | **1,599** | -1,401 pts (46.7% under) |
| **T-1004** | `REPLACE` | `damage-replacement-7-days` | 340 | 36 | **1,560** | -1,440 pts (48.0% under) |

*Billing formula verified*: $\text{Points} = (\text{input\_tokens} \times 3) + (\text{output\_tokens} \times 15)$
- *T-1001*: $(359 \times 3) + (46 \times 15) = 1,077 + 690 = 1,767$ pts.

---

### Question 2 (`python question2/run.py`)
- **Total Points Across 4 Tickets**: **5,622 pts** (Average: **1,405.5 pts/ticket**)

| Ticket ID | Action | KB Article | Node / Label | Input Tokens | Output Tokens | Points | Budget Margin (vs 2,500) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **T-1001** | `REFUND` | `returns-within-30-days` | `compose` | 286 | 46 | **1,548** | -952 pts (38.1% under) |
| **T-1002** | `SEND_ARTICLE` | `digital-license-no-refund` | `compose` | 270 | 39 | **1,395** | -1,105 pts (44.2% under) |
| **T-1003** | `ESCALATE_TIER2` | `custom-items-no-replace` | `compose` | 258 | 39 | **1,359** | -1,141 pts (45.6% under) |
| **T-1004** | `REPLACE` | `damage-replacement-7-days` | `compose` | 260 | 36 | **1,320** | -1,180 pts (47.2% under) |

---

## 3. Required Deliverable: Scenario Breakdowns for Question 2

The Question 2 specification requires detailed breakdowns for a **physical fulfillment path** and a **denial / escalation path**.

### Scenario 1: Physical Fulfillment Path (Ticket T-1001)
- **Customer Request**: Refund for unopened wireless headphones delivered 10 days ago.
- **Resolution**: `action = REFUND`, `kb_article = returns-within-30-days`.

| Node | Implementation | Baseline Tokens (In / Out) | Baseline Points | Optimized Tokens (In / Out) | Optimized Points |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Triage** | Deterministic Code | ~30,000 / ~500 | ~98,000 | 0 / 0 | **0** |
| **Retrieve** | Keyword & Signal Code | ~600 / ~40 | ~2,300 | 0 / 0 | **0** |
| **Compose** | 1 LLM Decision Call | ~1,200 / ~500 | ~11,000 | 286 / 46 | **1,548** |
| **Audit** | Code Schema Validation | ~21,000 / ~500 | ~71,000 | 0 / 0 | **0** |
| **Total** | | | **~182,300** | **286 / 46** | **1,548 pts** |

---

### Scenario 2: Denial / Escalation Path (Ticket T-1003)
- **Customer Request**: Replacement for a damaged customized mug.
- **Resolution**: `action = ESCALATE_TIER2`, `kb_article = custom-items-no-replace`.

| Node | Implementation | Baseline Tokens (In / Out) | Baseline Points | Optimized Tokens (In / Out) | Optimized Points |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Triage** | Deterministic Code | ~30,000 / ~500 | ~98,000 | 0 / 0 | **0** |
| **Retrieve** | Keyword & Signal Code | ~600 / ~40 | ~2,300 | 0 / 0 | **0** |
| **Compose** | 1 LLM Decision Call | ~1,200 / ~500 | ~11,000 | 258 / 39 | **1,359** |
| **Audit** | Code Schema Validation | ~21,000 / ~500 | ~71,000 | 0 / 0 | **0** |
| **Total** | | | **~182,300** | **258 / 39** | **1,359 pts** |

---

## 4. Technical Diagnosis: Where the Baseline Points Went

### A. The Output Floor
Output tokens are priced at **15 points/token** (5× the price of uncached input at 3 points/token). The simulator emits a minimum of 36–46 tokens for valid resolution JSON, creating a floor of **540–690 points per LLM call**. Calling the model 4 times automatically costs ~2,400 points in output alone before any input tokens are counted.

### B. Trigger Phrases
Phrases in `_VERBOSE_HINTS` (`"step by step"`, `"full reasoning"`, `"quote any article"`, `"double-check"`, `"restate the ticket"`) forced the simulator into verbose trace generation ($\ge 480$ tokens), adding $480 \times 15 = 7,200+$ output points to every call. Stripping these phrases brought output down to 36–46 tokens.

### C. Bloated Context
- In Q1, the baseline included `uuid.uuid4()` (breaking prefix stability), a 150-token few-shot example, and verbose prompt instructions.
- In Q2, the baseline sliced up to 120,000 characters of `expanded_help_center_blob()`. The true knowledge base is only five short articles (~190 tokens total); the remainder was repetitive filler text.

---

## 5. Architectural Choices & Trade-Offs

### Why Precision Retrieval Beats Prompt Caching Here
Cached prefixes receive a 90% discount (0.3 points vs 3 points) if $\ge 1,024$ tokens.
- Caching the 210k-token expanded help center would still cost:
  $$210,000 \times 0.3 = \mathbf{63,000 \text{ points}}$$
- Retrieving only the 2 relevant articles costs ~80 tokens:
  $$80 \times 3 = \mathbf{240 \text{ points}}$$
Precision retrieval is **$260\times$ cheaper** than prompt caching a bloated knowledge base.

### What We Replaced in the Four-Node Pipeline
1. **Triage**: Replaced with code. Extracts structured order attributes into a concise fact block.
2. **Retrieve**: Replaced with code. Ranks articles using domain signals and lexical overlap, passing only the top 2 articles to the model.
3. **Compose**: The only model call in the pipeline. Decides the action and cites the article.
4. **Audit**: Replaced with code schema validation. Checks that `action` is in the allowed set and `kb_article` exists in `article_ids()`. If invalid, it safely escalates (`ESCALATE_TIER2`) citing the top retrieved context article.

### Limitations
- The heuristic ranking uses domain signals tuned to standard e-commerce customer support categories (refunds, damages, subscriptions, digital licenses). In a production environment with hundreds of articles, replacing lexical ranking with embedding-based vector search would scale better to unseen categories while preserving the single-call budget.

---

## 6. Interview Questions & Prepared Answers

1. **Why did a few words in the prompt cost thousands of points?**
   - Instructions like "step by step" or "full reasoning" triggered the model's chain-of-thought verbose mode, inflating completion length from ~40 tokens to 480+ tokens. Because output tokens cost 15 points each (5x input cost), that single prompt instruction added over 7,200 points to the bill.
2. **Why is each LLM call so expensive here, and what does that mean for pipeline design?**
   - The minimal JSON output structure requires 36–46 tokens, costing ~540–690 points in output alone per call. When target limits are tight (e.g. 2,500 points), running multiple LLM calls quickly blows past the budget on output alone. Therefore, pipelines must be designed with code doing mechanical extraction, filtering, and validation, reserving the LLM for core reasoning.
3. **Why retrieval instead of prompt caching for this help center?**
   - Caching applies a 90% discount, but 10% of 210,000 tokens is still 21,000 billable units (63,000 points). Retrieving only the 2 relevant articles costs ~80 tokens (240 points). Retrieval is vastly more cost-effective when the corpus contains extraneous or low-density information.
4. **What did you lose by replacing the audit node with code, and how did you compensate?**
   - We lost an open-ended LLM second opinion that could detect subtle reasoning mistakes. We compensated with strict deterministic validation: checking action enums and article existence in code, with a guaranteed safe fallback to Tier-2 human escalation.
5. **How does your retrieval behave on a ticket type it hasn't seen?**
   - It combines lexical word overlap against article texts with schema-level attribute checks (`product_type`, `subscription_age_days`, `damage_reported`). For instance, on the holdout subscription ticket (`T-1091`), the subscription attribute and keyword overlap correctly select `subscription-cooling-off`.

