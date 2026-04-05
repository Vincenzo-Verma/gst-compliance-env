"""
Task definitions and state management for GST compliance tasks.
"""
import json
import copy
from pathlib import Path
from typing import Dict, Any


DATA_PATH = Path(__file__).parent / "data" / "invoices_seed.json"


def load_invoice_data() -> Dict[str, Any]:
    """Load pre-generated invoice data from seed file."""
    if not DATA_PATH.exists():
        # Generate data on-the-fly if seed file missing
        from env.data.generator import generate_all_invoice_sets
        data = generate_all_invoice_sets()
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DATA_PATH, "w") as f:
            json.dump(data, f, indent=2)
        return data
    with open(DATA_PATH) as f:
        return json.load(f)


TASK_CONFIGS = {
    "invoice_validation_easy": {
        "id": "invoice_validation_easy",
        "name": "GST Invoice Validation",
        "difficulty": "easy",
        "max_steps": 10,
        "invoice_set": "easy",
        "description": "Validate 5 GST invoices and flag all errors.",
        "phase": "validation",
    },
    "gstr1_reconciliation_medium": {
        "id": "gstr1_reconciliation_medium",
        "name": "GSTR-1 Reconciliation",
        "difficulty": "medium",
        "max_steps": 20,
        "invoice_set": "medium",
        "description": "Reconcile 15 invoices: find and correct 4 mismatches.",
        "phase": "reconciliation",
    },
    "itc_audit_hard": {
        "id": "itc_audit_hard",
        "name": "ITC Fraud Audit",
        "difficulty": "hard",
        "max_steps": 30,
        "invoice_set": "hard",
        "description": "Audit 20 ITC claims: find 5 fraudulent/blocked claims.",
        "phase": "itc_audit",
    },
}


def get_initial_state(task_id: str) -> Dict[str, Any]:
    """Create fresh episode state for a given task."""
    config = TASK_CONFIGS.get(task_id)
    if not config:
        raise ValueError(f"Unknown task_id: {task_id}. Valid: {list(TASK_CONFIGS)}")

    invoice_data = load_invoice_data()
    invoice_set = invoice_data[config["invoice_set"]]
    # Deep copy to avoid mutation across episodes
    invoices = copy.deepcopy(invoice_set)

    return {
        "task_id": task_id,
        "task_config": config,
        "invoices": invoices,
        "step": 0,
        "max_steps": config["max_steps"],
        "phase": config["phase"],
        # Agent's accumulated actions
        "flags": {},           # {invoice_id: [error_types]}
        "corrections": {},     # {invoice_id: {field: value}}
        "itc_decisions": {},   # {invoice_id: {decision, legal_section, amount}}
        "itc_running_total": 0.0,
        "done": False,
        "total_reward": 0.0,
        "reward_history": [],
    }
