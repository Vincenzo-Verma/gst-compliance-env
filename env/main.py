"""
FastAPI application for GST Compliance OpenEnv.
Implements OpenEnv spec: /reset, /step, /state endpoints.
"""
from typing import Any, Dict
from fastapi import FastAPI, HTTPException, Query
import uvicorn

from env.models import GSTAction, GSTObservation, StepResult, ResetResult, InvoiceView
from env.tasks import get_initial_state, TASK_CONFIGS
from env.graders import grade_easy_task, grade_medium_task, grade_hard_task
from env.reward import compute_step_reward
from env.simulator import GSTSimulator

app = FastAPI(
    title="GST Compliance OpenEnv",
    description="OpenEnv environment for Indian GST tax compliance workflows",
    version="1.0.0",
)

sim = GSTSimulator()

_episode_state: Dict[str, Any] = {}  # In-memory single episode state


def invoices_to_view(invoices: list) -> list:
    """Convert raw invoice dicts to InvoiceView objects (strips ground truth fields)."""
    views = []
    for inv in invoices:
        views.append(InvoiceView(
            invoice_id=inv["invoice_id"],
            invoice_date=inv.get("invoice_date", ""),
            gstin_supplier=inv.get("gstin_supplier", ""),
            gstin_buyer=inv.get("gstin_buyer", ""),
            taxable_value=inv.get("taxable_value", 0.0),
            gst_rate=inv.get("gst_rate", 0.0),
            igst=inv.get("igst", 0.0),
            cgst=inv.get("cgst", 0.0),
            sgst=inv.get("sgst", 0.0),
            category=inv.get("category", ""),
            supplier_filing_status=inv.get("supplier_filing_status", "filer"),
            portal_taxable_value=inv.get("portal_taxable_value"),
            portal_igst=inv.get("portal_igst"),
        ))
    return views


def build_observation(state: Dict[str, Any], message: str = "") -> GSTObservation:
    steps_remaining = state["max_steps"] - state["step"]
    return GSTObservation(
        task_id=state["task_id"],
        step_number=state["step"],
        phase=state["phase"],
        invoices=invoices_to_view(state["invoices"]),
        flags=state["flags"],
        corrections=state["corrections"],
        itc_decisions=state["itc_decisions"],
        itc_running_total=state["itc_running_total"],
        message=message,
        done=state["done"],
        steps_remaining=max(0, steps_remaining),
    )


def compute_completeness(state: Dict[str, Any]) -> float:
    """Compute how complete the agent's work is before filing."""
    task_id = state["task_id"]
    invoices = state["invoices"]

    if task_id == "invoice_validation_easy":
        error_invoices = [i for i in invoices if i.get("injected_errors")]
        if not error_invoices:
            return 1.0
        flagged = sum(1 for inv in error_invoices if inv["invoice_id"] in state["flags"])
        return flagged / len(error_invoices)

    elif task_id == "gstr1_reconciliation_medium":
        mismatch_invoices = [i for i in invoices if i.get("has_reconciliation_mismatch")]
        if not mismatch_invoices:
            return 1.0
        corrected = sum(
            1 for inv in mismatch_invoices if inv["invoice_id"] in state["corrections"]
        )
        return corrected / len(mismatch_invoices)

    elif task_id == "itc_audit_hard":
        total = len(invoices)
        decided = len(state["itc_decisions"])
        return decided / total if total > 0 else 1.0

    return 0.0


@app.post("/reset", response_model=ResetResult)
async def reset(task_id: str = Query(default="invoice_validation_easy")):
    """Reset the environment and return initial observation."""
    global _episode_state
    if task_id not in TASK_CONFIGS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task_id '{task_id}'. Valid: {list(TASK_CONFIGS)}"
        )
    _episode_state = get_initial_state(task_id)
    obs = build_observation(
        _episode_state,
        message=(
            f"Task started: {TASK_CONFIGS[task_id]['description']} "
            f"You have {_episode_state['max_steps']} steps."
        )
    )
    return ResetResult(observation=obs, info={"task_id": task_id})


