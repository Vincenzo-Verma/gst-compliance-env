"""
Step-level reward function providing dense signal throughout the episode.
Rewards are in [-0.5, +0.5] per step, scaled to [0, 1] at episode end.
"""
from typing import Dict, Any
from env.simulator import GSTSimulator

sim = GSTSimulator()


def compute_step_reward(
    action: Dict[str, Any],
    state: Dict[str, Any],
    result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Compute reward for a single step.

    Returns {"value": float, "breakdown": dict, "explanation": str}

    Reward components:
    - Correct flag: +0.15
    - Wrong flag (FP): -0.05
    - Correct ITC approve: +0.10
    - Correct ITC reject: +0.10
    - Correct legal section: +0.05 bonus
    - Wrong ITC decision: -0.10
    - Correct reconciliation: +0.15
    - Wrong reconciliation: -0.05
    - Filing complete: +0.20 * completeness_ratio
    - Step penalty (after 80% steps used): -0.02
    - No-op / repeated action: -0.03
    """
    action_type = action.get("action_type", "")
    invoice_id = action.get("invoice_id")

    reward = 0.0
    breakdown = {}
    explanation = ""

    invoices_map = {inv["invoice_id"]: inv for inv in state.get("invoices", [])}

    # ── flag_error ──────────────────────────────────────────────────────────
    if action_type == "flag_error" and invoice_id:
        inv = invoices_map.get(invoice_id)
        if inv:
            error_type = action.get("error_type", "")
            true_errors = set(inv.get("injected_errors", []))
            # Normalize error type
            normalized = error_type.replace("supplier_non_filer", "non_filer_supplier")
            if normalized in true_errors or error_type in true_errors:
                reward += 0.15
                breakdown["correct_flag"] = 0.15
                explanation = f"Correctly flagged {error_type} on {invoice_id}"
            else:
                reward -= 0.05
                breakdown["false_positive"] = -0.05
                explanation = f"False positive: {error_type} not an error on {invoice_id}"
        else:
            reward -= 0.03
            explanation = f"Invoice {invoice_id} not found"

    # ── approve_itc / reject_itc ────────────────────────────────────────────
    elif action_type in ("approve_itc", "reject_itc") and invoice_id:
        inv = invoices_map.get(invoice_id)
        if inv:
            is_eligible = inv.get("true_itc_eligible", True)
            true_section = inv.get("true_itc_section")
            agent_decision = "approve" if action_type == "approve_itc" else "reject"
            correct = (
                (agent_decision == "approve" and is_eligible) or
                (agent_decision == "reject" and not is_eligible)
            )
            if correct:
                reward += 0.10
                breakdown["correct_itc_decision"] = 0.10
                if agent_decision == "reject":
                    agent_section = action.get("legal_section", "")
                    if agent_section and agent_section == true_section:
                        reward += 0.05
                        breakdown["correct_legal_section"] = 0.05
                        explanation = f"Correct rejection with right legal basis: {agent_section}"
                    else:
                        explanation = (
                            f"Correct rejection but wrong/missing legal section "
                            f"(expected {true_section})"
                        )
                else:
                    explanation = f"Correctly approved ITC for {invoice_id}"
            else:
                reward -= 0.10
                breakdown["wrong_itc_decision"] = -0.10
                explanation = (
                    f"Wrong ITC decision: said {agent_decision}, "
                    f"should be {'approve' if is_eligible else 'reject'}"
                )

    # ── correct_value (reconciliation) ──────────────────────────────────────
    elif action_type == "correct_value" and invoice_id:
        inv = invoices_map.get(invoice_id)
        if inv and inv.get("has_reconciliation_mismatch"):
            field = action.get("field_name", "taxable_value")
            corrected = action.get("corrected_value", 0)
            correct_val = inv.get(f"correct_{field}", inv.get(f"portal_{field}"))
            if correct_val is not None and abs(corrected - correct_val) <= 50:
                reward += 0.15
                breakdown["correct_reconciliation"] = 0.15
                explanation = f"Correctly reconciled {field} for {invoice_id}"
            else:
                reward -= 0.05
                breakdown["wrong_reconciliation"] = -0.05
                explanation = f"Wrong correction: {corrected} vs expected {correct_val}"
        elif inv and not inv.get("has_reconciliation_mismatch"):
            reward -= 0.05
            breakdown["unnecessary_correction"] = -0.05
            explanation = f"No mismatch on {invoice_id}, correction unnecessary"

    # ── file_return ─────────────────────────────────────────────────────────
    elif action_type == "file_return":
        completeness = result.get("completeness_ratio", 0.0)
        reward += completeness * 0.20
        breakdown["filing_reward"] = round(completeness * 0.20, 3)
        explanation = f"Filed return with {completeness:.0%} completeness"

    # ── no-op / repeated actions ────────────────────────────────────────────
    elif action_type == "request_info":
        reward -= 0.02  # mild penalty for stalling
        explanation = "Requested info — minor delay penalty"

    # ── step efficiency penalty (after 80% of steps used) ──────────────────
    step = state.get("step", 0)
    max_steps = state.get("max_steps", 10)
    if step > max_steps * 0.8:
        reward -= 0.02
        breakdown["efficiency_penalty"] = -0.02

    return {
        "value": round(max(-0.5, min(0.5, reward)), 4),
        "breakdown": breakdown,
        "explanation": explanation,
    }
