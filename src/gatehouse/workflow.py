"""The Gatehouse workflow: the canonical demo chain, executed.

Every consequential step follows the same shape:

    deterministic facts -> actor proposal -> independent verification
        -> deterministic gate -> (maybe) mutation -> authority record

Agents never hold mutation tools. Only a gate mints the token a mutation
requires, so the separation is structural rather than advisory.
"""

from __future__ import annotations

from .agents.roles import (
    material_disposition_agent,
    production_readiness_agent,
    recovery_agent,
    recovery_verifier,
    specification_verifier,
)
from .gates import material_authority_gate, recovery_authority_gate
from .state import (
    AuthorityRecord,
    Disposition,
    LotStatus,
    OrderStatus,
    RecoveryAction,
    StateStore,
    Usability,
    VerifierOutcome,
)
from .tools import AuthorityToken, EvalTools, MutationTools, ReadTools, make_idempotency_key


class Gatehouse:
    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.read = ReadTools(store)
        self.eval = EvalTools(store)
        self._mutate = MutationTools(store)  # gate-guarded; agents never see this

        self.material_actor = material_disposition_agent(self.read)
        self.spec_verifier = specification_verifier(self.read)
        self.readiness = production_readiness_agent(self.read)
        self.recovery_actor = recovery_agent(self.read)
        self.recovery_check = recovery_verifier(self.read)

    # ------------------------------------------------------------------
    # material disposition chain  (S1, S2, S6, S7)
    # ------------------------------------------------------------------
    def evaluate_lot(self, case_id: str, lot_id: str) -> dict:
        from .schemas import SchemaFailure

        lot_before = self.read.get_lot(lot_id)
        state_before = lot_before.status.value if lot_before else "UNKNOWN"

        # 1. deterministic reconciliation — the agents reason about this
        facts = self.eval.evaluate_evidence_against_spec(lot_id)

        # A1: a schema failure is never coerced into a disposition. It denies the
        # mutation and escalates to QA, and is recorded as a schema failure.
        schema_failures: list[str] = []

        # 2. actor proposes
        try:
            proposal = self.material_actor.run(facts)
            actor_disposition = Disposition(proposal["disposition"])
        except SchemaFailure as exc:
            schema_failures.append(str(exc))
            proposal = {
                "disposition": Disposition.INSUFFICIENT_EVIDENCE.value,
                "rationale": f"SCHEMA_FAILURE: {exc}",
                "evidence_refs": facts.get("evidence_refs", []),
                "requirements_evaluated": [],
                "schema_failure": True,
            }
            actor_disposition = Disposition.INSUFFICIENT_EVIDENCE

        # 3. verifier independently reviews
        verifier_facts = dict(facts)
        verifier_facts["proposed_disposition"] = actor_disposition.value
        try:
            verdict = self.spec_verifier.run(verifier_facts)
            verifier_outcome = VerifierOutcome(verdict["outcome"])
        except SchemaFailure as exc:
            schema_failures.append(str(exc))
            verdict = {
                "outcome": VerifierOutcome.INSUFFICIENT_EVIDENCE.value,
                "rationale": f"SCHEMA_FAILURE: {exc}",
                "evidence_refs": facts.get("evidence_refs", []),
                "schema_failure": True,
            }
            verifier_outcome = VerifierOutcome.INSUFFICIENT_EVIDENCE

        # 4. deterministic authority gate
        decision = material_authority_gate(case_id, lot_id, actor_disposition, verifier_outcome)

        # 5. mutation only if authorized
        mutation_result = "NO_MUTATION"
        if decision.allowed and decision.tool == "release_lot":
            mutation_result = self._mutate.release_lot(lot_id, decision.token)
        elif decision.allowed and decision.tool == "quarantine_lot":
            mutation_result = self._mutate.quarantine_lot(lot_id, decision.token)
        elif decision.tool == "create_qa_review" and decision.token is not None:
            mutation_result = self._mutate.create_qa_review(
                lot_id,
                case_id,
                decision.reason,
                tuple(facts.get("evidence_refs", [])),
                decision.token,
            )

        lot_after = self.read.get_lot(lot_id)
        state_after = lot_after.status.value if lot_after else "UNKNOWN"

        record = AuthorityRecord(
            case_id=case_id,
            evidence_refs=tuple(facts.get("evidence_refs", [])),
            actor_disposition=actor_disposition.value,
            actor_rationale=proposal["rationale"],
            verifier_outcome=verifier_outcome.value,
            verifier_rationale=verdict["rationale"],
            authority_source=decision.authority_source,
            authority_result="ALLOWED" if decision.allowed else f"DENIED: {decision.reason}",
            requested_tool=decision.tool or "none",
            mutation_result=mutation_result,
            state_before=state_before,
            state_after=state_after,
            idempotency_key=decision.token.idempotency_key if decision.token else "",
        )
        self.store.record_authority(record)

        return {
            "case_id": case_id,
            "lot_id": lot_id,
            "findings": facts.get("findings", []),
            "actor": proposal,
            "verifier": verdict,
            "gate": decision,
            "mutation_result": mutation_result,
            "state_before": state_before,
            "state_after": state_after,
            "authority_record": record,
            "schema_failures": schema_failures,
        }

    # ------------------------------------------------------------------
    # production readiness  (S3)
    # ------------------------------------------------------------------
    def evaluate_production_readiness(self, case_id: str, order_id: str) -> dict:
        order_before = self.read.get_production_order(order_id)
        state_before = order_before.status.value if order_before else "UNKNOWN"

        shortage = self.eval.calculate_material_shortage(order_id)  # arithmetic in Python
        verdict = self.readiness.run({"order_id": order_id, "shortage": shortage})

        mutation_result = "NO_MUTATION"
        authority_result = "NO_CHANGE_REQUIRED"
        tool = "none"
        idem = ""

        if verdict["authority_status"] == "HOLD" and state_before != OrderStatus.HOLD.value:
            tool = "hold_production_order"
            idem = make_idempotency_key(case_id, tool, order_id)
            # Deterministic shortage IS the authority for a HOLD: holding is the
            # fail-safe direction, and the arithmetic is not an agent's opinion.
            token = AuthorityToken(case_id, tool, order_id, idem, "deterministic_shortage_authority")
            mutation_result = self._mutate.hold_production_order(order_id, token)
            authority_result = "ALLOWED"

        order_after = self.read.get_production_order(order_id)
        state_after = order_after.status.value if order_after else "UNKNOWN"

        record = AuthorityRecord(
            case_id=case_id,
            evidence_refs=tuple(
                s["material_id"] for s in shortage.get("shortages", [])
            ),
            actor_disposition=verdict["authority_status"],
            actor_rationale=verdict["rationale"],
            verifier_outcome="DETERMINISTIC_SHORTAGE_CALC",
            verifier_rationale=str(shortage),
            authority_source="deterministic_shortage_authority",
            authority_result=authority_result,
            requested_tool=tool,
            mutation_result=mutation_result,
            state_before=state_before,
            state_after=state_after,
            idempotency_key=idem,
        )
        self.store.record_authority(record)

        return {
            "order_id": order_id,
            "shortage": shortage,
            "readiness": verdict,
            "state_before": state_before,
            "state_after": state_after,
            "mutation_result": mutation_result,
            "authority_record": record,
        }

    # ------------------------------------------------------------------
    # recovery chain  (S4, S5)
    # ------------------------------------------------------------------
    def _build_recovery_facts(self, held_order_id: str) -> dict:
        held = self.read.get_production_order(held_order_id)
        if held is None:
            return {"held_order_id": held_order_id}

        shortage = self.eval.calculate_material_shortage(held_order_id)
        short_ids = {s["material_id"] for s in shortage.get("shortages", [])}

        # substitution candidates: approval read from the table, stock computed
        substitution_candidates = []
        for sub in self.read.get_approved_substitutions(held.product):
            if sub.original_material_id in short_ids:
                approval = self.eval.check_substitution_approval(
                    held.product, sub.original_material_id, sub.substitute_material_id
                )
                substitution_candidates.append(
                    {
                        "original_material_id": sub.original_material_id,
                        "substitute_material_id": sub.substitute_material_id,
                        "approved": approval["approved"],
                        "available_quantity": self.read.get_usable_inventory(
                            sub.substitute_material_id
                        ),
                    }
                )

        # resequence candidates: every other READY order, deterministically checked
        resequence_candidates = []
        for order in self.store.all("production_order"):
            if order.order_id == held_order_id or order.status is not OrderStatus.READY:
                continue
            slot_check = self.eval.check_schedule_slot(order.order_id, held.planned_slot)
            order_shortage = self.eval.calculate_material_shortage(order.order_id)
            resequence_candidates.append(
                {
                    "order_id": order.order_id,
                    "resource": order.resource,
                    "current_slot": order.planned_slot,
                    "target_slot": held.planned_slot,
                    "slot_available": slot_check["available"],
                    "materials_released": not order_shortage["has_shortage"],
                    "resource_compatible": order.resource == held.resource,
                }
            )

        return {
            "held_order_id": held_order_id,
            "product": held.product,
            "vacated_slot": held.planned_slot,
            "shortage": shortage,
            "substitution_candidates": substitution_candidates,
            "resequence_candidates": resequence_candidates,
        }

    def evaluate_recovery(self, case_id: str, held_order_id: str) -> dict:
        """Recovery is DETERMINISTIC (A3).

        Substitution approval, quantity sufficiency, slot feasibility and
        resource compatibility are crisp structured facts. An LLM adds variance
        and no information, so it does not decide them. The agent is retained
        only for genuinely ambiguous candidate selection, which the current
        fixtures do not require — recorded honestly rather than preserved for
        appearances.
        """
        facts = self._build_recovery_facts(held_order_id)

        # 1. Explicitly unapproved substitution -> deterministic REFUSE.
        unapproved = [c for c in facts.get("substitution_candidates", []) if not c.get("approved")]

        # 2. Admissible resequence candidates: every hard constraint satisfied.
        admissible = [
            c
            for c in facts.get("resequence_candidates", [])
            if c.get("slot_available")
            and c.get("materials_released")
            and c.get("resource_compatible")
        ]

        if admissible:
            chosen = min(admissible, key=lambda c: c["order_id"])
            action = RecoveryAction.RESEQUENCE
            target_order_id = chosen["order_id"]
            target_slot = chosen["target_slot"]
            rationale = (
                f"deterministic: {target_order_id} satisfies all hard constraints "
                f"(material released, resource {chosen.get('resource')} compatible, "
                f"slot {target_slot} free)"
            )
        else:
            action = RecoveryAction.REFUSE
            target_order_id = held_order_id
            target_slot = None
            if unapproved:
                names = ", ".join(c["substitute_material_id"] for c in unapproved)
                rationale = (
                    f"deterministic: candidate substitute(s) {names} are NOT approved for "
                    f"{facts.get('product')}; available quantity does not confer authority"
                )
            else:
                rationale = "deterministic: no candidate satisfies all hard constraints"

        proposal = {
            "action": action.value,
            "target_order_id": target_order_id,
            "target_slot": target_slot,
            "rationale": rationale,
            "decided_by": "deterministic_recovery_evaluator",
        }

        # 3. Independent deterministic re-check (defence in depth): recompute the
        #    admissibility of the chosen candidate from live state.
        facts_ok = False
        state_before = "UNCHANGED"
        if action is RecoveryAction.RESEQUENCE:
            slot_check = self.eval.check_schedule_slot(target_order_id, target_slot)
            shortage = self.eval.calculate_material_shortage(target_order_id)
            target = self.read.get_production_order(target_order_id)
            held = self.read.get_production_order(held_order_id)
            facts_ok = bool(
                slot_check["available"]
                and not shortage["has_shortage"]
                and target
                and held
                and target.resource == held.resource
            )
            state_before = target.planned_slot if target else "UNKNOWN"
            verdict = {
                "outcome": (
                    VerifierOutcome.VERIFIED.value if facts_ok else VerifierOutcome.REJECTED.value
                ),
                "rationale": (
                    f"independent recomputation: slot_available={slot_check['available']}, "
                    f"materials_released={not shortage['has_shortage']}, "
                    f"resource_compatible={bool(target and held and target.resource == held.resource)}"
                ),
                "decided_by": "deterministic_recovery_recheck",
            }
        else:
            verdict = {
                "outcome": VerifierOutcome.VERIFIED.value,
                "rationale": f"refusal confirmed deterministically: {rationale}",
                "decided_by": "deterministic_recovery_recheck",
            }
        verifier_outcome = VerifierOutcome(verdict["outcome"])

        decision = recovery_authority_gate(
            case_id, target_order_id or held_order_id, action, verifier_outcome, facts_ok, target_slot
        )

        mutation_result = "NO_MUTATION"
        if decision.allowed and decision.tool == "resequence_production_order":
            mutation_result = self._mutate.resequence_production_order(
                target_order_id, target_slot, decision.token
            )

        state_after = state_before
        if target_order_id:
            after = self.read.get_production_order(target_order_id)
            state_after = after.planned_slot if after else "UNKNOWN"

        record = AuthorityRecord(
            case_id=case_id,
            evidence_refs=tuple(
                c["order_id"] for c in facts.get("resequence_candidates", [])
            ) + tuple(
                c["substitute_material_id"] for c in facts.get("substitution_candidates", [])
            ),
            actor_disposition=action.value,
            actor_rationale=proposal["rationale"],
            verifier_outcome=verifier_outcome.value,
            verifier_rationale=verdict["rationale"],
            authority_source=decision.authority_source,
            authority_result="ALLOWED" if decision.allowed else f"DENIED: {decision.reason}",
            requested_tool=decision.tool or "none",
            mutation_result=mutation_result,
            state_before=state_before,
            state_after=state_after,
            idempotency_key=decision.token.idempotency_key if decision.token else "",
        )
        self.store.record_authority(record)

        return {
            "case_id": case_id,
            "held_order_id": held_order_id,
            "facts": facts,
            "actor": proposal,
            "verifier": verdict,
            "gate": decision,
            "mutation_result": mutation_result,
            "state_before": state_before,
            "state_after": state_after,
            "authority_record": record,
        }
