"""Unit tests for core.state.StateStore.

Uses fakeredis to avoid any real Redis dependency.
"""
from __future__ import annotations

import fakeredis.aioredis
import pytest

from core.state import StateStore


@pytest.fixture
async def store() -> StateStore:
    """Return a StateStore with a fake Redis backend."""
    s = StateStore("test_service")
    s._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return s


class TestStateStoreNotConnected:
    def test_ensure_connected_raises_when_not_connected(self) -> None:
        s = StateStore("svc")
        with pytest.raises(RuntimeError, match="not connected"):
            s._ensure_connected()


class TestStateStoreKV:
    async def test_set_and_get(self, store: StateStore) -> None:
        await store.set("mykey", {"value": 42})
        result = await store.get("mykey")
        assert result == {"value": 42}

    async def test_get_missing_key_returns_none(self, store: StateStore) -> None:
        result = await store.get("nonexistent")
        assert result is None

    async def test_set_with_ttl(self, store: StateStore) -> None:
        await store.set("ttlkey", "hello", ttl=3600)
        result = await store.get("ttlkey")
        assert result == "hello"

    async def test_delete_removes_key(self, store: StateStore) -> None:
        await store.set("delkey", 1)
        await store.delete("delkey")
        result = await store.get("delkey")
        assert result is None

    async def test_exists_returns_true_for_set_key(self, store: StateStore) -> None:
        await store.set("existkey", True)
        assert await store.exists("existkey") is True

    async def test_exists_returns_false_for_missing_key(self, store: StateStore) -> None:
        assert await store.exists("missing_key") is False

    async def test_set_decimal_serialized_as_string(self, store: StateStore) -> None:
        from decimal import Decimal

        await store.set("dec_key", Decimal("1.5"))
        result = await store.get("dec_key")
        assert result == "1.5"

    async def test_set_list_value(self, store: StateStore) -> None:
        await store.set("list_key", [1, 2, 3])
        result = await store.get("list_key")
        assert result == [1, 2, 3]


class TestStateStoreHash:
    async def test_hset_and_hget(self, store: StateStore) -> None:
        await store.hset("myhash", "field1", {"score": 0.9})
        result = await store.hget("myhash", "field1")
        assert result == {"score": 0.9}

    async def test_hget_missing_field_returns_none(self, store: StateStore) -> None:
        result = await store.hget("myhash", "missing_field")
        assert result is None

    async def test_hgetall_returns_all_fields(self, store: StateStore) -> None:
        await store.hset("myhash2", "a", 1)
        await store.hset("myhash2", "b", 2)
        result = await store.hgetall("myhash2")
        assert result == {"a": 1, "b": 2}

    async def test_hgetall_empty_hash(self, store: StateStore) -> None:
        result = await store.hgetall("nonexistent_hash")
        assert result == {}

    async def test_hdel_removes_field(self, store: StateStore) -> None:
        await store.hset("myhash3", "fieldX", 99)
        await store.hdel("myhash3", "fieldX")
        result = await store.hget("myhash3", "fieldX")
        assert result is None


class TestStateStoreList:
    async def test_lpush_and_lrange(self, store: StateStore) -> None:
        await store.lpush("mylist", 1, 2, 3)
        result = await store.lrange("mylist")
        assert set(result) == {1, 2, 3}

    async def test_lrange_with_bounds(self, store: StateStore) -> None:
        await store.lpush("mylist2", "a", "b", "c")
        result = await store.lrange("mylist2", 0, 0)
        assert len(result) == 1

    async def test_ltrim_keeps_range(self, store: StateStore) -> None:
        await store.lpush("mylist3", 10, 20, 30)
        await store.ltrim("mylist3", 0, 1)
        result = await store.lrange("mylist3")
        assert len(result) == 2


class TestStateStoreIncr:
    async def test_incr_returns_new_value(self, store: StateStore) -> None:
        val = await store.incr("counter")
        assert val == 1

    async def test_incr_multiple_times(self, store: StateStore) -> None:
        await store.incr("counter2")
        await store.incr("counter2")
        val = await store.incr("counter2")
        assert val == 3

    async def test_incr_with_amount(self, store: StateStore) -> None:
        val = await store.incr("counter3", amount=5)
        assert val == 5


class TestStateStorePubSub:
    async def test_publish_does_not_raise(self, store: StateStore) -> None:
        # Just verify publish doesn't raise; no subscriber in unit test
        await store.publish("my.channel", {"event": "test"})


class TestStateStoreStream:
    async def test_stream_add_returns_id(self, store: StateStore) -> None:
        entry_id = await store.stream_add("mystream", {"field": "value"})
        assert isinstance(entry_id, str)
        assert len(entry_id) > 0

    async def test_stream_read_returns_entries(self, store: StateStore) -> None:
        await store.stream_add("mystream2", {"key": "val"})
        entries = await store.stream_read("mystream2", last_id="0")
        assert len(entries) >= 1
        assert isinstance(entries[0], tuple)
        _, data = entries[0]
        assert "key" in data
        assert data["key"] == "val"

    async def test_stream_read_empty_stream(self, store: StateStore) -> None:
        entries = await store.stream_read("empty_stream", last_id="0")
        assert entries == []


class TestStateStoreDisconnect:
    async def test_disconnect_clears_redis(self, store: StateStore) -> None:
        assert store._redis is not None
        await store.disconnect()
        assert store._redis is None

    async def test_disconnect_when_not_connected_is_noop(self) -> None:
        s = StateStore("svc2")
        # Should not raise
        await s.disconnect()
