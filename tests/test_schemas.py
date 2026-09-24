from datetime import date

import pytest
from pydantic import ValidationError

from koffito.schemas.me import ProfileUpdate, adult_cutoff


def test_adult_cutoff_handles_leap_day():
    assert adult_cutoff(date(2028, 2, 29)) == date(2010, 2, 28)
    assert adult_cutoff(date(2026, 9, 24)) == date(2008, 9, 24)


def test_profile_update_rejects_minors_and_accepts_adults():
    with pytest.raises(ValidationError):
        ProfileUpdate(date_of_birth=date(2015, 1, 1))
    assert ProfileUpdate(date_of_birth=date(1990, 5, 5)).date_of_birth == date(1990, 5, 5)
