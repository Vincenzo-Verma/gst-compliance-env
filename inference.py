"""
GST Compliance OpenEnv — Baseline Inference Script

Runs an LLM agent against all 3 tasks and produces reproducible baseline scores.
Uses OpenAI client with structured JSON output.

Required environment variables:
    API_BASE_URL   — LLM API endpoint (default: https://api.openai.com/v1)
    MODEL_NAME     — Model identifier (default: gpt-4o-mini)
    HF_TOKEN       — API key

Usage:
    HF_TOKEN=sk-... MODEL_NAME=gpt-4o-mini python inference.py
"""

import os
import sys
import json
import asyncio
import httpx
from typing import List, Dict, Any, Optional
from openai import OpenAI

# ── Configuration ────────────────────────────────────────────────────────────

API_BASE_URL: str = os.environ.get("API_BASE_URL", "https://api.openai.com/v1")
API_KEY: str      = os.environ.get("HF_TOKEN", "")
MODEL_NAME: str   = os.environ.get("MODEL_NAME", "gpt-4o-mini")

ENV_BASE_URL: str = os.environ.get("ENV_BASE_URL", "http://localhost:7860")
BENCHMARK: str    = "gst-compliance-env"

TASKS = [
    {
        "id": "invoice_validation_easy",
        "max_steps": 10,
        "max_total_reward": 3.0,    # 2 errors * 0.15 + file_return bonus
        "success_threshold": 0.5,
    },
    {
        "id": "gstr1_reconciliation_medium",
        "max_steps": 20,
        "max_total_reward": 5.0,
        "success_threshold": 0.45,
    },
    {
        "id": "itc_audit_hard",
        "max_steps": 30,
        "max_total_reward": 8.0,
        "success_threshold": 0.40,
    },
]

# ── Logging — EXACT FORMAT REQUIRED ─────────────────────────────────────────
# Each line: [TAG] followed by a JSON payload.
# Evaluator parses lines starting with [START], [STEP], [END].

def log_start(task: str, env: str, model: str) -> None:
    payload = json.dumps({"task": task, "env": env, "model": model})
    print(f"[START] {payload}", flush=True)


def log_step(step: int, action: str, reward: float,
             done: bool, error: Optional[str]) -> None:
    payload = json.dumps({
        "step": step,
        "action": action,
        "reward": reward,
        "done": done,
        "error": error,
    })
    print(f"[STEP] {payload}", flush=True)


def log_end(success: bool, steps: int, score: float,
            rewards: List[float]) -> None:
    payload = json.dumps({
        "success": success,
        "steps": steps,
        "score": score,
        "rewards": rewards,
    })
    print(f"[END] {payload}", flush=True)


# ── System Prompts per Task ───────────────────────────────────────────────────

SYSTEM_PROMPTS = {
    "invoice_validation_easy": """You are a GST compliance expert reviewing Indian tax invoices.
Your job: find ALL errors in the provided invoices.

Valid GST rates in India: 0%, 5%, 12%, 18%, 28% — any other rate is invalid.
GSTIN must be 15 characters: 2-digit state code + 10-char PAN + 1 entity + Z + check digit.
Tax calculation: igst (or cgst+sgst) must equal taxable_value * gst_rate / 100 (±₹1 tolerance).

Available actions (respond ONLY with valid JSON):
- Flag an error: {"action_type": "flag_error", "invoice_id": "INV-XXX", "error_type": "invalid_gstin_supplier|invalid_gstin_buyer|missing_field|invalid_gst_rate|tax_calculation_mismatch", "reasoning": "brief reason"}
- File return when done: {"action_type": "file_return", "reasoning": "all errors found"}

Respond ONLY with a single JSON object. No explanation outside JSON.""",

    "gstr1_reconciliation_medium": """You are a GST return reconciliation specialist.
Your job: find invoices where the business's sales register differs from the GSTR-1 portal data.

Each invoice shows both register values (taxable_value, igst) and portal values (portal_taxable_value, portal_igst).
If portal_taxable_value != taxable_value: there is a mismatch. Correct to the portal (government) value.

Available actions (respond ONLY with valid JSON):
- Correct a value: {"action_type": "correct_value", "invoice_id": "INV-XXX", "field_name": "taxable_value", "corrected_value": 12345.67, "reasoning": "brief reason"}
- File return when done: {"action_type": "file_return", "reasoning": "all mismatches corrected"}

Respond ONLY with a single JSON object.""",

    "itc_audit_hard": """You are an ITC (Input Tax Credit) audit specialist under the CGST Act.
Your job: audit each invoice's ITC claim. Approve valid claims, reject invalid ones.

ITC is BLOCKED (Section 17(5)) for: personal_vehicle, food_beverage, club_membership, health_club, life_insurance_personal.
ITC is invalid if: supplier_filing_status is "non_filer" (use legal_section: "supplier_non_filer")
ITC is invalid if: supplier GSTIN is malformed (use legal_section: "supplier_gstin_invalid")

Available actions (respond ONLY with valid JSON):
- Approve: {"action_type": "approve_itc", "invoice_id": "INV-XXX", "reasoning": "eligible ITC"}
- Reject: {"action_type": "reject_itc", "invoice_id": "INV-XXX", "legal_section": "section_17_5_motor_vehicle|section_17_5_food_beverage|section_17_5_personal_use|supplier_non_filer|supplier_gstin_invalid", "reasoning": "brief reason"}
- File when done: {"action_type": "file_return", "reasoning": "audit complete"}

Respond ONLY with a single JSON object.""",
}


