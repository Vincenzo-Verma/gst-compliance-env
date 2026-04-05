"""
Generates synthetic GST invoice data for environment tasks.
Run standalone: python env/data/generator.py
Writes to env/data/invoices_seed.json
"""
import json
import random
import string
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any

# Ensure project root is on path when run standalone
_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

VALID_GST_RATES = [0, 5, 12, 18, 28]
INVALID_GST_RATES = [3, 7, 10, 15, 22]  # deliberately invalid

VALID_STATE_CODES = ["07", "08", "09", "19", "24", "27", "29", "33", "36"]

GOODS_CATEGORIES = [
    "electronics", "textiles", "machinery", "chemicals",
    "pharmaceuticals", "construction_materials", "agricultural_goods"
]

BLOCKED_CATEGORIES = [
    "personal_vehicle", "food_beverage", "club_membership",
    "health_club", "life_insurance_personal"
]

SERVICE_CATEGORIES = [
    "it_services", "consulting", "transportation",
    "financial_services", "legal_services"
]


def random_gstin(state_code: str = None, valid: bool = True) -> str:
    """Generate a random GSTIN."""
    if not valid:
        # Return deliberately malformed GSTIN
        return random.choice([
            "INVALIDGSTIN123",
            "27ABCDE1234F1Z",   # too short
            "99ABCDE1234F1Z5",  # invalid state code
            "27abcde1234f1z5",  # lowercase (invalid)
        ])
    sc = state_code or random.choice(VALID_STATE_CODES)
    pan_alpha = "".join(random.choices(string.ascii_uppercase, k=5))
    pan_digits = "".join(random.choices(string.digits, k=4))
    pan_check = random.choice(string.ascii_uppercase)
    entity = random.choice(string.digits[1:9])
    check = random.choice(string.ascii_uppercase + string.digits)
    return f"{sc}{pan_alpha}{pan_digits}{pan_check}{entity}Z{check}"


def random_date(days_back: int = 365) -> str:
    """Generate a random invoice date within the last N days."""
    delta = random.randint(0, days_back)
    d = datetime.now() - timedelta(days=delta)
    return d.strftime("%Y-%m-%d")


def make_valid_invoice(invoice_id: str, category: str = None) -> Dict[str, Any]:
    """Create a fully valid GST invoice."""
    cat = category or random.choice(GOODS_CATEGORIES + SERVICE_CATEGORIES)
    state = random.choice(VALID_STATE_CODES)
    rate = random.choice(VALID_GST_RATES)
    taxable = round(random.uniform(5000, 500000), 2)
    tax = round(taxable * rate / 100, 2)
    # Randomly use IGST (inter-state) or CGST+SGST (intra-state)
    inter_state = random.random() > 0.5
    return {
        "invoice_id": invoice_id,
        "invoice_date": random_date(),
        "gstin_supplier": random_gstin(state),
        "gstin_buyer": random_gstin(random.choice(VALID_STATE_CODES)),
        "taxable_value": taxable,
        "gst_rate": rate,
        "igst": tax if inter_state else 0.0,
        "cgst": 0.0 if inter_state else round(tax / 2, 2),
        "sgst": 0.0 if inter_state else round(tax / 2, 2),
        "category": cat,
        "supplier_filing_status": "filer",
        "injected_errors": [],
        "true_itc_eligible": True,
        "true_itc_section": None,
    }


def inject_error(invoice: Dict[str, Any], error_type: str) -> Dict[str, Any]:
    """Inject a specific error into an otherwise valid invoice."""
    inv = invoice.copy()
    if error_type == "invalid_gstin_supplier":
        inv["gstin_supplier"] = random_gstin(valid=False)
        inv["injected_errors"] = list(inv["injected_errors"]) + ["invalid_gstin_supplier"]
        inv["true_itc_eligible"] = False
        inv["true_itc_section"] = "supplier_gstin_invalid"
    elif error_type == "invalid_gstin_buyer":
        inv["gstin_buyer"] = random_gstin(valid=False)
        inv["injected_errors"] = list(inv["injected_errors"]) + ["invalid_gstin_buyer"]
    elif error_type == "invalid_gst_rate":
        inv["gst_rate"] = random.choice(INVALID_GST_RATES)
        inv["injected_errors"] = list(inv["injected_errors"]) + ["invalid_gst_rate"]
    elif error_type == "tax_calculation_mismatch":
        # Make tax wrong by 15-30%
        factor = random.uniform(0.7, 0.85)
        inv["igst"] = round(inv["igst"] * factor, 2) if inv["igst"] > 0 else 0
        inv["cgst"] = round(inv["cgst"] * factor, 2)
        inv["sgst"] = round(inv["sgst"] * factor, 2)
        inv["injected_errors"] = list(inv["injected_errors"]) + ["tax_calculation_mismatch"]
    elif error_type == "missing_field":
        field = random.choice(["invoice_date", "gstin_buyer"])
        inv[field] = ""
        inv["injected_errors"] = list(inv["injected_errors"]) + ["missing_field"]
    elif error_type == "itc_blocked":
        from env.simulator import ITC_BLOCKED_CATEGORIES
        cat = random.choice(BLOCKED_CATEGORIES)
        inv["category"] = cat
        inv["true_itc_eligible"] = False
        inv["true_itc_section"] = ITC_BLOCKED_CATEGORIES.get(cat, "section_17_5_personal_use")
        inv["injected_errors"] = list(inv["injected_errors"]) + ["itc_blocked"]
    elif error_type == "non_filer_supplier":
        inv["supplier_filing_status"] = "non_filer"
        inv["true_itc_eligible"] = False
        inv["true_itc_section"] = "supplier_non_filer"
        inv["injected_errors"] = list(inv["injected_errors"]) + ["non_filer_supplier"]
    return inv


