"""
Typed Pydantic models for the GST Compliance OpenEnv environment.
All models use Pydantic v2 syntax.
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field


# ── Action Model ────────────────────────────────────────────────────────────

ActionType = Literal[
    "validate_invoice",
    "flag_error",
    "clear_flag",
    "approve_itc",
    "reject_itc",
    "correct_value",
    "file_return",
    "request_info",
]

ErrorType = Literal[
    "invalid_gstin_supplier",
    "invalid_gstin_buyer",
    "missing_field",
    "invalid_gst_rate",
    "tax_calculation_mismatch",
    "duplicate_invoice",
]

LegalSection = Literal[
    "section_17_5_personal_use",
    "section_17_5_food_beverage",
    "section_17_5_motor_vehicle",
    "supplier_non_filer",
    "supplier_gstin_invalid",
    "itc_reversal_required",
]


class GSTAction(BaseModel):
    """Action taken by the agent in the GST environment."""
    action_type: ActionType = Field(
        ..., description="The type of action to perform"
    )
    invoice_id: Optional[str] = Field(
        None, description="Target invoice ID (e.g. INV-1234)"
    )
    error_type: Optional[ErrorType] = Field(
        None, description="Error type when action_type is flag_error"
    )
    corrected_value: Optional[float] = Field(
        None, description="Corrected numeric value for reconciliation"
    )
    field_name: Optional[str] = Field(
        None, description="Field being corrected in reconciliation task"
    )
    legal_section: Optional[LegalSection] = Field(
        None, description="Legal basis for ITC rejection"
    )
    reasoning: Optional[str] = Field(
        None, max_length=200, description="Agent's brief reasoning"
    )


# ── Observation Model ───────────────────────────────────────────────────────

class InvoiceView(BaseModel):
    """A single invoice as presented to the agent."""
    invoice_id: str
    invoice_date: str
    gstin_supplier: str
    gstin_buyer: str
    taxable_value: float
    gst_rate: float
    igst: float
    cgst: float
    sgst: float
    category: str
    supplier_filing_status: str  # "filer" or "non_filer"
    # For reconciliation task: portal values may differ from register
    portal_taxable_value: Optional[float] = None
    portal_igst: Optional[float] = None


class GSTObservation(BaseModel):
    """Observation returned after each step."""
    task_id: str
    step_number: int
    phase: str = Field(..., description="Current task phase")
    invoices: List[InvoiceView] = Field(default_factory=list)
    flags: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="invoice_id -> list of error flags raised"
    )
    corrections: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description="invoice_id -> {field: corrected_value}"
    )
    itc_decisions: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="invoice_id -> {decision, legal_section, amount}"
    )
    itc_running_total: float = 0.0
    message: str = ""
    done: bool = False
    steps_remaining: int = 0


# ── Reward Model ────────────────────────────────────────────────────────────

class RewardBreakdown(BaseModel):
    """Detailed breakdown of the reward signal."""
    accuracy: float = Field(0.0, ge=0.0, le=1.0)
    completeness: float = Field(0.0, ge=0.0, le=1.0)
    efficiency: float = Field(0.0, ge=0.0, le=1.0)
    legal_reasoning: float = Field(0.0, ge=0.0, le=1.0)
    penalties: float = Field(0.0, le=0.0)


class GSTReward(BaseModel):
    """Reward returned after each step."""
    value: float = Field(..., ge=-1.0, le=1.0, description="Step reward")
    breakdown: RewardBreakdown = Field(default_factory=RewardBreakdown)
    explanation: str = ""


# ── Step Result ─────────────────────────────────────────────────────────────

class StepResult(BaseModel):
    """Full result of a step() call."""
    observation: GSTObservation
    reward: float
    done: bool
    info: Dict[str, Any] = Field(default_factory=dict)


# ── Reset Result ─────────────────────────────────────────────────────────────

class ResetResult(BaseModel):
    """Full result of a reset() call."""
    observation: GSTObservation
    info: Dict[str, Any] = Field(default_factory=dict)
