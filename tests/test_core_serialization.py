import os
import struct

import pytest

from core.bloom import HEADER_SIZE, BloomFilter, FilterFormatError, atomic_write_bytes


def make_filter(n=1000, items=300):
    bf = BloomFilter(n, 0.01)
    for i in range(items):
        bf.add(f"fraud_txn_{i}")
    return bf


def test_header_is_27_bytes():
    assert HEADER_SIZE == 27


def test_layout_size():
    bf = make_filter()
    assert len(bf.to_bytes()) == 27 + len(bf.bits) + 4
    assert bf.to_bytes()[:4] == b"BLMF"


def test_round_trip_in_memory():
    bf = make_filter()
    bf2 = BloomFilter.from_bytes(bf.to_bytes())
    assert (bf2.size, bf2.num_hashes, bf2.count) == (bf.size, bf.num_hashes, bf.count)
    assert bf2.bits == bf.bits
    assert all(f"fraud_txn_{i}" in bf2 for i in range(300))
    assert bf2.fill_ratio() == bf.fill_ratio()


def test_loaded_filter_keeps_working():
    bf2 = BloomFilter.from_bytes(make_filter().to_bytes())
    bf2.add("new_key")
    assert "new_key" in bf2
    assert bf2.count == 301


def test_empty_filter_round_trip():
    bf = BloomFilter(100)
    assert BloomFilter.from_bytes(bf.to_bytes()).bits == bf.bits


def test_save_and_load_file(tmp_path):
    bf = make_filter()
    path = tmp_path / "filter_state.bin"
    bf.save(path)
    assert path.exists()
    assert not (tmp_path / "filter_state.bin.tmp").exists()
    bf2 = BloomFilter.load(path)
    assert bf2.bits == bf.bits and bf2.count == bf.count


def test_save_overwrites_existing(tmp_path):
    path = tmp_path / "f.bin"
    BloomFilter(100).save(path)
    bf = make_filter()
    bf.save(path)
    assert BloomFilter.load(path).count == 300


def test_failed_write_keeps_old_file(tmp_path, monkeypatch):
    path = tmp_path / "f.bin"
    atomic_write_bytes(path, b"old-good-data")

    def boom(src, dst):
        raise OSError("disk error")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_bytes(path, b"new-data")
    assert path.read_bytes() == b"old-good-data"
    assert not (tmp_path / "f.bin.tmp").exists()


def test_corrupted_payload_detected():
    data = bytearray(make_filter().to_bytes())
    data[HEADER_SIZE + 5] ^= 0xFF
    with pytest.raises(FilterFormatError, match="CRC32"):
        BloomFilter.from_bytes(bytes(data))


def test_corrupted_trailer_detected():
    data = bytearray(make_filter().to_bytes())
    data[-1] ^= 0x01
    with pytest.raises(FilterFormatError):
        BloomFilter.from_bytes(bytes(data))


def test_bad_magic():
    data = bytearray(make_filter().to_bytes())
    data[0:4] = b"XXXX"
    with pytest.raises(FilterFormatError, match="magic"):
        BloomFilter.from_bytes(bytes(data))


@pytest.mark.parametrize("offset,label", [(4, "version"), (5, "filter type"), (6, "hash scheme")])
def test_bad_header_fields(offset, label):
    data = bytearray(make_filter().to_bytes())
    data[offset] = 99
    with pytest.raises(FilterFormatError):
        BloomFilter.from_bytes(bytes(data))


def test_truncated_and_extended():
    data = make_filter().to_bytes()
    with pytest.raises(FilterFormatError):
        BloomFilter.from_bytes(data[:-10])
    with pytest.raises(FilterFormatError):
        BloomFilter.from_bytes(data + b"\x00")
    with pytest.raises(FilterFormatError):
        BloomFilter.from_bytes(data[:10])
    with pytest.raises(FilterFormatError):
        BloomFilter.from_bytes(b"")


def test_invalid_sizes_in_header():
    data = bytearray(make_filter().to_bytes())
    data[7:15] = struct.pack("<Q", 0)  # m = 0
    with pytest.raises(FilterFormatError):
        BloomFilter.from_bytes(bytes(data))
    data = bytearray(make_filter().to_bytes())
    data[15:19] = struct.pack("<I", 0)  # k = 0
    with pytest.raises(FilterFormatError):
        BloomFilter.from_bytes(bytes(data))


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        BloomFilter.load(tmp_path / "nope.bin")
