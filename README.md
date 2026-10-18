# SaveMyCustomers 🚀

### Proactive Customer Risk Detection Powered by Jev System One

**SaveMyCustomers** is  a context-awared financial intelligence project that helps businesses identify customers showing early signs of financial risk.

Instead of waiting until customers stop purchasing or invoices become seriously overdue, SaveMyCustomers analyzes accounting activity to identify meaningful changes and prioritize customers who may need attention.

Our core idea is simple:

> **Use Jev System One to make intelligent first-pass financial decisions, and reserve deeper System Two reasoning for situations that truly need it.**

---

## 🎯 The Problem

Businesses generate thousands of financial transactions, but important customer warning signs are often hidden inside accounting data.

For example:

- A regular customer suddenly reduces purchases.
- A customer's invoices are increasingly overdue.
- Payment delays grow over time.
- Purchasing increases, but payment health deteriorates.
- Multiple financial signals suggest a customer relationship may be at risk.

Traditional accounting dashboards display financial metrics, but business owners still need to determine **which changes matter and which customers require action**.

**SaveMyCustomers aims to turn financial data into proactive customer-risk intelligence.**

---

## 💡 Our Solution

SaveMyCustomers uses **Jev System One** as the primary financial event interpretation and escalation layer.

The system is designed to:

1. Monitor customer financial activity.
2. Detect meaningful changes in purchasing and payment behavior.
3. Prioritize financial events that may require attention.
4. Apply deterministic financial safeguards for critical risks.
5. Escalate complex or ambiguous situations to a System Two reasoning model.
6. Surface actionable customer-risk insights.

### Proposed Architecture

```text
       QuickBooks Accounting Data
                  |
                  v
       Customer Financial Signals
                  |
                  v
           Jev System One
        First-Pass Decision Layer
                  |
                  v
        Financial Risk Guardrails
                  |
           +------+------+
           |             |
           v             v
     Routine Events   Complex / High-Risk
           |             |
           |             v
           |         System Two
           |       Deep Reasoning
           |             |
           +------+------+
                  |
                  v
           SaveMyCustomers
        Prioritized Customer Alerts
```

**Jev is the central intelligence layer**, helping make financial monitoring more selective and cost-efficient.

The complete hybrid architecture is a proposed next step; this project primarily evaluates the underlying decision models.

---

## 📊 Dataset

We worked with a multi-company accounting dataset containing:

| Data | Count |
|------|------:|
| Companies | 100 |
| Industries | 71 |
| Customers | 8,322 |
| Invoices | 84,451 |
| Payment records | 143,616 |

The accounting records allow us to analyze customer purchasing patterns, invoice activity, overdue balances, and payment behavior.

### Financial Signals Analyzed

- Revenue and purchasing trends
- Invoice frequency
- Payment behavior
- Overdue accounts receivable
- Payment aging
- Contradictory financial indicators

---

## 🧪 Evaluation Methodology

We compared four approaches:

| Model | Purpose |
|-------|---------|
| Rules | Traditional threshold-based detection |
| XGBoost | Machine learning baseline |
| Jev System One | Financial event interpretation and escalation |
| GPT-mini | General-purpose language model baseline |

### Evaluation Stages

**1. Company-Specific Evaluation**

We reconstructed customer financial activity for Company 003 and evaluated models using customer-disjoint development data.

**2. Cross-Company Transfer**

We evaluated a frozen XGBoost baseline across 40 companies, including 39 held-out companies, to investigate generalization beyond the original training company.

**3. Financial Stress Testing**

We generated controlled changes in customer purchasing behavior across multiple companies.

**4. Multi-Signal Evaluation**

We created a final benchmark of **1,302 validated synthetic financial scenarios across 217 customer contexts**.

The six scenarios were:

| Scenario | Description |
|----------|-------------|
| A | Stable financial activity |
| B | Purchasing slowdown |
| C | Payment warning |
| D | Reinforcing negative financial signals |
| E | Improving financial signals |
| F | Conflicting positive and negative signals |

This benchmark tests whether models can interpret financial changes and decide when escalation is appropriate.

---

## 🏆 Key Results

### Jev System One vs GPT-mini

