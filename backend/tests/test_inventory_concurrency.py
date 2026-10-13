"""Real concurrency against MySQL: many threads, each with its own connection and transaction.

These tests must commit, and stock ledger rows can never be deleted (append-only triggers),
so they run in a separate throwaway database (`*_conc_test`) that is created, migrated and
seeded here and dropped afterwards. The main test database stays clean.
"""

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, make_url, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dates import today
from app.core.db import make_engine
from app.core.errors import AppError
from app.modules.auth.models import User
from app.modules.inventory import service as inv
from app.modules.inventory.models import PURCHASE_IN, SALE_OUT, StockBalance, StockTransaction
from app.modules.master.models import Product, Warehouse
from app.seed import seed
from tests.conftest import drop_database, migrate, recreate_database

D = Decimal
THREADS = 20


@dataclass
class Conc:
    engine: Engine
    admin_id: int
    products: list[int]
    wh1: int
    wh2: int


@pytest.fixture(scope="module")
def conc(engine: Engine) -> Iterator[Conc]:  # `engine` first: it applies test settings
    main_url = make_url(settings.test_database_url)
    name = main_url.database
    assert name and name.endswith("_test")
    url = main_url.set(database=f"{name[: -len('_test')]}_conc_test").render_as_string(
        hide_password=False
    )
    recreate_database(url)
    migrate(url)
    eng = make_engine(url, pool_size=THREADS + 5)
    with Session(eng) as s:
        seed(s)
        second = Warehouse(name="Second", code="WH2", address="", is_default=False, is_active=True)
        s.add(second)
        s.commit()
        admin_id = s.scalar(select(User.id).where(User.username == "admin"))
        products = list(s.scalars(select(Product.id).order_by(Product.id)))
        wh1 = s.scalar(select(Warehouse.id).where(Warehouse.code == "MAIN"))
        assert admin_id and wh1
        data = Conc(eng, admin_id, products, wh1, second.id)
    try:
        yield data
    finally:
        eng.dispose()
        drop_database(url)


def run_parallel(c: Conc, work: Callable[[Session, User, int], object]) -> list[str]:
    """Run `work` in THREADS threads released together; each commits its own transaction.
    Returns one outcome per thread: "ok", an AppError code, or "ERROR: <exception>"."""
    barrier = threading.Barrier(THREADS)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        with Session(c.engine) as session:
            user = session.get(User, c.admin_id)
            assert user is not None
            barrier.wait()
            try:
                work(session, user, i)
                session.commit()
                result = "ok"
            except AppError as exc:
                session.rollback()
                result = exc.code
            except Exception as exc:  # deadlocks, lock timeouts... must not happen
                session.rollback()
                result = f"ERROR: {exc!r}"[:300]
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert len(outcomes) == THREADS, "a thread hung"
    return outcomes


def committed(c: Conc, fn: Callable[[Session, User], object]) -> None:
    with Session(c.engine) as s:
        user = s.get(User, c.admin_id)
        assert user is not None
        fn(s, user)
        s.commit()


def read_balance(c: Conc, product: int, wh: int) -> StockBalance:
    with Session(c.engine) as s:
        b = s.scalar(
            select(StockBalance).where(
                StockBalance.product_id == product, StockBalance.warehouse_id == wh
            )
        )
        assert b is not None
        s.expunge(b)
        return b


def test_twenty_threads_taking_one_unit_from_ten(conc: Conc) -> None:
    p = conc.products[0]
    committed(
        conc,
        lambda s, u: inv.stock_in(
            s, p, conc.wh1, D("10"), D("25"), PURCHASE_IN, "TEST", None, today(), u
        ),
    )

    outcomes = run_parallel(
        conc,
        lambda s, u, i: inv.stock_out(s, p, conc.wh1, D("1"), SALE_OUT, "CONC", i, today(), u),
    )
    assert sorted(outcomes) == ["INSUFFICIENT_STOCK"] * 10 + ["ok"] * 10, outcomes

    balance = read_balance(conc, p, conc.wh1)
    assert balance.qty_on_hand == D("0")
    with Session(conc.engine) as s:
        rows = s.scalars(
            select(StockTransaction)
            .where(StockTransaction.product_id == p, StockTransaction.warehouse_id == conc.wh1)
            .order_by(StockTransaction.id)
        ).all()
        outs = [r for r in rows if r.txn_type == SALE_OUT]
        assert len(outs) == 10
        # each successful OUT saw the previous one: balance_after counts down 9..0 exactly once
        assert sorted(r.balance_after for r in outs) == [D(n) for n in range(10)]
        assert min(r.balance_after for r in rows) >= 0


def test_twenty_threads_creating_the_same_balance_row(conc: Conc) -> None:
    """No balance row exists yet for (product, WH2); all threads race to create it."""
    p = conc.products[1]
    outcomes = run_parallel(
        conc,
        lambda s, u, i: inv.stock_in(
            s, p, conc.wh2, D("1"), D("10"), PURCHASE_IN, "CONC", i, today(), u
        ),
    )
    assert outcomes == ["ok"] * THREADS, outcomes
    balance = read_balance(conc, p, conc.wh2)
    assert (balance.qty_on_hand, balance.avg_cost) == (D("20"), D("10.0000"))
    with Session(conc.engine) as s:
        count = s.scalar(
            select(func.count())
            .select_from(StockBalance)
            .where(StockBalance.product_id == p, StockBalance.warehouse_id == conc.wh2)
        )
        assert count == 1


def test_opposite_transfers_do_not_deadlock(conc: Conc) -> None:
    p = conc.products[2]
    committed(
        conc,
        lambda s, u: inv.stock_in(
            s, p, conc.wh1, D("50"), D("4"), PURCHASE_IN, "TEST", None, today(), u
        ),
    )
    committed(
        conc,
        lambda s, u: inv.stock_in(
            s, p, conc.wh2, D("50"), D("4"), PURCHASE_IN, "TEST", None, today(), u
        ),
    )

    def move(s: Session, u: User, i: int) -> None:
        src, dst = (conc.wh1, conc.wh2) if i % 2 == 0 else (conc.wh2, conc.wh1)
        inv.transfer(s, p, src, dst, D("1"), "CONC", i, today(), u)

    outcomes = run_parallel(conc, move)
    assert outcomes == ["ok"] * THREADS, outcomes
    a, b = read_balance(conc, p, conc.wh1), read_balance(conc, p, conc.wh2)
    assert (a.qty_on_hand, b.qty_on_hand) == (D("50"), D("50"))  # 10 each way
    assert (a.avg_cost, b.avg_cost) == (D("4.0000"), D("4.0000"))


def test_twenty_threads_paying_one_from_ten(conc: Conc) -> None:
    """Money accounts use the same row locking: exactly 10 payments of 1 fit into 10."""
    from app.modules.money import service as money
    from app.modules.money.models import MoneyAccount

    with Session(conc.engine) as s:
        account = MoneyAccount(name="Conc Cash", account_type="cash", is_active=True)
        s.add(account)
        s.commit()
        account_id = account.id
    committed(
        conc,
        lambda s, u: money.money_in(s, account_id, D("10"), "INCOME", "TEST", None, today(), u),
    )
    outcomes = run_parallel(
        conc,
        lambda s, u, i: money.money_out(s, account_id, D("1"), "EXPENSE", "CONC", i, today(), u),
    )
    assert sorted(outcomes) == ["INSUFFICIENT_FUNDS"] * 10 + ["ok"] * 10, outcomes
    with Session(conc.engine) as s:
        assert s.get(MoneyAccount, account_id).balance == D("0.00")
        assert money.ledger_balance(s, account_id) == D("0.00")