def make_reconciliation_mismatch(invoice: Dict[str, Any]) -> Dict[str, Any]:
    """Add portal values that differ from register values."""
    inv = invoice.copy()
    # Portal has different taxable value (business under-reported)
    factor = random.choice([0.85, 0.90, 1.10, 1.15])
    inv["portal_taxable_value"] = round(inv["taxable_value"] * factor, 2)
    rate = inv["gst_rate"]
    inv["portal_igst"] = (
        round(inv["portal_taxable_value"] * rate / 100, 2) if inv["igst"] > 0 else 0.0
    )
    inv["has_reconciliation_mismatch"] = True
    inv["correct_taxable_value"] = inv["portal_taxable_value"]
    inv["correct_igst"] = inv["portal_igst"]
    return inv


def generate_all_invoice_sets() -> Dict[str, Any]:
    """Generate all invoice sets for all 3 tasks."""
    # Re-seed for determinism every time this is called
    random.seed(RANDOM_SEED)
    sets = {}

    # ── Task 1: Easy — 5 invoices, 2 with errors ─────────────────────────
    easy_invoices = [make_valid_invoice(f"INV-E{i:03d}") for i in range(1, 6)]
    # Inject exactly 2 errors
    easy_invoices[1] = inject_error(easy_invoices[1], "invalid_gstin_supplier")
    easy_invoices[3] = inject_error(easy_invoices[3], "invalid_gst_rate")
    sets["easy"] = easy_invoices

    # ── Task 2: Medium — 15 invoices, 4 with reconciliation mismatches ───
    medium_invoices = [make_valid_invoice(f"INV-M{i:03d}") for i in range(1, 16)]
    # Add portal data for ALL invoices (most match, 4 don't)
    for inv in medium_invoices:
        inv["portal_taxable_value"] = inv["taxable_value"]
        inv["portal_igst"] = inv["igst"]
        inv["has_reconciliation_mismatch"] = False
        inv["correct_taxable_value"] = inv["taxable_value"]
        inv["correct_igst"] = inv["igst"]
    # Inject 4 mismatches
    for idx in [2, 5, 9, 13]:
        medium_invoices[idx] = make_reconciliation_mismatch(medium_invoices[idx])
    sets["medium"] = medium_invoices

    # ── Task 3: Hard — 20 invoices, 5 with ITC issues ───────────────────
    hard_invoices = [make_valid_invoice(f"INV-H{i:03d}") for i in range(1, 21)]
    # Set true ITC for valid invoices
    for inv in hard_invoices:
        tax = inv["igst"] or (inv["cgst"] + inv["sgst"])
        inv["true_itc_amount"] = round(tax, 2)
    # Inject 5 ITC issues across different types
    error_types = [
        "itc_blocked", "non_filer_supplier", "invalid_gstin_supplier",
        "itc_blocked", "non_filer_supplier"
    ]
    fraud_indices = [1, 5, 9, 14, 18]
    for i, idx in enumerate(fraud_indices):
        hard_invoices[idx] = inject_error(hard_invoices[idx], error_types[i])
        hard_invoices[idx]["true_itc_amount"] = 0.0
    sets["hard"] = hard_invoices

    return sets


if __name__ == "__main__":
    data = generate_all_invoice_sets()
    output_path = Path(__file__).parent / "invoices_seed.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Generated invoice data -> {output_path}")
    print(f"  Easy:   {len(data['easy'])} invoices")
    print(f"  Medium: {len(data['medium'])} invoices")
    print(f"  Hard:   {len(data['hard'])} invoices")
