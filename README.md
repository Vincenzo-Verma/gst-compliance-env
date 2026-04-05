---
title: GST Compliance Env
emoji: 🧾
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# GST Compliance Agent Environment

[![OpenEnv](https://img.shields.io/badge/OpenEnv-v1.0-blue)](https://openenv.dev)
[![HF Space](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Space-yellow)](https://huggingface.co/spaces/YOUR_USERNAME/gst-compliance-env)

An **OpenEnv** environment where AI agents learn to handle Indian GST
(Goods and Services Tax) compliance workflows — the tax system used by
14 million+ Indian businesses filing ₹1.87 lakh crore in monthly returns.

## Why This Matters

GST compliance errors cost Indian businesses crores in penalties annually.
CAs and tax professionals spend hours on tasks that are structurally
well-defined enough for agents to learn: format validation, math checks,
legal rule application. This environment trains agents on exactly those tasks.

## Environment Overview

| Property | Value |
|----------|-------|
| Domain | Indian Tax Compliance |
| Episodes | Single-task episodes |
| Action Space | Discrete (8 action types) |
| Observation Space | Structured JSON |
| Reward Type | Dense (step-level) + terminal |
| Max Steps | 10 / 20 / 30 (by task) |

## Tasks

### Task 1: Invoice Validation (Easy)
**Objective:** Review 5 GST invoices. Flag all errors with correct error type.
**Difficulty:** Easy — 2 injected errors, clear right/wrong criteria
**Baseline Score:** ~0.65
**Key skills needed:** GSTIN format, GST rate enumeration, tax math

### Task 2: GSTR-1 Reconciliation (Medium)
**Objective:** Find and correct 4 mismatches across 15 invoices (register vs portal).
**Difficulty:** Medium — must identify which invoices differ, then correct them
**Baseline Score:** ~0.42
**Key skills needed:** Comparative analysis, value correction

### Task 3: ITC Fraud Audit (Hard)
**Objective:** Audit 20 ITC claims. Find 5 invalid claims, cite the correct legal section.
**Difficulty:** Hard — requires knowing Section 17(5) categories, supplier validity rules
**Baseline Score:** ~0.28
**Key skills needed:** CGST Act knowledge, multi-factor fraud detection

## Action Space

| action_type | Parameters | Description |
|-------------|-----------|-------------|
| `flag_error` | invoice_id, error_type | Flag a specific error on an invoice |
| `clear_flag` | invoice_id, error_type | Remove an incorrect flag |
| `approve_itc` | invoice_id | Approve ITC claim as eligible |
| `reject_itc` | invoice_id, legal_section | Reject ITC with legal basis |
| `correct_value` | invoice_id, field_name, corrected_value | Fix reconciliation mismatch |
| `file_return` | — | Submit and end episode |
| `request_info` | — | No-op (mild penalty) |
| `validate_invoice` | invoice_id | Trigger validation (informational) |

**Valid error_types:** `invalid_gstin_supplier`, `invalid_gstin_buyer`, `missing_field`, `invalid_gst_rate`, `tax_calculation_mismatch`

**Valid legal_sections:** `section_17_5_personal_use`, `section_17_5_food_beverage`, `section_17_5_motor_vehicle`, `supplier_non_filer`, `supplier_gstin_invalid`

## Observation Space

```json
{
  "task_id": "invoice_validation_easy",
  "step_number": 3,
  "phase": "validation",
  "invoices": [
    {
      "invoice_id": "INV-E001",
      "invoice_date": "2024-08-15",
      "gstin_supplier": "27ABCDE1234F1Z5",
      "gstin_buyer": "07XYZAB5678G2Z3",
      "taxable_value": 50000.00,
      "gst_rate": 18.0,
      "igst": 9000.00,
      "cgst": 0.0,
      "sgst": 0.0,
      "category": "it_services",
      "supplier_filing_status": "filer"
    }
  ],
  "flags": {"INV-E002": ["invalid_gstin_supplier"]},
  "corrections": {},
  "itc_decisions": {},
  "message": "Flagged invalid_gstin_supplier on INV-E002",
  "done": false,
  "steps_remaining": 7
}
```

## Reward Function

Rewards are dense — provided at each step, not just at episode end:

| Action | Reward |
|--------|--------|
| Correct error flag | +0.15 |
| False positive flag | -0.05 |
| Correct ITC decision | +0.10 |
| Correct + right legal section | +0.15 total |
| Wrong ITC decision | -0.10 |
| Correct reconciliation | +0.15 |
| Wrong reconciliation | -0.05 |
| File return (proportional) | up to +0.20 |
| Step efficiency penalty | -0.02 |

## Setup & Usage

### Local Development

```bash
# Clone and install
git clone https://huggingface.co/spaces/Vincenzo-Verma/gst-compliance-env
cd gst-compliance-env
pip install -r requirements.txt

# Generate invoice data
python env/data/generator.py

# Start the environment server
uvicorn env.main:app --host 0.0.0.0 --port 7860

# Run baseline inference (in another terminal)
export HF_TOKEN=your_api_key
export MODEL_NAME=gpt-4o-mini
export API_BASE_URL=https://api.openai.com/v1
python inference.py
```

### Docker

```bash
docker build -t gst-compliance-env .
docker run -p 7860:7860 gst-compliance-env

# Test it's running
curl -X POST http://localhost:7860/reset?task_id=invoice_validation_easy
```

### OpenEnv Validation

```bash
pip install openenv-core
openenv validate
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/reset?task_id=...` | Start new episode |
| POST | `/step` | Send action, get observation + reward |
| GET | `/state` | Get current episode state |
| GET | `/tasks` | List all available tasks |
| GET | `/health` | Health check |

## Baseline Scores

Tested with `gpt-4o-mini` (temperature=0.1):

| Task | Score | Success? |
|------|-------|---------|
| invoice_validation_easy | 0.65 | ✅ |
| gstr1_reconciliation_medium | 0.42 | ✅ |
| itc_audit_hard | 0.28 | ❌ |
| **Average** | **0.45** | — |

## License

MIT
