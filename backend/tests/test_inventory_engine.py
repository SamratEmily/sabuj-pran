"""Inventory engine: costing, limits, reservations, transfers, reversals, invariants."""

import random
from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.dates import today
from app.core.errors import AppError
from app.modules.auth.models import User
from app.modules.inventory import service as inv
from app.modules.inventory.models import (
    ADJUST_IN,
    ADJUST_OUT,
    PURCHASE_IN,
    PURCHASE_RETURN_OUT,
    SALE_OUT,
    SALE_RETURN_IN,
    StockBalance,
    StockTransaction,
)
from app.modules.master.models import Product, Warehouse

D = Decimal


@dataclass
class Ctx:
    db: Session
    user: User
    p1: int
    p2: int
    p3: int
    wh1: int
    wh2: int


@pytest.fixture
def ctx(db: Session, admin: User) -> Ctx:
    products = dict(db.execute(select(Product.code, Product.id)).all())
    main = db.scalar(select(Warehouse.id).where(Warehouse.code == "MAIN"))
    second = Warehouse(name="Second", code="WH2", address="", is_default=False, is_active=True)
    db.add(second)
    db.flush()
    assert main is not None
    return Ctx(
        db, admin, products["P-0001"], products["P-0002"], products["P-0003"], main, second.id
    )


def bal(c: Ctx, product_id: int, warehouse_id: int) -> tuple[Decimal, Decimal, Decimal]:
    b = inv.get_balance(c.db, product_id, warehouse_id)
    assert b is not None
    return b.qty_on_hand, b.qty_reserved, b.avg_cost


def put(
    c: Ctx, qty: str, cost: str, p: int | None = None, w: int | None = None
) -> StockTransaction:
    return inv.stock_in(
        c.db, p or c.p1, w or c.wh1, D(qty), D(cost), PURCHASE_IN, "TEST", None, today(), c.user
    )


def take(c: Ctx, qty: str, p: int | None = None, w: int | None = None, **kw: object) -> Decimal:
    return inv.stock_out(
        c.db, p or c.p1, w or c.wh1, D(qty), SALE_OUT, "TEST", None, today(), c.user, **kw
    )


def ledger_count(c: Ctx) -> int:
    return c.db.scalar(select(func.count()).select_from(StockTransaction)) or 0


# --- weighted average ------------------------------------------------------------------


def test_weighted_average_over_ins_and_outs(ctx: Ctx) -> None:
    put(ctx, "10", "100")
    assert bal(ctx, ctx.p1, ctx.wh1) == (D("10"), D("0"), D("100.0000"))

    put(ctx, "5", "130")  # (1000 + 650) / 15
    assert bal(ctx, ctx.p1, ctx.wh1)[2] == D("110.0000")

    assert take(ctx, "6") == D("110.0000")  # OUT at current avg, avg unchanged
    assert bal(ctx, ctx.p1, ctx.wh1) == (D("9"), D("0"), D("110.0000"))

    put(ctx, "9", "90")  # (990 + 810) / 18
    assert bal(ctx, ctx.p1, ctx.wh1)[2] == D("100.0000")

    assert take(ctx, "18") == D("100.0000")
    assert bal(ctx, ctx.p1, ctx.wh1)[:2] == (D("0"), D("0"))

    # from zero stock, the previous average does not leak into the new one
    put(ctx, "3", "10")
    assert bal(ctx, ctx.p1, ctx.wh1)[2] == D("10.0000")
    put(ctx, "1", "11")  # 41 / 4
    assert bal(ctx, ctx.p1, ctx.wh1)[2] == D("10.2500")
    put(ctx, "2", "10.3333")  # 61.6666 / 6 = 10.27776... -> 4 places, half-up
    assert bal(ctx, ctx.p1, ctx.wh1) == (D("6"), D("0"), D("10.2778"))

    # fractional quantities
    put(ctx, "0.125", "8", p=ctx.p2)
    put(ctx, "0.375", "12", p=ctx.p2)  # (1 + 4.5) / 0.5 = 11
    assert bal(ctx, ctx.p2, ctx.wh1) == (D("0.500"), D("0"), D("11.0000"))


def test_ledger_rows_record_cost_and_balance_after(ctx: Ctx) -> None:
    put(ctx, "10", "100")
    take(ctx, "4")
    rows = ctx.db.scalars(select(StockTransaction).order_by(StockTransaction.id)).all()
    assert [(r.txn_type, r.qty_in, r.qty_out, r.unit_cost, r.balance_after) for r in rows] == [
        (PURCHASE_IN, D("10"), D("0"), D("100.0000"), D("10")),
        (SALE_OUT, D("0"), D("4"), D("100.0000"), D("6")),
    ]


# --- limits ----------------------------------------------------------------------------