Results from the final **1,302-event multi-signal benchmark**:

| Metric | Jev System One | GPT-mini |
|--------|---------------:|---------:|
| Escalation F1 | **67.1%** | 58.4% |
| Escalation Precision | **59.4%** | 44.3% |
| Escalation Recall | 77.0% | 85.5% |

### Jev's Key Advantages

- **+8.7 percentage points higher escalation F1** than GPT-mini.
- **+15.1 percentage points higher escalation precision** than GPT-mini.
- More selective escalation behavior on the multi-signal benchmark.
- Promising inference economics for continuous financial monitoring.

These results highlight Jev's potential as a **System One decision layer for prioritizing customer-risk events**.

---

## 💰 Cost Efficiency

Separate operational experiments produced the following estimated inference costs:

| Metric | Jev | GPT-mini |
|--------|----:|---------:|
| Estimated cost per 1,000 events | **$0.0422** | $0.4569 |
| Estimated cost per 1 million events | **$42.16** | $456.86 |

Jev demonstrated approximately **10.8× lower estimated per-event inference cost** across these separate measurements.

The million-event figures are illustrative linear projections, not production billing measurements.

**Note:** Jev and GPT-mini were measured on different evaluation workloads and request strategies. These results suggest a cost advantage but are not a fully controlled cost comparison.

---

## ⚡ Inference Performance

| Metric | Jev | GPT-mini |
|--------|----:|---------:|
| Average latency per event | 331.5 ms | 121.5 ms |

Jev's latency was measured using individual requests, while GPT-mini's latency was amortized across batched requests.

This demonstrates subsecond average Jev inference, although the latency measurements are not directly comparable.

---

## 🧠 Why System One + System Two?

Not every accounting event needs deep reasoning.

Many financial events can be interpreted using a lightweight first-pass model. More complicated situations may require additional financial context and reasoning.

Our experiments suggest a promising architecture:

- **Jev System One:** Interpret financial changes and prioritize potential escalations.
- **Financial Guardrails:** Detect critical accounting conditions independently.
- **System Two:** Perform deeper analysis for selected complex or high-risk cases.
- **SaveMyCustomers:** Present prioritized customer-risk insights.

This approach aims to reduce unnecessary expensive reasoning while preserving attention on important financial risks.

---

## 🛠️ Technical Stack

- **Python** — Data processing and evaluation
- **Pandas / NumPy** — Financial data analysis
- **Jev System One API** — Financial event classification
- **XGBoost** — Machine learning baseline
- **GPT-mini** — Language model baseline
- **Matplotlib / Seaborn** — Benchmark visualizations
- **Jupyter Notebook** — Experiments, charts, and findings

---

## 📈 What We Demonstrated

Our project demonstrates:

1. Financial event reconstruction from accounting records.
2. Customer-level financial signal analysis.
3. Controlled multi-signal financial stress testing.
4. Benchmarking Jev against rules, XGBoost, and GPT-mini.
5. Stronger Jev escalation precision and F1 on the final benchmark.
6. Promising Jev inference cost efficiency.
7. A data-driven design for selective System One-to-System Two escalation.

---

## 🔮 Future Improvements

- Implement the complete System One-to-System Two routing pipeline.
- Add deterministic checks for critical payment and purchasing risks.
- Evaluate the hybrid system end to end.
- Integrate with live QuickBooks accounting data.
- Generate customer-risk explanations and recommended actions.
- Validate alerts against real customer outcomes.

---

## ⚠️ Evaluation Notes

The benchmark uses **synthetic financial scenarios and predefined policy labels**.

Some scenarios revealed model-specific weaknesses, motivating additional safeguards and deeper reasoning for difficult cases.

The results support Jev's promise as a first-pass escalation layer, but do not establish production reliability or measured savings for the complete hybrid architecture.

---

## ❤️ Our Vision

**SaveMyCustomers helps businesses move from reactive financial reporting to proactive customer intelligence.**

By combining **Jev System One's selective escalation capabilities** with targeted deeper reasoning, we aim to help businesses identify customer risks earlier, focus attention where it matters, and protect valuable customer relationships.

**SaveMyCustomers — Detect Earlier. Escalate Smarter. Retain More Customers.**