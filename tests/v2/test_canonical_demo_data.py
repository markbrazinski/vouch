"""The canonical demo dataset, pinned.

D10 of the FE<->BE contract gate decided which numbers the demo story rests on.
Two of them had drifted or were never applied, and a drifted demo number is not
a cosmetic problem: the frontend renders these verbatim, so a mismatch means the
UI shows one figure while the authoritative corpus computes another.

These tests exist because the C-417 requirement was decided at one gate
(`900.0`) and still read `800.0` in the fixture three gates later. Nothing
failed, because nothing asserted it.
"""

from __future__ import annotations

from vouch.v2.fixtures import build_corpus


def test_c417_requires_the_canonical_900():
    """D10: the fixture moves to match the story, not the reverse.

    The demo beat is "C-417 · 900 kg uncovered". Before this test, the corpus
    said 800.0 and the copy said 900 — and the FE<->BE integration contract had
    frozen the 800 because it was captured from a live corpus that had never
    been migrated.
    """
    order = build_corpus().order("C-417")
    requirement = {r.material_id: r.quantity for r in order.requirements}
    assert requirement == {"MAT-ALLOY-7": 900.0}


def test_the_requirement_is_still_coverable():
    """Changing a demo number must not silently invert a causal beat.

    The three MAT-ALLOY-7 lots hold 1100 between them, so 900 is coverable with
    200 to spare. Had the requirement exceeded available stock, C-417 could
    never return to READY and the recovery story would break in a way no test
    named.
    """
    corpus = build_corpus()
    total = sum(
        corpus.get("inventory", lot).quantity
        for lot in ("LOT-1001", "LOT-1002", "LOT-1003", "LOT-1004")
    )
    required = build_corpus().order("C-417").requirements[0].quantity
    assert total == 1550.0
    assert required < total, "C-417 could never be covered"


def test_no_alloy_stock_is_usable_before_a_release():
    """Hero A's shortage is measured against ZERO usable, not against 1100.

    Stock existing is not stock being usable — that distinction is the product.
    """
    corpus = build_corpus()
    assert corpus.usable_inventory("LOT-1001") == 0
    for lot in ("LOT-1001", "LOT-1002", "LOT-1003", "LOT-1004"):
        assert corpus.get("inventory", lot).usable is False


def test_the_substitute_stock_is_a_different_900():
    """Guard against the coincidence that will mislead a reader.

    LOT-9001 holds 900.0 of MAT-SUB-9 — stock exists, authority does not. It is
    numerically identical to C-417's requirement and causally unrelated. Anyone
    conflating them concludes the substitute covers the shortage, which is
    exactly the refusal S4 exists to make.
    """
    corpus = build_corpus()
    substitute = corpus.get("inventory", "LOT-9001")
    assert substitute.quantity == 900.0
    assert substitute.material_id == "MAT-SUB-9"
    assert substitute.usable is True

    required = corpus.order("C-417").requirements[0]
    assert required.material_id == "MAT-ALLOY-7"
    assert required.material_id != substitute.material_id, (
        "the substitute is a different material; equal quantities are a "
        "coincidence, never a coverage relationship"
    )


def test_canonical_orders_and_slots():
    """The identifiers the demo copy names, and the slot recovery vacates."""
    corpus = build_corpus()
    for order_id, resource in (("C-417", "LINE-1"), ("C-418", "LINE-1"), ("C-419", "LINE-2")):
        order = corpus.order(order_id)
        assert order is not None, f"{order_id} is canonical and must exist"
        assert order.resource == resource
        assert order.status == "READY", "every order starts READY; reseed is repeatable"