def test_out_beyond_stock_is_rejected_and_changes_nothing(ctx: Ctx) -> None:
    with pytest.raises(AppError) as err:
        take(ctx, "1")  # nothing in stock (no balance row yet)
    assert err.value.code == "INSUFFICIENT_STOCK"

    put(ctx, "5", "20")
    before = (bal(ctx, ctx.p1, ctx.wh1), ledger_count(ctx))
    with pytest.raises(AppError) as err:
        take(ctx, "5.001")
    assert err.value.code == "INSUFFICIENT_STOCK"
    assert "available 5" in err.value.detail
    assert "P-0001 Plastic Granules in Main Warehouse" in err.value.detail
    assert (bal(ctx, ctx.p1, ctx.wh1), ledger_count(ctx)) == before

    assert take(ctx, "5") == D("20.0000")  # exactly all of it is fine
    assert bal(ctx, ctx.p1, ctx.wh1)[0] == D("0")


@pytest.mark.parametrize("qty", ["0", "-1", "1.0001", "NaN"])
def test_invalid_quantities(ctx: Ctx, qty: str) -> None:
    with pytest.raises(AppError) as err:
        put(ctx, qty, "1")
    assert err.value.code == "INVALID_QTY"


def test_invalid_cost(ctx: Ctx) -> None:
    for cost in ("-0.01", "1.00001"):
        with pytest.raises(AppError) as err:
            put(ctx, "1", cost)
        assert err.value.code == "INVALID_COST"


def test_unknown_product_or_warehouse(ctx: Ctx) -> None:
    with pytest.raises(AppError) as err:
        put(ctx, "1", "1", p=999999)
    assert err.value.code == "INVALID_PRODUCT"
    with pytest.raises(AppError) as err:
        put(ctx, "1", "1", w=999999)
    assert err.value.code == "INVALID_WAREHOUSE"


# --- reservations ----------------------------------------------------------------------


def test_reserve_and_release_limits(ctx: Ctx) -> None:
    put(ctx, "10", "5")
    inv.reserve(ctx.db, ctx.p1, ctx.wh1, D("6"))
    assert bal(ctx, ctx.p1, ctx.wh1)[:2] == (D("10"), D("6"))

    with pytest.raises(AppError) as err:
        inv.reserve(ctx.db, ctx.p1, ctx.wh1, D("4.001"))  # only 4 available
    assert err.value.code == "INSUFFICIENT_STOCK"
    inv.reserve(ctx.db, ctx.p1, ctx.wh1, D("4"))  # exactly the rest
    assert bal(ctx, ctx.p1, ctx.wh1)[:2] == (D("10"), D("10"))

    with pytest.raises(AppError) as err:
        inv.release(ctx.db, ctx.p1, ctx.wh1, D("10.001"))
    assert err.value.code == "INVALID_RELEASE"
    inv.release(ctx.db, ctx.p1, ctx.wh1, D("10"))
    assert bal(ctx, ctx.p1, ctx.wh1)[:2] == (D("10"), D("0"))
    with pytest.raises(AppError):
        inv.release(ctx.db, ctx.p1, ctx.wh1, D("0.001"))  # never below zero


def test_free_stock_excludes_reservations(ctx: Ctx) -> None:
    put(ctx, "10", "5")
    inv.reserve(ctx.db, ctx.p1, ctx.wh1, D("6"))  # e.g. SO-A 4 + SO-B 2
    with pytest.raises(AppError) as err:
        take(ctx, "5")  # only 4 free
    assert err.value.code == "INSUFFICIENT_STOCK"


def test_out_consumes_own_reservation(ctx: Ctx) -> None:
    put(ctx, "10", "5")
    inv.reserve(ctx.db, ctx.p1, ctx.wh1, D("6"))

    # SO-A delivers 5: 4 from its reservation + 1 free
    take(ctx, "5", reserved_qty=D("4"))
    assert bal(ctx, ctx.p1, ctx.wh1)[:2] == (D("5"), D("2"))

    with pytest.raises(AppError) as err:
        take(ctx, "4")  # free = 5 - 2 = 3
    assert err.value.code == "INSUFFICIENT_STOCK"
    with pytest.raises(AppError) as err:
        take(ctx, "3", reserved_qty=D("3"))  # only 2 reserved
    assert err.value.code == "INVALID_RESERVATION"
    with pytest.raises(AppError) as err:
        take(ctx, "1", reserved_qty=D("2"))  # reserved part larger than qty
    assert err.value.code == "INVALID_RESERVATION"

    take(ctx, "5", reserved_qty=D("2"))  # SO-B: 2 reserved + 3 free = everything
    assert bal(ctx, ctx.p1, ctx.wh1)[:2] == (D("0"), D("0"))


