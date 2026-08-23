"""Part C (honest variant) — deterministic baseline over RAW documents.

`baseline.py` reads pre-structured facts and scores 30/30. That result is not
meaningful on its own: the structuring step already contains the judgment
(scoped equivalence, adjudication policy, incorporation by reference).

A real plant does not receive `{"equivalence": {"conditions": "room_temp_only"}}`.
It receives a PDF. So this baseline gets the ERP-grade structured facts a
conventional system genuinely has — identifiers, dates, numbers, flags — and must
recover everything else from `evidence_text` by pattern matching.

This is the strongest *honest* conventional system, and the gap between it and
baseline.py is the size of the extraction problem.
"""

from __future__ import annotations

import re

from .adversarial import Case

# Facts a conventional ERP/LIMS genuinely holds as structured data.
ERP_KEYS = {
    "po_spec_rev", "master_spec_rev", "received", "manufactured", "rev_c_effective",
    "rev_b_min", "rev_c_min", "rev_a_min", "tensile_mpa", "viscosity_cp", "hardness_hrc",
    "limits_cp", "limits_hrc", "po_material", "coa_material", "receiving_material",
    "supplier", "supplier_name", "lot_material", "lot_po", "qual_expiry", "qualified_for",
    "alias_map", "required_method", "used_method", "required_condition", "used_condition",
    "required", "reported", "cert_spec_rev", "cert_rev", "governing_rev",
    "coa_tensile", "plant_lab_tensile", "test_temp",
}


def erp_facts(case: Case) -> dict:
    return {k: v for k, v in case.structured.items() if k in ERP_KEYS}


def extract(text: str) -> dict:
    """Best-effort deterministic extraction. Regex/keyword only — no LLM.

    Written to succeed on the phrasings actually present, i.e. deliberately
    favourable to the baseline. Where it cannot decide, it reports uncertainty
    rather than guessing.
    """
    t = text.lower()
    out: dict = {}

    # --- effective-date basis -------------------------------------------
    if "manufactured on or after" in t or "date of manufacture" in t and "applies to" in t:
        out["rev_basis"] = "manufacture"
    elif "received on or after" in t or "booked into stores from" in t:
        out["rev_basis"] = "receipt"
    elif "becomes effective" in t or "is in force" in t:
        out["rev_basis"] = "UNSTATED"

    # --- equivalence records --------------------------------------------
    if "equivalent" in t or "equivalence" in t:
        out["equivalence_mentioned"] = True
        out["equivalence_withdrawn"] = "withdrawn" in t
        out["equivalence_room_temp_only"] = bool(
            re.search(r"room temperature testing only|for room temperature", t)
        )
        out["equivalence_approved"] = "approved as equivalent" in t and "withdrawn" not in t

    # --- correlation records --------------------------------------------
    if "correlate" in t or "correlation" in t:
        out["correlation_mentioned"] = True
        out["correlation_approved"] = "approved" in t
        m = re.search(r"equivalent of [\d.]+ cp at [\d]+ ?c is ([\d.]+) cp", t)
        if m:
            out["corrected_value"] = float(m.group(1))

    # --- deviations -------------------------------------------------------
    m = re.search(r"deviation (dev-\d+)[^\]]*\]?[^.]*?(po-\d+)", t)
    if m:
        out["deviation_id"], out["deviation_po"] = m.group(1).upper(), m.group(2).upper()
        out["deviation_approved"] = "approved" in t
    elif "dev-" in t:
        m2 = re.search(r"(dev-\d+)", t)
        m3 = re.search(r"po[- ]?(\d+)", t)
        if m2:
            out["deviation_id"] = m2.group(1).upper()
            if m3:
                out["deviation_po"] = f"PO-{m3.group(1)}"
            out["deviation_approved"] = "signed off" in t or "approved" in t

    # --- adjudication policy ---------------------------------------------
    if "shall govern" in t or "result shall govern" in t:
        out["adjudication_present"] = True
        out["adjudication_governs_plant"] = "laboratory result shall govern" in t or "plant laborator" in t

    # --- incorporation by reference ---------------------------------------
    if "additionally satisfy" in t or "requirements of spec" in t:
        out["incorporates_other_doc"] = True

    # --- site information --------------------------------------------------
    sites = re.findall(r"(hamburg|rotterdam)", t)
    if sites:
        out["sites_mentioned"] = sorted(set(sites))

    # --- rename claim -------------------------------------------------------
    if "new designation" in t or "naming update" in t:
        out["rename_claimed"] = True

    # --- distinct grade note -------------------------------------------------
    if "variant of" in t:
        out["variant_note"] = True

    # --- unknown revision ----------------------------------------------------
    m = re.search(r"revision ([a-z])\b", t)
    if m:
        out["cert_rev_text"] = m.group(1).upper()

    return out


