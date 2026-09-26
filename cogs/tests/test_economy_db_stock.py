"""Stock / fuzzy-search tests for the economy DB layer (temp DB, no live data touched)."""

import os
import shutil
import sqlite3

import pytest

from utils import economy_db as edb


@pytest.fixture()
def stock_db(tmp_path, monkeypatch):
    """Point the economy DB at a fresh temp copy so tests never hit the live DB."""
    db_path = os.path.join(edb.BASE_DIR, "db", "economy.db")
    target = tmp_path / "economy_test.db"
    if os.path.exists(db_path):
        shutil.copy2(db_path, target)
    monkeypatch.setattr(edb, "DB_PATH", str(target))
    monkeypatch.setattr(edb, "_DB_READY", False)
    monkeypatch.setattr(edb, "_BOT_DB_MIGRATED", True)
    edb._ensure_ready()
    yield str(target)


class TestShopStock:
    def test_column_exists(self, stock_db):
        conn = sqlite3.connect(stock_db)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(economy_shop_items)").fetchall()]
        assert "stock" in cols

    def test_add_and_null_stock(self, stock_db):
        item_id = edb.add_shop_item(1, "🪵 Log", "a log", 100, stock=5)
        item = edb.get_shop_item_by_name(1, "Log")
        assert item_id
        assert item["stock"] == 5

    def test_default_stock_is_zero(self, stock_db):
        edb.add_shop_item(1, "🎆 Fireworks", "boom", 100)
        assert edb.get_shop_item_by_name(1, "Fireworks")["stock"] == 0

    def test_update_stock(self, stock_db):
        edb.add_shop_item(1, "🪵 Log", "a log", 100, stock=5)
        assert edb.update_shop_item_by_name(1, "Log", stock=0)
        assert edb.get_shop_item_by_name(1, "Log")["stock"] == 0

    def test_search_fuzzy_ranking(self, stock_db):
        edb.add_shop_item(1, "🪵 Log", "a log", 100)
        edb.add_shop_item(1, "🔭 Peep Hole", "peek", 150)
        res = edb.search_shop_items(1, "peep")
        assert res and res[0]["name"] == "🔭 Peep Hole"
        assert res[0]["score"] >= 0.9
        assert edb.search_shop_items(1, "zzzznope") == []

    def test_search_includes_stock_and_score(self, stock_db):
        edb.add_shop_item(1, "🪵 Log", "a log", 100, stock=3)
        res = edb.search_shop_items(1, "log")
        assert res[0]["stock"] == 3
        assert "score" in res[0]

    def test_search_inventory_items(self, stock_db):
        edb.set_economy_channel_balance(1, 2, 1000)
        item_id = edb.add_shop_item(1, "🪵 Log", "a log", 100, stock=5)
        edb.add_inventory_item_channel(1, 2, item_id, 3)
        res = edb.search_inventory_items(1, 2, "log")
        assert res and res[0]["name"] == "🪵 Log"
        assert res[0]["quantity"] == 3
        assert edb.search_inventory_items(1, 2, "nothing") == []

    def test_buy_decrements_stock(self, stock_db):
        edb.set_economy_channel_balance(1, 2, 1000)
        item_id = edb.add_shop_item(1, "🪵 Log", "a log", 100, stock=5)
        ok, qty, reason = edb.buy_shop_item(1, 2, item_id, 100, 2)
        assert ok is True and qty == 2 and reason is None
        assert edb.get_shop_item_by_name(1, "Log")["stock"] == 3

    def test_buy_over_stock_fails(self, stock_db):
        edb.set_economy_channel_balance(1, 2, 1000)
        item_id = edb.add_shop_item(1, "🪵 Log", "a log", 100, stock=2)
        ok, qty, reason = edb.buy_shop_item(1, 2, item_id, 100, 3)
        assert ok is False and reason == "stock"
        assert edb.get_shop_item_by_name(1, "Log")["stock"] == 2

    def test_unlimited_zero_stock_never_decrements(self, stock_db):
        edb.set_economy_channel_balance(1, 2, 1000)
        item_id = edb.add_shop_item(1, "🎆 Fireworks", "boom", 100, stock=0)
        ok, qty, reason = edb.buy_shop_item(1, 2, item_id, 100, 3)
        assert ok is True and reason is None
        assert edb.get_shop_item_by_name(1, "Fireworks")["stock"] == 0

    def test_buy_balance_failure_does_not_touch_stock(self, stock_db):
        edb.set_economy_channel_balance(1, 2, 10)
        item_id = edb.add_shop_item(1, "🪵 Log", "a log", 100, stock=5)
        ok, qty, reason = edb.buy_shop_item(1, 2, item_id, 100, 1)
        assert ok is False and reason == "balance"
        assert edb.get_shop_item_by_name(1, "Log")["stock"] == 5