@app.post("/step", response_model=StepResult)
async def step(action: GSTAction):
    """Process agent action and return observation + reward."""
    global _episode_state

    if not _episode_state:
        raise HTTPException(status_code=400, detail="Call /reset first")
    if _episode_state.get("done"):
        raise HTTPException(status_code=400, detail="Episode done — call /reset")

    _episode_state["step"] += 1
    action_dict = action.model_dump()

    # ── Apply action to state ──────────────────────────────────────────────
    invoice_id = action.invoice_id
    invoices_map = {inv["invoice_id"]: inv for inv in _episode_state["invoices"]}

    completeness_ratio = 0.0
    message = ""

    if action.action_type == "flag_error" and invoice_id:
        if invoice_id not in _episode_state["flags"]:
            _episode_state["flags"][invoice_id] = []
        if action.error_type and action.error_type not in _episode_state["flags"][invoice_id]:
            _episode_state["flags"][invoice_id].append(action.error_type)
        message = f"Flagged {action.error_type} on {invoice_id}"

    elif action.action_type == "clear_flag" and invoice_id:
        if invoice_id in _episode_state["flags"]:
            if action.error_type in _episode_state["flags"][invoice_id]:
                _episode_state["flags"][invoice_id].remove(action.error_type)
        message = f"Cleared flag {action.error_type} on {invoice_id}"

    elif action.action_type == "approve_itc" and invoice_id:
        inv = invoices_map.get(invoice_id)
        if inv:
            amount = inv.get("igst", 0) or (inv.get("cgst", 0) + inv.get("sgst", 0))
            _episode_state["itc_decisions"][invoice_id] = {
                "decision": "approve",
                "legal_section": None,
                "amount": round(amount, 2),
            }
            _episode_state["itc_running_total"] += round(amount, 2)
        message = f"Approved ITC for {invoice_id}"

    elif action.action_type == "reject_itc" and invoice_id:
        _episode_state["itc_decisions"][invoice_id] = {
            "decision": "reject",
            "legal_section": action.legal_section,
            "amount": 0.0,
        }
        message = f"Rejected ITC for {invoice_id} under {action.legal_section}"

    elif action.action_type == "correct_value" and invoice_id:
        if invoice_id not in _episode_state["corrections"]:
            _episode_state["corrections"][invoice_id] = {}
        if action.field_name and action.corrected_value is not None:
            _episode_state["corrections"][invoice_id][action.field_name] = action.corrected_value
        message = f"Corrected {action.field_name}={action.corrected_value} on {invoice_id}"

    elif action.action_type == "validate_invoice" and invoice_id:
        # Informational action — run validation and report results in message
        inv = invoices_map.get(invoice_id)
        if inv:
            errors = sim.validate_invoice(inv)
            if errors:
                message = f"Validation found {len(errors)} error(s) on {invoice_id}"
            else:
                message = f"Invoice {invoice_id} is valid"
        else:
            message = f"Invoice {invoice_id} not found"

    elif action.action_type == "file_return":
        completeness_ratio = compute_completeness(_episode_state)
        _episode_state["done"] = True
        message = f"Return filed. Completeness: {completeness_ratio:.0%}"

    # ── Compute reward ─────────────────────────────────────────────────────
    reward_result = compute_step_reward(
        action_dict,
        _episode_state,
        {"completeness_ratio": completeness_ratio}
    )
    step_reward = reward_result["value"]
    _episode_state["total_reward"] += step_reward
    _episode_state["reward_history"].append(step_reward)

    # ── Check episode termination ──────────────────────────────────────────
    if _episode_state["step"] >= _episode_state["max_steps"]:
        _episode_state["done"] = True
        message += " | Max steps reached."

    obs = build_observation(_episode_state, message=message)

    return StepResult(
        observation=obs,
        reward=step_reward,
        done=_episode_state["done"],
        info={
            "step": _episode_state["step"],
            "total_reward": round(_episode_state["total_reward"], 4),
            "reward_breakdown": reward_result["breakdown"],
            "reward_explanation": reward_result["explanation"],
        }
    )


@app.get("/state")
async def state():
    """Return current internal state (for debugging/evaluation)."""
    if not _episode_state:
        return {"status": "no_episode", "message": "Call /reset to start"}
    # Return state without ground truth labels
    safe_state = {k: v for k, v in _episode_state.items()
                  if k not in ("task_config",)}
    return safe_state


@app.get("/tasks")
async def list_tasks():
    """List all available tasks."""
    return {
        "tasks": [
            {
                "id": cfg["id"],
                "name": cfg["name"],
                "difficulty": cfg["difficulty"],
                "max_steps": cfg["max_steps"],
                "description": cfg["description"],
            }
            for cfg in TASK_CONFIGS.values()
        ]
    }


@app.get("/")
async def root():
    """Root endpoint — satisfies HF Spaces container health probe."""
    return {
        "env": "gst-compliance-env",
        "version": "1.0.0",
        "status": "ok",
        "endpoints": ["/reset", "/step", "/state", "/tasks", "/health", "/docs"],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "env": "gst-compliance-env", "version": "1.0.0"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