def test_reserved_stock_cannot_be_moved_by_transfer(ctx: Ctx) -> None:
    put(ctx, "10", "5")
    inv.reserve(ctx.db, ctx.p1, ctx.wh1, D("8"))
    with pytest.raises(AppError) as err:
        inv.transfer(ctx.db, ctx.p1, ctx.wh1, ctx.wh2, D("3"), "TEST", None, today(), ctx.user)
    assert err.value.code == "INSUFFICIENT_STOCK"
    inv.transfer(ctx.db, ctx.p1, ctx.wh1, ctx.wh2, D("2"), "TEST", None, today(), ctx.user)
    assert bal(ctx, ctx.p1, ctx.wh1)[:2] == (D("8"), D("8"))


# --- purchase return at receipt cost ---------------------------------------------------


def test_out_at_specific_cost_recomputes_average_from_value(ctx: Ctx) -> None:
    put(ctx, "10", "12")  # value 120
    cost = inv.stock_out(
        ctx.db,
        ctx.p1,
        ctx.wh1,
        D("4"),
        PURCHASE_RETURN_OUT,
        "TEST",
        None,
        today(),
        ctx.user,
        unit_cost=D("15"),
    )
    assert cost == D("15.0000")
    assert bal(ctx, ctx.p1, ctx.wh1) == (D("6"), D("0"), D("10.0000"))  # (120 - 60) / 6

    # value can't go negative: average floors at 0
    put(ctx, "2", "1", p=ctx.p2)
    put(ctx, "2", "100", p=ctx.p2)  # avg 50.5, value 202
    inv.stock_out(
        ctx.db,
        ctx.p2,
        ctx.wh1,
        D("3"),
        PURCHASE_RETURN_OUT,
        "TEST",
        None,
        today(),
        ctx.user,
        unit_cost=D("100"),
    )
    assert bal(ctx, ctx.p2, ctx.wh1) == (D("1"), D("0"), D("0.0000"))

    # returning everything leaves the last average in place
    put(ctx, "5", "7", p=ctx.p3)
    inv.stock_out(
        ctx.db,
        ctx.p3,
        ctx.wh1,
        D("5"),
        PURCHASE_RETURN_OUT,
        "TEST",
        None,
        today(),
        ctx.user,
        unit_cost=D("9"),
    )
    assert bal(ctx, ctx.p3, ctx.wh1) == (D("0"), D("0"), D("7.0000"))


# --- transfers -------------------------------------------------------------------------


def test_transfer_moves_qty_and_cost(ctx: Ctx) -> None:
    put(ctx, "10", "50", w=ctx.wh1)
    put(ctx, "10", "80", w=ctx.wh2)
    cost = inv.transfer(ctx.db, ctx.p1, ctx.wh1, ctx.wh2, D("4"), "TEST", 1, today(), ctx.user)
    assert cost == D("50.0000")
    assert bal(ctx, ctx.p1, ctx.wh1) == (D("6"), D("0"), D("50.0000"))
    assert bal(ctx, ctx.p1, ctx.wh2) == (D("14"), D("0"), D("71.4286"))  # 1000 / 14
    types = ctx.db.scalars(
        select(StockTransaction.txn_type).where(StockTransaction.ref_id == 1)
    ).all()
    assert sorted(types) == ["TRANSFER_IN", "TRANSFER_OUT"]


def test_transfer_to_same_warehouse_rejected(ctx: Ctx) -> None:
    put(ctx, "5", "1")
    with pytest.raises(AppError) as err:
        inv.transfer(ctx.db, ctx.p1, ctx.wh1, ctx.wh1, D("1"), "TEST", None, today(), ctx.user)
    assert err.value.code == "SAME_WAREHOUSE"


# --- reversal --------------------------------------------------------------------------


def test_reversal_adds_opposite_row_once(ctx: Ctx) -> None:
    row = inv.stock_in(
        ctx.db, ctx.p1, ctx.wh1, D("10"), D("20"), ADJUST_IN, "TEST", None, today(), ctx.user
    )
    rev = inv.reverse_transaction(ctx.db, row.id, ctx.user)
    assert (rev.txn_type, rev.qty_out, rev.unit_cost, rev.reversal_of_id, rev.ref_type) == (
        ADJUST_OUT,
        D("10"),
        D("20.0000"),
        row.id,
        "REVERSAL",
    )
    assert bal(ctx, ctx.p1, ctx.wh1)[0] == D("0")

    original = ctx.db.get(StockTransaction, row.id)
    assert original is not None and original.qty_in == D("10")  # untouched

    for target in (row.id, rev.id):
        with pytest.raises(AppError) as err:
            inv.reverse_transaction(ctx.db, target, ctx.user)
        assert err.value.code == "ALREADY_REVERSED"


