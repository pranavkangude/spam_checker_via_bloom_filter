import pytest

from core.params import MAX_M_BITS, bits_per_item, fp_rate, optimal_k, optimal_m


def test_known_values_1m_1pct():
    m = optimal_m(1_000_000, 0.01)
    assert m == 9_585_059
    assert optimal_k(m, 1_000_000) == 7


def test_bits_per_item():
    m = optimal_m(1_000_000, 0.01)
    assert bits_per_item(m, 1_000_000) == pytest.approx(9.585, abs=0.001)


def test_fp_rate_close_to_target():
    n, p = 1_000_000, 0.01
    m = optimal_m(n, p)
    k = optimal_k(m, n)
    assert fp_rate(m, n, k) == pytest.approx(p, rel=0.05)


def test_fp_rate_empty_filter_is_zero():
    assert fp_rate(1000, 0, 5) == 0.0


def test_fp_rate_grows_with_n():
    assert fp_rate(10_000, 500, 5) < fp_rate(10_000, 2000, 5)


def test_optimal_k_at_least_one():
    assert optimal_k(10, 1000) == 1


def test_small_n():
    assert optimal_m(1, 0.5) >= 1


@pytest.mark.parametrize("n,p", [(0, 0.01), (-5, 0.01), (10, 0), (10, 1), (10, 1.5), (10, -0.1)])
def test_invalid_inputs(n, p):
    with pytest.raises(ValueError):
        optimal_m(n, p)


def test_non_integer_n_rejected():
    with pytest.raises(ValueError):
        optimal_m(10.5, 0.01)


def test_size_cap():
    with pytest.raises(ValueError):
        optimal_m(10 ** 12, 0.01)
    assert optimal_m(10 ** 6, 0.01) <= MAX_M_BITS
