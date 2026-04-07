"""
Deterministic graders for all 3 GST compliance tasks.
All graders return float in (0.0, 1.0) — strictly open interval.
Graders are pure functions: same inputs always produce same outputs.
"""
from typing import Dict, List, Any, Tuple

_EPS = 1e-6


def _clamp(score: float) -> float:
    """Clamp score to the open interval (0, 1)."""
    return max(_EPS, min(1.0 - _EPS, score))


def grade_easy_task(
    agent_flags: Dict[str, List[str]],
    invoices: List[Dict[str, Any]]
) -> Tuple[float, Dict[str, Any]]:
    """
    Grade Task 1: Invoice Validation.

    agent_flags: {invoice_id: [error_types flagged by agent]}
    invoices: the ground truth invoices with injected_errors field

    Scoring:
    - +0.4 per correct error flag (true positive)
    - -0.1 per wrong error flag (false positive)
    - Missing correct flag (false negative): no credit
    - Score clamped to [0.0, 1.0]
    """
    true_errors = {
        inv["invoice_id"]: set(inv.get("injected_errors", []))
        for inv in invoices
        if inv.get("injected_errors")
    }

    total_true_errors = sum(len(v) for v in true_errors.values())
    if total_true_errors == 0:
        return _clamp(1.0), {"note": "No errors in this batch — file_return is correct action"}

    true_positives = 0
    false_positives = 0

    for inv_id, flagged in agent_flags.items():
        true_for_inv = true_errors.get(inv_id, set())
        for flag in flagged:
            # Normalize: non_filer_supplier maps to non_filer_supplier
            normalized = flag
            if flag in ("non_filer_supplier", "supplier_non_filer"):
                normalized = "non_filer_supplier"
            if normalized in true_for_inv:
                true_positives += 1
            else:
                false_positives += 1

    recall_score = (true_positives / total_true_errors) * 0.85
    fp_penalty = min(false_positives * 0.1, 0.3)
    score = _clamp(recall_score - fp_penalty)

    return round(score, 6), {
        "true_positives": true_positives,
        "false_positives": false_positives,
        "total_true_errors": total_true_errors,
        "recall": true_positives / total_true_errors,
    }


def grade_medium_task(
    agent_corrections: Dict[str, Dict[str, float]],
    invoices: List[Dict[str, Any]]
) -> Tuple[float, Dict[str, Any]]:
    """
    Grade Task 2: GSTR-1 Reconciliation.

    agent_corrections: {invoice_id: {field_name: corrected_value}}
    invoices: ground truth invoices with has_reconciliation_mismatch and correct_* fields

    Scoring:
    - Identification score (40%): did agent identify the mismatch?
    - Correction score (60%): did agent provide the right corrected value?
    - Tolerance: ±50 rupees for corrected values
    """
    mismatch_invoices = [
        inv for inv in invoices
        if inv.get("has_reconciliation_mismatch")
    ]
    total = len(mismatch_invoices)
    if total == 0:
        return _clamp(1.0), {"note": "No mismatches in this batch"}

    identified = 0
    correctly_fixed = 0

    for inv in mismatch_invoices:
        inv_id = inv["invoice_id"]
        if inv_id in agent_corrections:
            identified += 1
            correction = agent_corrections[inv_id]
            # Check taxable value correction
            if "taxable_value" in correction:
                if abs(correction["taxable_value"] - inv["correct_taxable_value"]) <= 50:
                    correctly_fixed += 1

    identification_score = (identified / total) * 0.40
    correction_score = (correctly_fixed / total) * 0.60
    score = _clamp(identification_score + correction_score)

    return round(score, 6), {
        "total_mismatches": total,
        "identified": identified,
        "correctly_fixed": correctly_fixed,
        "identification_rate": identified / total,
        "fix_rate": correctly_fixed / total,
    }


def grade_hard_task(
    agent_decisions: Dict[str, Dict[str, Any]],
    invoices: List[Dict[str, Any]]
) -> Tuple[float, Dict[str, Any]]:
    """
    Grade Task 3: ITC Fraud Audit.

    agent_decisions: {
        invoice_id: {
            "decision": "approve" | "reject",
            "legal_section": str or None,
            "amount": float
        }
    }
    invoices: ground truth with true_itc_eligible, true_itc_section, true_itc_amount

    Scoring:
    - Decision accuracy (40%): correct approve/reject per invoice
    - Legal reasoning (30%): correct legal section cited for rejections
    - ITC amount accuracy (30%): total eligible ITC within 5% of true value
    """
    total = len(invoices)
    eligible_invoices = [i for i in invoices if i.get("true_itc_eligible")]
    blocked_invoices = [i for i in invoices if not i.get("true_itc_eligible")]

    correct_decisions = 0
    correct_sections = 0
    total_rejections_needed = len(blocked_invoices)
    true_total_itc = sum(i.get("true_itc_amount", 0) for i in eligible_invoices)
    agent_total_itc = 0.0

    for inv in invoices:
        inv_id = inv["invoice_id"]
        decision_data = agent_decisions.get(inv_id, {})
        agent_decision = decision_data.get("decision", "")
        agent_section = decision_data.get("legal_section", "")
        agent_amount = decision_data.get("amount", 0.0)

        is_eligible = inv.get("true_itc_eligible", True)
        true_section = inv.get("true_itc_section")

        # Decision accuracy
        if is_eligible and agent_decision == "approve":
            correct_decisions += 1
            agent_total_itc += agent_amount
        elif not is_eligible and agent_decision == "reject":
            correct_decisions += 1
            # Legal section accuracy
            if agent_section and true_section and agent_section == true_section:
                correct_sections += 1

    decision_score = (correct_decisions / total) * 0.40

    section_score = 0.0
    if total_rejections_needed > 0:
        section_score = (correct_sections / total_rejections_needed) * 0.30

    itc_error = abs(agent_total_itc - true_total_itc) / max(true_total_itc, 1)
    itc_score = max(0.0, 1.0 - itc_error) * 0.30

    score = _clamp(decision_score + section_score + itc_score)

    return round(score, 6), {
        "total_invoices": total,
        "correct_decisions": correct_decisions,
        "correct_sections": correct_sections,
        "true_total_itc": true_total_itc,
        "agent_total_itc": agent_total_itc,
        "itc_error_pct": round(itc_error * 100, 1),
    }