def test_reversing_an_out_brings_stock_back_at_its_cost(ctx: Ctx) -> None:
    put(ctx, "10", "30")
    take(ctx, "4")
    out = ctx.db.scalar(select(StockTransaction).where(StockTransaction.txn_type == SALE_OUT))
    assert out is not None
    rev = inv.reverse_transaction(ctx.db, out.id, ctx.user)
    assert (rev.txn_type, rev.qty_in, rev.unit_cost) == (SALE_RETURN_IN, D("4"), D("30.0000"))
    assert bal(ctx, ctx.p1, ctx.wh1) == (D("10"), D("0"), D("30.0000"))


def test_reversing_an_in_that_was_consumed_fails(ctx: Ctx) -> None:
    row = put(ctx, "5", "10")
    take(ctx, "3")
    with pytest.raises(AppError) as err:
        inv.reverse_transaction(ctx.db, row.id, ctx.user)
    assert err.value.code == "INSUFFICIENT_STOCK"


# --- append-only -----------------------------------------------------------------------


def test_stock_ledger_rows_cannot_be_updated_or_deleted(ctx: Ctx) -> None:
    row = put(ctx, "1", "1")
    for sql in (
        "UPDATE stock_transactions SET qty_in = 99 WHERE id = :id",
        "DELETE FROM stock_transactions WHERE id = :id",
    ):
        with pytest.raises(OperationalError, match="append-only"), ctx.db.begin_nested():
            ctx.db.execute(text(sql), {"id": row.id})


def test_balance_check_constraint_blocks_negative_values(ctx: Ctx) -> None:
    put(ctx, "1", "1")
    with pytest.raises(OperationalError), ctx.db.begin_nested():
        ctx.db.execute(
            text("UPDATE stock_balances SET qty_reserved = 2 WHERE product_id = :p"),
            {"p": ctx.p1},
        )


# --- invariants over a random workload -------------------------------------------------


def assert_invariants(db: Session) -> None:
    balances = db.scalars(select(StockBalance)).all()
    assert balances
    for b in balances:
        rows = db.scalars(
            select(StockTransaction)
            .where(
                StockTransaction.product_id == b.product_id,
                StockTransaction.warehouse_id == b.warehouse_id,
            )
            .order_by(StockTransaction.id)
        ).all()
        net = sum((r.qty_in - r.qty_out for r in rows), D("0"))
        assert net == b.qty_on_hand
        if rows:
            assert rows[-1].balance_after == b.qty_on_hand
        running = D("0")
        for r in rows:  # every row's balance_after is the running sum at that point
            running += r.qty_in - r.qty_out
            assert r.balance_after == running >= 0
        assert D("0") <= b.qty_reserved <= b.qty_on_hand
        assert b.avg_cost >= 0


def test_invariants_hold_after_random_operations(ctx: Ctx) -> None:
    rng = random.Random(20261013)
    products = [ctx.p1, ctx.p2, ctx.p3]
    warehouses = [ctx.wh1, ctx.wh2]
    ok = failed = 0

    def qty() -> D:
        return D(rng.randint(1, 20_000)) / 1000  # 0.001 .. 20.000

    for _ in range(300):
        p, w = rng.choice(products), rng.choice(warehouses)
        op = rng.choices(
            ["in", "out", "reserve", "release", "transfer", "reverse", "return"],
            weights=[30, 25, 10, 8, 12, 8, 7],
        )[0]
        try:
            with ctx.db.begin_nested():
                if op == "in":
                    put(ctx, str(qty()), str(D(rng.randint(100, 99_999)) / 100), p=p, w=w)
                elif op == "out":
                    b = inv.get_balance(ctx.db, p, w)
                    reserved = min(b.qty_reserved, qty()) if b and rng.random() < 0.3 else D("0")
                    take(ctx, str(qty()), p=p, w=w, reserved_qty=reserved)
                elif op == "reserve":
                    inv.reserve(ctx.db, p, w, qty())
                elif op == "release":
                    inv.release(ctx.db, p, w, qty())
                elif op == "transfer":
                    other = warehouses[1 - warehouses.index(w)]
                    inv.transfer(ctx.db, p, w, other, qty(), "TEST", None, today(), ctx.user)
                elif op == "return":
                    inv.stock_out(
                        ctx.db,
                        p,
                        w,
                        qty(),
                        PURCHASE_RETURN_OUT,
                        "TEST",
                        None,
                        today(),
                        ctx.user,
                        unit_cost=D(rng.randint(100, 99_999)) / 100,
                    )
                else:
                    ids = ctx.db.scalars(select(StockTransaction.id)).all()
                    if ids:
                        inv.reverse_transaction(ctx.db, rng.choice(ids), ctx.user)
            ok += 1
        except AppError:
            failed += 1
    assert ok > 150 and failed > 10  # the workload exercised both paths
    assert_invariants(ctx.db)
