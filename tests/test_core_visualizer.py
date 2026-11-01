import pytest

from core.hashing import hash_indexes
from core.visualizer import MAX_WORDS, TeachingFilter, find_false_positive


def loaded(m=128, k=3, words=("hello", "world", "sun")):
    tf = TeachingFilter(m, k)
    for w in words:
        tf.insert(w)
    return tf


@pytest.mark.parametrize("m,k", [(15, 3), (513, 3), (128, 0), (128, 9), (12.5, 3), (128, 2.5)])
def test_invalid_parameters(m, k):
    with pytest.raises(ValueError):
        TeachingFilter(m, k)


def test_state_of_new_filter():
    st = TeachingFilter(128, 3).state()
    assert st == {"m": 128, "k": 3, "bits": "0" * 128}


def test_insert_uses_real_hashing_and_sets_bits():
    tf = TeachingFilter(128, 3)
    out = tf.insert("hello")
    assert out["indexes"] == hash_indexes("hello", 128, 3)
    assert out["duplicate"] is False
    assert len(out["bits"]) == 128
    for i in out["indexes"]:
        assert out["bits"][i] == "1"
    assert out["bits"].count("1") == len(set(out["indexes"]))


def test_query_inserted_is_probable_never_false_negative():
    tf = TeachingFilter(512, 3)
    words = [f"word{i}" for i in range(60)]
    for w in words:
        tf.insert(w)
    for w in words:
        q = tf.query(w)
        assert q["result"] == "PROBABLE" and q["truly_inserted"] and not q["false_positive"]
        assert q["bit_values"] == [1] * 3


def test_query_absent_message_names_first_zero_bit():
    tf = loaded()
    for i in range(500):
        q = tf.query(f"unseen{i}")
        if q["result"] == "ABSENT":
            first_zero = q["indexes"][q["bit_values"].index(0)]
            assert q["message"] == f"Bit {first_zero} is 0 -> DEFINITELY NOT PRESENT"
            assert 0 in q["bit_values"] and not q["false_positive"]
            return
    raise AssertionError("no absent word found")


def test_query_probable_message():
    q = loaded().query("hello")
    assert q["message"] == "All 3 bits are 1 -> PROBABLY PRESENT"


def test_empty_filter_everything_absent():
    q = TeachingFilter().query("hello")
    assert q["result"] == "ABSENT" and q["bit_values"] == [0, 0, 0] and q["explained_by"] == {}


def test_explained_by_names_first_setter():
    tf = TeachingFilter(32, 3)
    first = tf.insert("alpha")
    idx_alpha = set(first["indexes"])
    # find a later word that shares a bit with alpha
    shared = next(w for w in (f"w{i}" for i in range(10_000))
                  if idx_alpha & set(hash_indexes(w, 32, 3)))
    tf.insert(shared)
    overlap = idx_alpha & set(hash_indexes(shared, 32, 3))
    explained = tf.explain(shared)
    for i in overlap:
        assert explained[str(i)] == "alpha"       # first setter wins
    for i in set(hash_indexes(shared, 32, 3)) - idx_alpha:
        assert explained[str(i)] == shared


def test_duplicate_insert_is_ignored():
    tf = TeachingFilter()
    tf.insert("hello")
    bits = tf.bits_string()
    again = tf.insert("hello")
    assert again["duplicate"] is True
    assert tf.bits_string() == bits and tf.words == ["hello"]


def test_items_are_trimmed():
    tf = TeachingFilter()
    tf.insert("  hello ")
    assert tf.query("hello")["truly_inserted"] is True
    assert tf.words == ["hello"]


@pytest.mark.parametrize("bad", ["", "   ", "x" * 3000])
def test_bad_items_rejected(bad):
    tf = TeachingFilter()
    with pytest.raises(ValueError):
        tf.insert(bad)
    with pytest.raises(ValueError):
        tf.query(bad)


def test_word_limit():
    tf = TeachingFilter(512, 3)
    for i in range(MAX_WORDS):
        tf.insert(f"w{i}")
    with pytest.raises(ValueError, match="full"):
        tf.insert("one-too-many")
    assert tf.insert("w0")["duplicate"] is True    # known words are still fine


def test_find_false_positive_found_and_explained():
    tf = loaded()
    out = tf.find_false_positive(seed=1)
    assert out["found"] is True
    word = out["item"]
    assert word not in tf.words
    assert out["tries"] >= 1
    bits = out["bits"]
    assert all(bits[i] == "1" for i in out["indexes"])          # every bit already set
    assert set(out["explained_by"]) == {str(i) for i in out["indexes"]}
    for idx, owner in out["explained_by"].items():              # the explanation is true
        assert owner in tf.words
        assert int(idx) in hash_indexes(owner, 128, 3)
    q = tf.query(word)
    assert q["result"] == "PROBABLE" and q["false_positive"] is True


def test_find_false_positive_reproducible_with_seed():
    a = loaded().find_false_positive(seed=5)
    b = loaded().find_false_positive(seed=5)
    assert (a["item"], a["tries"]) == (b["item"], b["tries"])


def test_find_false_positive_on_empty_filter():
    out = TeachingFilter().find_false_positive()
    assert out["found"] is False and out["item"] is None and out["tries"] == 0
    assert "Insert some words" in out["message"]


def test_find_false_positive_gives_up():
    tf = loaded(m=512, k=3, words=("only",))
    out = tf.find_false_positive(max_tries=5, seed=1)
    assert out["found"] is False and out["tries"] == 5
    assert "No false positive found" in out["message"]


@pytest.mark.parametrize("bad", [0, -1, 1_000_001, 2.5, "10"])
def test_max_tries_validation(bad):
    with pytest.raises(ValueError):
        loaded().find_false_positive(max_tries=bad)


def test_module_function_excludes_inserted_words():
    tf = loaded()
    word, tries = find_false_positive(tf.bf, set(tf.words), seed=3)
    assert word is not None and word not in tf.words and word in tf.bf and tries >= 1


def test_tiny_filter_with_duplicate_indexes_works():
    tf = TeachingFilter(16, 8)      # k=8 on 16 bits: hash positions can repeat
    tf.insert("a")
    assert tf.query("a")["result"] == "PROBABLE"