# ── Model Interaction ─────────────────────────────────────────────────────────

def get_model_action(
    client: OpenAI,
    task_id: str,
    observation: Dict[str, Any],
    history: List[str],
    step: int,
) -> Dict[str, Any]:
    """Call the LLM to get the next action."""
    system_prompt = SYSTEM_PROMPTS.get(task_id, SYSTEM_PROMPTS["invoice_validation_easy"])

    # Build user message with current observation
    # Only show last 5 history items to stay within context
    recent_history = history[-5:] if len(history) > 5 else history
    user_msg = (
        f"Step {step} | Steps remaining: {observation.get('steps_remaining', '?')}\n\n"
        f"Current state:\n{json.dumps(observation, indent=2)}\n\n"
        f"Recent history:\n{chr(10).join(recent_history) if recent_history else 'None'}\n\n"
        f"What is your next action? Respond with a single JSON object only."
    )

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=300,
            temperature=0.1,  # Low temp for deterministic, rule-based decisions
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[DEBUG] JSON parse error: {e}", flush=True)
        return {"action_type": "file_return", "reasoning": "fallback: json parse error"}
    except Exception as e:
        print(f"[DEBUG] Model request failed: {e}", flush=True)
        return {"action_type": "file_return", "reasoning": f"fallback: {str(e)[:50]}"}


# ── Task Runner ───────────────────────────────────────────────────────────────

async def run_task(
    task_cfg: Dict[str, Any],
    client: OpenAI,
) -> float:
    """Run a single task episode and return normalized score."""
    task_id = task_cfg["id"]
    max_steps = task_cfg["max_steps"]
    max_total_reward = task_cfg["max_total_reward"]
    success_threshold = task_cfg["success_threshold"]

    log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

    rewards: List[float] = []
    history: List[str] = []
    steps_taken = 0
    score = 0.0
    observation: Dict[str, Any] = {}

    async with httpx.AsyncClient(timeout=30.0) as http:
        # ── Reset episode ────────────────────────────────────────────────
        try:
            resp = await http.post(
                f"{ENV_BASE_URL}/reset",
                params={"task_id": task_id}
            )
            resp.raise_for_status()
            reset_data = resp.json()
            observation = reset_data.get("observation", {})
        except Exception as e:
            _EPS = 1e-6
            print(f"[DEBUG] Reset failed: {e}", flush=True)
            log_end(success=False, steps=0, score=_EPS, rewards=[])
            return _EPS

        # ── Run steps ────────────────────────────────────────────────────
        for step in range(1, max_steps + 1):
            if observation.get("done"):
                break

            # Get action from model
            action = get_model_action(client, task_id, observation, history, step)

            # Execute action
            error_msg = None
            try:
                resp = await http.post(f"{ENV_BASE_URL}/step", json=action)
                resp.raise_for_status()
                result = resp.json()
                reward = float(result.get("reward", 0.0))
                done = bool(result.get("done", False))
                observation = result.get("observation", {})
            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP {e.response.status_code}"
                reward = -0.05
                done = False
                print(f"[DEBUG] Step error: {error_msg}", flush=True)
            except Exception as e:
                error_msg = str(e)[:100]
                reward = -0.05
                done = False
                print(f"[DEBUG] Step exception: {e}", flush=True)

            rewards.append(reward)
            steps_taken = step
            action_summary = f"{action.get('action_type')} {action.get('invoice_id', '')}"
            history.append(f"Step {step}: {action_summary} → reward {reward:+.3f}")

            log_step(
                step=step,
                action=action_summary.strip(),
                reward=reward,
                done=done,
                error=error_msg,
            )

            if done:
                break

    # ── Compute final score ──────────────────────────────────────────────
    _EPS = 1e-6
    total_reward = sum(rewards)
    score = total_reward / max_total_reward if max_total_reward > 0 else _EPS
    score = min(max(score, _EPS), 1.0 - _EPS)
    success = score >= success_threshold

    log_end(success=success, steps=steps_taken, score=score, rewards=rewards)
    return score


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    if not API_KEY:
        print("[ERROR] HF_TOKEN environment variable not set", flush=True)
        sys.exit(1)

    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

    print(f"[DEBUG] Model: {MODEL_NAME}", flush=True)
    print(f"[DEBUG] API Base: {API_BASE_URL}", flush=True)
    print(f"[DEBUG] Environment: {ENV_BASE_URL}", flush=True)
    print(f"[DEBUG] Running {len(TASKS)} tasks...", flush=True)

    all_scores = []
    for task_cfg in TASKS:
        score = await run_task(task_cfg, client)
        all_scores.append(score)
        print(f"[DEBUG] Task '{task_cfg['id']}' score: {score:.3f}", flush=True)

    avg_score = sum(all_scores) / len(all_scores)
    print(f"[DEBUG] ─────────────────────────────────────", flush=True)
    print(f"[DEBUG] Average score across all tasks: {avg_score:.3f}", flush=True)
    for task_cfg, score in zip(TASKS, all_scores):
        print(f"[DEBUG]   {task_cfg['id']}: {score:.3f}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
