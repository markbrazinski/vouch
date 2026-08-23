"""Part C — the strongest reasonable deterministic baseline.

What a competent engineer would build without an LLM, given the same structured
facts: alias maps, effective dates, revision rules, equivalence records,
qualification flags, deviations, adjudication policies, numeric comparisons.

Deliberately NOT weakened. It abstains only where the STRUCTURED facts genuinely
underdetermine the answer — which is exactly the boundary the strip test probes.

No LLM is used here.
"""

from __future__ import annotations

from .adversarial import Case


def _num(d: dict, *keys):
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def decide(case: Case) -> tuple[str, str]:
    """Return (disposition, rationale) from structured facts alone."""
    s = case.structured

    # ---- identity resolution ------------------------------------------
    if "supplier_name" in s:
        alias = (s.get("alias_map") or {}).get(s["supplier_name"])
        if alias and alias == s.get("po_material"):
            pass  # identity resolves; fall through to property checks
        elif s["supplier_name"] in (s.get("distinct_grades") or []):
            return "QUARANTINE", f"{s['supplier_name']} is a distinct grade, not an alias"
        elif s.get("supplier_claims_rename"):
            return "ABSTAIN", "supplier asserts a rename with no controlled alias record"
        elif not alias:
            return "QUARANTINE", f"no alias record maps {s['supplier_name']} to the PO material"

    if {"po_material", "coa_material", "receiving_material"} <= s.keys():
        vals = {s["po_material"], s["coa_material"], s["receiving_material"]}
        if len(vals) > 1:
            return "ABSTAIN", "PO, CoA and receiving record disagree on material identity"

    # ---- supplier qualification ---------------------------------------
    if s.get("qualified_for") is not None and s.get("lot_material"):
        if s["lot_material"] not in s["qualified_for"]:
            return "QUARANTINE", f"supplier not qualified for {s['lot_material']}"

    if s.get("qualified_sites") is not None and s.get("lot_site"):
        if s["lot_site"] not in s["qualified_sites"]:
            return "QUARANTINE", f"manufacturing site {s['lot_site']} is outside qualification scope"

    if s.get("qual_expiry") and s.get("received"):
        if s["received"] > s["qual_expiry"]:
            dev = s.get("deviation")
            if dev and dev.get("status") == "APPROVED" and dev.get("scope_po") == s.get("lot_po"):
                pass  # deviation covers this PO
            else:
                return "QUARANTINE", "supplier qualification expired at receipt with no covering deviation"

    # ---- conflicting evidence ------------------------------------------
    if s.get("coa_tensile") is not None and s.get("plant_lab_tensile") is not None:
        rule = s.get("adjudication_rule")
        if rule and rule.get("governs") == "plant_lab":
            value, mn = s["plant_lab_tensile"], s.get("rev_c_min")
            if mn is not None and value < mn:
                return "QUARANTINE", f"policy {rule['id']}: plant lab {value} < {mn}"
            return "RELEASE", f"policy {rule['id']}: plant lab {value} meets {mn}"
        return "ABSTAIN", "conflicting results with no adjudication rule on record"

    if s.get("coa_site") and s.get("mill_cert_site") and s["coa_site"] != s["mill_cert_site"]:
        return "ABSTAIN", "certificate and mill certificate disagree on manufacturing site"

    # ---- governing revision --------------------------------------------
    gov_min = None
    if s.get("rev_c_effective"):
        basis = s.get("rev_c_basis")
        if basis == "date_of_manufacture" and s.get("manufactured"):
            gov_min = s["rev_c_min"] if s["manufactured"] >= s["rev_c_effective"] else s["rev_b_min"]
        elif basis is None and s.get("manufactured") and s.get("received"):
            # straddles the boundary and the basis is unstated
            if s["manufactured"] < s["rev_c_effective"] <= s["received"]:
                return "ABSTAIN", "effective-date basis unstated and the lot straddles the boundary"
            gov_min = s["rev_c_min"]
        elif s.get("received"):
            gov_min = s["rev_c_min"] if s["received"] >= s["rev_c_effective"] else s["rev_b_min"]

    if s.get("cert_spec_rev") and s.get("known_revs") is not None:
        if s["cert_spec_rev"] not in s["known_revs"]:
            return "ABSTAIN", f"certificate cites unknown revision {s['cert_spec_rev']}"

    if s.get("cert_rev") and s.get("governing_rev") and s["cert_rev"] != s["governing_rev"]:
        return "ABSTAIN", f"certified to rev {s['cert_rev']} but rev {s['governing_rev']} governs"

    # ---- completeness ---------------------------------------------------
    if s.get("required") and s.get("reported"):
        missing = set(s["required"]) - set(s["reported"])
        if missing:
            return "ABSTAIN", f"required characteristic(s) not reported: {sorted(missing)}"

    if s.get("referenced_doc"):
        added = set(s["referenced_doc"].get("adds", []))
        if added - set(s.get("reported", [])):
            return "ABSTAIN", f"{s['referenced_doc']['id']} adds unreported requirements"

    # ---- method equivalence ---------------------------------------------
    if s.get("required_method") and s.get("used_method") and s["required_method"] != s["used_method"]:
        eq = s.get("equivalence")
        if not eq or eq.get("status") != "APPROVED":
            return "ABSTAIN", "test method differs with no approved equivalence in force"
        if eq.get("conditions") == "room_temperature_only" and s.get("test_temp") not in (None, "25C", "room_temp"):
            return "ABSTAIN", f"equivalence is scoped to room temperature; test ran at {s.get('test_temp')}"

    # ---- test condition --------------------------------------------------
    req_c, used_c = s.get("required_condition"), s.get("used_condition")
    if req_c and used_c and req_c != used_c:
        if req_c == "23C+/-2" and used_c.endswith("C"):
            try:
                t = float(used_c.rstrip("C"))
                if not (21.0 <= t <= 25.0):
                    return "ABSTAIN", f"test at {used_c} is outside the permitted 23C +/- 2C window"
            except ValueError:
                return "ABSTAIN", "test condition cannot be parsed"
        elif s.get("correlation", {}) and (s.get("correlation") or {}).get("status") == "APPROVED":
            corrected = (s.get("correlation") or {}).get("corrected_value_cp")
            lo, hi = (s.get("limits_cp") or [None, None])
            if corrected is not None and lo is not None:
                ok = lo <= corrected <= hi
                return ("RELEASE" if ok else "QUARANTINE",
                        f"approved correlation gives {corrected} cP against [{lo}, {hi}]")
        else:
            return "ABSTAIN", f"condition {used_c} differs from required {req_c} with no correlation"

    # ---- numeric limits ---------------------------------------------------
    tensile = _num(s, "tensile_mpa")
    if tensile is not None:
        mn = gov_min if gov_min is not None else s.get("rev_c_min")
        if mn is not None:
            return (("RELEASE", f"tensile {tensile} meets minimum {mn}") if tensile >= mn
                    else ("QUARANTINE", f"tensile {tensile} below minimum {mn}"))

    visc = _num(s, "viscosity_cp")
    if visc is not None and s.get("limits_cp"):
        lo, hi = s["limits_cp"]
        return (("RELEASE", f"viscosity {visc} within [{lo}, {hi}]") if lo <= visc <= hi
                else ("QUARANTINE", f"viscosity {visc} outside [{lo}, {hi}]"))

    hard = _num(s, "hardness_hrc")
    if hard is not None and s.get("limits_hrc"):
        lo, hi = s["limits_hrc"]
        return (("RELEASE", f"hardness {hard} within [{lo}, {hi}]") if lo <= hard <= hi
                else ("QUARANTINE", f"hardness {hard} outside [{lo}, {hi}]"))

    return "ABSTAIN", "structured facts do not determine a disposition"


def run_all(cases: list[Case]) -> list[dict]:
    out = []
    for c in cases:
        disposition, rationale = decide(c)
        out.append({
            "case_id": c.case_id, "truth": c.truth, "predicted": disposition,
            "correct": disposition == c.truth, "rationale": rationale,
            "rule_solvable": c.rule_solvable, "family": c.family,
        })
    return out
