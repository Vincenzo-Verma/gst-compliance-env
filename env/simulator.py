"""
Core GST business logic simulator.
Implements real Indian GST rules: GSTIN validation, rate validation,
tax math checks, ITC eligibility under CGST Act.
"""
import re
from typing import Dict, List, Tuple, Optional, Any

# ── Constants ───────────────────────────────────────────────────────────────

VALID_GST_RATES = {0, 5, 12, 18, 28}

# GSTIN: 2-digit state code + 10-char PAN + 1 entity number + Z + 1 check digit
GSTIN_PATTERN = re.compile(
    r"^[0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$"
)

# Indian state codes for GSTIN validation
VALID_STATE_CODES = {
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
    "21", "22", "23", "24", "27", "29", "30", "32", "33", "34",
    "35", "36", "37", "38"
}

# ITC blocked categories under Section 17(5) of CGST Act
ITC_BLOCKED_CATEGORIES = {
    "personal_vehicle": "section_17_5_motor_vehicle",
    "food_beverage": "section_17_5_food_beverage",
    "club_membership": "section_17_5_personal_use",
    "health_club": "section_17_5_personal_use",
    "cosmetic_surgery": "section_17_5_personal_use",
    "life_insurance_personal": "section_17_5_personal_use",
}

REQUIRED_INVOICE_FIELDS = [
    "invoice_id", "invoice_date", "gstin_supplier",
    "gstin_buyer", "taxable_value", "gst_rate", "category"
]


class GSTSimulator:
    """
    Simulates GST compliance rules and invoice validation logic.
    All validation methods are deterministic and return structured results.
    """

    def validate_gstin(self, gstin: str) -> Tuple[bool, Optional[str]]:
        """
        Validate GSTIN format.
        Returns (is_valid, error_reason).
        Real GSTIN: 15 chars — 2 state + 10 PAN + 1 entity + Z + 1 check.
        """
        if not gstin or not isinstance(gstin, str):
            return False, "GSTIN is empty or not a string"
        gstin = gstin.strip().upper()
        if len(gstin) != 15:
            return False, f"GSTIN must be 15 characters, got {len(gstin)}"
        state_code = gstin[:2]
        if state_code not in VALID_STATE_CODES:
            return False, f"Invalid state code: {state_code}"
        if not GSTIN_PATTERN.match(gstin):
            return False, (
                "GSTIN format invalid "
                "(expected: 2 state + 5 alpha + 4 digit + 1 alpha + alphanumeric + Z + alphanumeric)"
            )
        return True, None

    def validate_invoice(self, invoice: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Validate a single invoice against GST rules.
        Returns list of {error_type, field, description} dicts.
        Empty list means invoice is valid.
        """
        errors = []

        # 1. Check required fields
        for field in REQUIRED_INVOICE_FIELDS:
            if field not in invoice or invoice[field] is None or invoice[field] == "":
                errors.append({
                    "error_type": "missing_field",
                    "field": field,
                    "description": f"Required field '{field}' is missing or empty"
                })

        # 2. Validate supplier GSTIN
        supplier_gstin = invoice.get("gstin_supplier", "")
        valid, reason = self.validate_gstin(supplier_gstin)
        if not valid:
            errors.append({
                "error_type": "invalid_gstin_supplier",
                "field": "gstin_supplier",
                "description": f"Supplier GSTIN invalid: {reason}"
            })

        # 3. Validate buyer GSTIN
        buyer_gstin = invoice.get("gstin_buyer", "")
        valid, reason = self.validate_gstin(buyer_gstin)
        if not valid:
            errors.append({
                "error_type": "invalid_gstin_buyer",
                "field": "gstin_buyer",
                "description": f"Buyer GSTIN invalid: {reason}"
            })

        # 4. Validate GST rate
        gst_rate = invoice.get("gst_rate")
        if gst_rate is not None and float(gst_rate) not in VALID_GST_RATES:
            errors.append({
                "error_type": "invalid_gst_rate",
                "field": "gst_rate",
                "description": (
                    f"GST rate {gst_rate}% is not valid. "
                    f"Valid rates: {sorted(VALID_GST_RATES)}"
                )
            })

        # 5. Validate tax calculation
        taxable = invoice.get("taxable_value", 0) or 0
        rate = invoice.get("gst_rate", 0) or 0
        igst = invoice.get("igst", 0) or 0
        cgst = invoice.get("cgst", 0) or 0
        sgst = invoice.get("sgst", 0) or 0

        # Either IGST alone (inter-state) or CGST+SGST (intra-state)
        actual_tax = igst if igst > 0 else (cgst + sgst)
        expected_tax = round(taxable * rate / 100, 2)

        if abs(actual_tax - expected_tax) > 1.0:  # ₹1 tolerance
            errors.append({
                "error_type": "tax_calculation_mismatch",
                "field": "igst",
                "description": (
                    f"Tax mismatch: expected ₹{expected_tax} "
                    f"({rate}% of ₹{taxable}), got ₹{actual_tax}"
                )
            })

        return errors

    def check_itc_eligibility(
        self, invoice: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], float]:
        """
        Check if an ITC claim is eligible under CGST Act.
        Returns (is_eligible, blocking_section, eligible_amount).
        """
        total_tax = invoice.get("igst", 0) or (
            invoice.get("cgst", 0) + invoice.get("sgst", 0)
        )

        # Check Section 17(5) blocked categories
        category = invoice.get("category", "")
        if category in ITC_BLOCKED_CATEGORIES:
            return False, ITC_BLOCKED_CATEGORIES[category], 0.0

        # Check supplier GSTIN validity
        valid, _ = self.validate_gstin(invoice.get("gstin_supplier", ""))
        if not valid:
            return False, "supplier_gstin_invalid", 0.0

        # Check supplier filing status
        if invoice.get("supplier_filing_status") == "non_filer":
            return False, "supplier_non_filer", 0.0

        return True, None, round(total_tax, 2)

    def check_reconciliation_mismatch(
        self, invoice: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if invoice has a mismatch between register and portal values.
        Returns (has_mismatch, mismatch_details).
        """
        mismatches = {}
        portal_tv = invoice.get("portal_taxable_value")
        register_tv = invoice.get("taxable_value")
        if portal_tv is not None and abs(portal_tv - register_tv) > 0.5:
            mismatches["taxable_value"] = {
                "register": register_tv,
                "portal": portal_tv,
                "correct": portal_tv  # portal (government) value is authoritative
            }

        portal_igst = invoice.get("portal_igst")
        register_igst = invoice.get("igst")
        if portal_igst is not None and abs(portal_igst - register_igst) > 0.5:
            mismatches["igst"] = {
                "register": register_igst,
                "portal": portal_igst,
                "correct": portal_igst
            }

        return len(mismatches) > 0, mismatches