def decide(case: Case) -> tuple[str, str]:
    s = erp_facts(case)
    x = extract(case.evidence_text)

    # ---- identity ------------------------------------------------------
    if "supplier_name" in s:
        alias = (s.get("alias_map") or {}).get(s["supplier_name"])
        if not alias:
            if x.get("rename_claimed"):
                return "ABSTAIN", "supplier asserts a rename; no controlled alias record"
            if x.get("variant_note"):
                return "QUARANTINE", "document describes a distinct variant grade"
            return "QUARANTINE", "no alias record maps the supplied name to the PO material"

    if {"po_material", "coa_material", "receiving_material"} <= s.keys():
        if len({s["po_material"], s["coa_material"], s["receiving_material"]}) > 1:
            return "ABSTAIN", "PO, CoA and receiving record disagree on identity"

    # ---- qualification --------------------------------------------------
    if s.get("qualified_for") is not None and s.get("lot_material"):
        if s["lot_material"] not in s["qualified_for"]:
            return "QUARANTINE", "supplier not qualified for the supplied material"

    if x.get("sites_mentioned") and len(x["sites_mentioned"]) >= 1:
        # A conventional system knows the qualified site list from the vendor master.
        qualified = {"hamburg"}
        mentioned = set(x["sites_mentioned"])
        if len(mentioned) > 1:
            return "ABSTAIN", "document names more than one manufacturing site"
        if mentioned and not (mentioned & qualified):
            return "QUARANTINE", f"manufacturing site {sorted(mentioned)[0]} outside qualification"

    if s.get("qual_expiry") and s.get("received") and s["received"] > s["qual_expiry"]:
        if x.get("deviation_approved") and x.get("deviation_po") == s.get("lot_po"):
            pass
        else:
            return "QUARANTINE", "qualification expired with no covering deviation for this PO"

    # ---- conflicting results ----------------------------------------------
    if s.get("coa_tensile") is not None and s.get("plant_lab_tensile") is not None:
        if x.get("adjudication_governs_plant"):
            v, mn = s["plant_lab_tensile"], s.get("rev_c_min")
            return (("QUARANTINE", f"policy: plant lab {v} < {mn}") if mn and v < mn
                    else ("RELEASE", f"policy: plant lab {v} meets {mn}"))
        return "ABSTAIN", "conflicting results, no adjudication rule recovered"

    # ---- completeness -------------------------------------------------------
    if x.get("incorporates_other_doc"):
        return "ABSTAIN", "document incorporates further requirements by reference"

    if s.get("required") and s.get("reported"):
        if set(s["required"]) - set(s["reported"]):
            return "ABSTAIN", "a required characteristic is not reported"

    if s.get("cert_rev") and s.get("governing_rev") and s["cert_rev"] != s["governing_rev"]:
        return "ABSTAIN", "certified against a non-governing revision"

    if s.get("cert_spec_rev") and s["cert_spec_rev"] not in ("A", "B", "C"):
        return "ABSTAIN", "certificate cites an unknown revision"

    # ---- method equivalence ---------------------------------------------------
    if s.get("required_method") and s.get("used_method") and s["required_method"] != s["used_method"]:
        if not x.get("equivalence_mentioned"):
            return "ABSTAIN", "method differs and no equivalence is present in the document"
        if x.get("equivalence_withdrawn"):
            return "ABSTAIN", "equivalence record is withdrawn"
        if x.get("equivalence_room_temp_only") and s.get("test_temp") not in (None, "25C", "room_temp"):
            return "ABSTAIN", "equivalence scoped to room temperature; test was elevated"
        if not x.get("equivalence_approved"):
            return "ABSTAIN", "equivalence present but approval not established"

    # ---- test condition ---------------------------------------------------------
    req_c, used_c = s.get("required_condition"), s.get("used_condition")
    if req_c and used_c and req_c != used_c:
        if req_c == "23C+/-2":
            try:
                t = float(used_c.rstrip("C"))
                if not (21.0 <= t <= 25.0):
                    return "ABSTAIN", f"{used_c} outside the permitted 23C +/- 2C window"
            except ValueError:
                return "ABSTAIN", "unparseable test condition"
        elif x.get("correlation_approved") and x.get("corrected_value") is not None:
            lo, hi = s.get("limits_cp", [None, None])
            v = x["corrected_value"]
            if lo is not None:
                return (("RELEASE", f"approved correlation gives {v} cP in [{lo}, {hi}]")
                        if lo <= v <= hi else ("QUARANTINE", f"corrected {v} cP outside [{lo}, {hi}]"))
        else:
            return "ABSTAIN", f"condition {used_c} differs from {req_c} with no correlation recovered"

    # ---- governing revision + numeric limits ------------------------------------
    gov_min = None
    if s.get("rev_c_effective"):
        basis = x.get("rev_basis")
        if basis == "UNSTATED" and s.get("manufactured") and s.get("received"):
            if s["manufactured"] < s["rev_c_effective"] <= s["received"]:
                return "ABSTAIN", "effective-date basis not stated and the lot straddles it"
        if basis == "manufacture" and s.get("manufactured"):
            gov_min = s["rev_c_min"] if s["manufactured"] >= s["rev_c_effective"] else s["rev_b_min"]
        elif basis == "receipt" and s.get("received"):
            gov_min = s["rev_c_min"] if s["received"] >= s["rev_c_effective"] else s["rev_b_min"]
        elif s.get("received"):
            gov_min = s["rev_c_min"] if s["received"] >= s["rev_c_effective"] else s["rev_b_min"]

    tensile = s.get("tensile_mpa")
    if tensile is not None:
        mn = gov_min if gov_min is not None else s.get("rev_c_min")
        if mn is not None:
            return (("RELEASE", f"tensile {tensile} >= {mn}") if tensile >= mn
                    else ("QUARANTINE", f"tensile {tensile} < {mn}"))

    visc = s.get("viscosity_cp")
    if visc is not None and s.get("limits_cp"):
        lo, hi = s["limits_cp"]
        return (("RELEASE", f"viscosity {visc} in [{lo}, {hi}]") if lo <= visc <= hi
                else ("QUARANTINE", f"viscosity {visc} outside [{lo}, {hi}]"))

    hard = s.get("hardness_hrc")
    if hard is not None and s.get("limits_hrc"):
        lo, hi = s["limits_hrc"]
        return (("RELEASE", f"hardness {hard} in [{lo}, {hi}]") if lo <= hard <= hi
                else ("QUARANTINE", f"hardness {hard} outside [{lo}, {hi}]"))

    return "ABSTAIN", "facts recovered from the document do not determine a disposition"


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
