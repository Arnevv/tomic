import pytest
from tomic.strategies.utils import validate_width_list


def test_validate_width_list_accepts_scalar():
    assert validate_width_list(1.0, "k") == [1.0]


def test_validate_width_list_accepts_dict():
    d = {"sigma": 1.0}
    assert validate_width_list(d, "k") == [d]


def test_validate_width_list_rejects_none():
    with pytest.raises(ValueError):
        validate_width_list(None, "k")
