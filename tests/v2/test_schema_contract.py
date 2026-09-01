"""Every load-bearing model-written field states its contract IN THE SCHEMA.

The contract a model actually sees is the generated JSON Schema Strands sends
as its structured-output spec. A `#:` comment, a docstring, or a paragraph of
prompt prose reaches the reader of this file and nobody else — so a field whose
meaning lives only there is a field the model is guessing at. Live runs proved
that twice: `method_match` and then `sufficiency` were each misused in
schema-valid ways until their meaning was written into `Field(description=...)`.

These tests pin the surface, not the wording, so the descriptions can be
improved without churn but cannot silently vanish.
"""

from __future__ import annotations

import pytest

from vouch.v2.contracts import EvidenceApplicabilityBrief

SCHEMA = EvidenceApplicabilityBrief.model_json_schema()
DEFS = SCHEMA.get("$defs", {})

#: Fields whose misuse changes a decision or manufactures a disagreement.
#: `investigation_notes` and `precedent_consulted` are deliberately absent:
#: they are non-authoritative and no deterministic step reads them.
LOAD_BEARING = [
    ("EvidenceApplicabilityBrief", "governing_basis"),
    ("EvidenceApplicabilityBrief", "sufficiency"),
    ("EvidenceApplicabilityBrief", "missing"),
    ("EvidenceApplicabilityBrief", "deviations_applied"),
    ("GoverningBasis", "spec_id"),
    ("GoverningBasis", "revision"),
    ("CoverageItem", "test"),
    ("CoverageItem", "evidence_ref"),
    ("CoverageItem", "method_match"),
    ("CoverageItem", "equivalence_record_id"),
    ("MissingItem", "test"),
    ("MissingItem", "reason"),
    ("RequiredTest", "name"),
    ("DeviationRef", "deviation_id"),
]


def _properties(model: str) -> dict:
    if model == "EvidenceApplicabilityBrief":
        return SCHEMA["properties"]
    return DEFS[model]["properties"]


@pytest.mark.parametrize("model,field", LOAD_BEARING)
def test_load_bearing_fields_describe_themselves(model, field):
    schema = _properties(model)[field]
    # A $ref-only property carries its description on the sibling key, which
    # pydantic emits alongside the ref.
    description = schema.get("description", "")
    assert description.strip(), (
        f"{model}.{field} is load-bearing but states no contract in the JSON "
        f"schema, so the model never sees what it means"
    )


def test_sufficiency_schema_separates_coverage_from_conformance():
    """The Hero A defect, pinned. The field must tell the model that a failing
    value is still covered evidence."""
    description = SCHEMA["properties"]["sufficiency"]["description"].lower()
    assert "coverage" in description
    # It must say what to do with an out-of-limit value, since that is the
    # exact confusion that produced false disagreements.
    assert "outside its limit" in description or "failing" in description


def test_the_brief_has_no_disposition_vocabulary():
    """No FIELD or enum value may let the model express an outcome.

    The class docstring does say the words — it exists to tell the model that
    release and quarantine are not its to state — so this checks the writable
    surface, which is what a model can actually fill in.
    """
    assert "disposition" not in EvidenceApplicabilityBrief.model_fields
    writable = {
        *SCHEMA["properties"],
        *(f for d in DEFS.values() for f in d.get("properties", {})),
    }
    for name in writable:
        assert "disposition" not in name.lower()
    for definition in DEFS.values():
        for value in definition.get("enum", []):
            assert value.upper() not in ("RELEASE", "QUARANTINE", "REJECT")


def test_sufficiency_is_a_closed_enum():
    """Free text here would be unvalidatable."""
    enum = DEFS["Sufficiency"]["enum"]
    assert sorted(enum) == ["INSUFFICIENT_EVIDENCE", "SUFFICIENT"]
