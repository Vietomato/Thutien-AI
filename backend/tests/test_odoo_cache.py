"""The in-memory cache around Odoo Online reads: pages open fast, nobody waits for Odoo when data is merely stale,
and a single invoice (needed fresh for approvals) is never cached."""
import threading
import time

import pytest

from app import odoo_reader


def wait_until(condition, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


@pytest.fixture
def online(monkeypatch):
    """Odoo Online with a fake network: every read is recorded, takes 50 ms and returns a new number."""
    monkeypatch.setenv("ODOO_SOURCE", "online")
    monkeypatch.setenv("ODOO_CACHE_SECONDS", "60")
    odoo_reader.clear_cache()
    calls = []

    def fetch(method, *args):
        calls.append((method, args))
        time.sleep(0.05)
        return [{"read": len(calls)}]
    monkeypatch.setattr(odoo_reader, "_fetch", fetch)
    yield calls
    odoo_reader.clear_cache()


def age_entries(seconds):
    """Pretend everything in the cache was read `seconds` ago."""
    for key, (mono, wall, value) in list(odoo_reader._CACHE.items()):
        odoo_reader._CACHE[key] = (mono - seconds, wall - seconds, value)


# ---------------------------------------------------------------- fresh data

def test_the_second_read_comes_from_memory(online):
    first, second = odoo_reader.customers(), odoo_reader.customers()
    assert first == second and len(online) == 1


def test_different_lists_are_cached_separately(online):
    odoo_reader.supplier_bills(), odoo_reader.customers(), odoo_reader.supplier_bills()
    assert [c[0] for c in online] == ["supplier_bills", "customers"]


def test_callers_get_their_own_copy(online):
    odoo_reader.customers().append({"read": "mutated"})
    assert odoo_reader.customers() == [{"read": 1}]


def test_clear_cache_reads_fresh_data(online):
    odoo_reader.customers()
    odoo_reader.clear_cache()
    assert odoo_reader.customers() == [{"read": 2}]


def test_cache_off_means_every_read_goes_to_odoo(online, monkeypatch):
    monkeypatch.setenv("ODOO_CACHE_SECONDS", "0")
    odoo_reader.customers(), odoo_reader.customers()
    assert len(online) == 2


def test_local_database_reads_are_not_cached(monkeypatch):
    monkeypatch.setenv("ODOO_SOURCE", "local_db"); monkeypatch.setenv("ODOO_CACHE_SECONDS", "60")
    odoo_reader.clear_cache()
    rows = iter([[("C1", "A")], [("C1", "B")]])
    monkeypatch.setattr(odoo_reader, "_query", lambda sql, params=None: next(rows))
    assert odoo_reader.customers() != odoo_reader.customers()


# ---------------------------------------------------------------- one list serves every customer

class Item:
    def __init__(self, customer_id):
        self.customer_id = customer_id


def test_a_customers_view_is_cut_from_the_one_cached_list(monkeypatch):
    monkeypatch.setenv("ODOO_SOURCE", "online"); monkeypatch.setenv("ODOO_CACHE_SECONDS", "60")
    odoo_reader.clear_cache()
    calls = []
    monkeypatch.setattr(odoo_reader, "_fetch", lambda method, *a: calls.append((method, a)) or [Item("C1"), Item("C2"), Item("C1")])
    assert len(odoo_reader.open_invoices()) == 3
    assert [i.customer_id for i in odoo_reader.open_invoices("C1")] == ["C1", "C1"]
    assert odoo_reader.open_invoices("C9") == []
    assert len(calls) == 1
    odoo_reader.clear_cache()


# ---------------------------------------------------------------- stale data is served at once and refreshed behind the scenes

def test_stale_data_is_returned_at_once_and_refreshed_in_the_background(online):
    odoo_reader.customers()                                   # slow first read
    age_entries(400)                                          # customers is a slow list: fresh for 300 s, usable until 3,000 s
    started = time.monotonic()
    value = odoo_reader.customers()
    assert time.monotonic() - started < 0.04                  # no 50 ms Odoo read was waited for
    assert value == [{"read": 1}]                             # the old data
    assert wait_until(lambda: len(online) == 2)               # one refresh started
    assert wait_until(lambda: odoo_reader.customers() == [{"read": 2}])


def test_many_stale_requests_start_only_one_refresh(online):
    odoo_reader.supplier_bills()
    age_entries(100)                                          # ttl 60, limit 600
    for _ in range(8):
        odoo_reader.supplier_bills()
    time.sleep(0.2)
    assert len(online) == 2


def test_a_failed_refresh_keeps_the_old_data_and_waits_before_retrying(monkeypatch):
    monkeypatch.setenv("ODOO_SOURCE", "online"); monkeypatch.setenv("ODOO_CACHE_SECONDS", "60")
    odoo_reader.clear_cache()
    state = {"n": 0}

    def flaky(method, *args):
        state["n"] += 1
        if state["n"] == 1:
            return ["first"]
        raise odoo_reader.OdooUnavailable("down")
    monkeypatch.setattr(odoo_reader, "_fetch", flaky)
    assert odoo_reader.supplier_bills() == ["first"]
    age_entries(100)
    assert odoo_reader.supplier_bills() == ["first"]          # stale answer while the refresh fails in the background
    assert wait_until(lambda: state["n"] == 2 and not odoo_reader._REFRESHING)
    assert odoo_reader.supplier_bills() == ["first"]          # still served; no immediate retry storm
    time.sleep(0.05)
    assert state["n"] == 2
    odoo_reader.clear_cache()


def test_data_too_old_is_read_again_before_answering(online):
    odoo_reader.supplier_bills()
    age_entries(100_000)                                      # far beyond the limit
    assert odoo_reader.supplier_bills() == [{"read": 2}]


def test_errors_are_not_cached(monkeypatch):
    monkeypatch.setenv("ODOO_SOURCE", "online"); monkeypatch.setenv("ODOO_CACHE_SECONDS", "60")
    odoo_reader.clear_cache()
    state = {"n": 0}

    def flaky(method, *args):
        state["n"] += 1
        if state["n"] == 1:
            raise odoo_reader.OdooUnavailable("down")
        return ["ok"]
    monkeypatch.setattr(odoo_reader, "_fetch", flaky)
    with pytest.raises(odoo_reader.OdooUnavailable):
        odoo_reader.customers()
    assert odoo_reader.customers() == ["ok"]
    odoo_reader.clear_cache()


def test_concurrent_cold_requests_share_one_read(online):
    results = []
    threads = [threading.Thread(target=lambda: results.append(odoo_reader.paid_delays())) for _ in range(6)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert len(online) == 1 and len(results) == 6 and all(r == [{"read": 1}] for r in results)


def test_different_lists_load_in_parallel_not_one_after_another(online):
    started = time.monotonic()
    threads = [threading.Thread(target=f) for f in (odoo_reader.customers, odoo_reader.supplier_bills, odoo_reader.paid_delays)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert time.monotonic() - started < 0.13                  # three 50 ms reads overlapped (one after another would be 150 ms)


# ---------------------------------------------------------------- one invoice is never cached

def test_a_single_invoice_is_always_read_fresh(online):
    odoo_reader.open_invoice("INV/1"), odoo_reader.open_invoice("INV/1"), odoo_reader.open_invoice("INV/1")
    assert len(online) == 3


# ---------------------------------------------------------------- warm-up and "updated at"

def test_warm_up_reads_the_main_lists_once(online):
    odoo_reader.warm_cache()
    assert sorted(c[0] for c in online) == ["customers", "open_invoices", "paid_delays", "supplier_bills"]
    odoo_reader.warm_cache()
    assert len(online) == 4                                   # a second warm-up finds everything already in memory


def test_warm_up_does_nothing_for_the_local_database(monkeypatch):
    monkeypatch.setenv("ODOO_SOURCE", "local_db")
    called = []
    monkeypatch.setattr(odoo_reader, "_fetch", lambda *a: called.append(a))
    odoo_reader.warm_cache()
    assert called == []


def test_a_failing_warm_up_never_raises(online, monkeypatch):
    monkeypatch.setattr(odoo_reader, "_fetch", lambda *a: (_ for _ in ()).throw(odoo_reader.OdooUnavailable("down")))
    odoo_reader.warm_cache()


def test_updated_at_is_the_oldest_read_time(online):
    odoo_reader.open_invoices(); odoo_reader.supplier_bills()
    age_entries(90)
    odoo_reader.customers()                                   # not part of the stamp
    stamp = odoo_reader.data_updated_at()
    assert stamp.endswith("+00:00") and stamp[:4].isdigit()
    from datetime import datetime, timezone
    assert 80 < (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds() < 100


# ---------------------------------------------------------------- endpoint

def test_refresh_endpoint_clears_the_cache_and_data_carries_its_time(client, team, auth, fake_odoo, monkeypatch):
    monkeypatch.setenv("ODOO_SOURCE", "online"); monkeypatch.setenv("ODOO_CACHE_SECONDS", "60")
    odoo_reader.clear_cache()
    odoo_reader._CACHE[("customers", ())] = (time.monotonic(), time.time(), ["old"])
    assert client.post("/api/data/refresh").status_code == 401                     # login required
    assert client.post("/api/data/refresh", headers=auth("acc1")).json() == {"ok": True}
    assert not odoo_reader._CACHE
    body = client.get("/api/summary", headers=auth("acc1")).json()
    assert body["data_updated_at"].endswith("+00:00")
