"""Pure recurrence/config contracts, independent of database availability."""
import random
import pytest
from dnfgm.config import Settings
from dnfgm.schedules import missed, next_due


def test_misfire_ranges_match_bounded_reference_enumeration():
    random.seed(20261105)
    for _ in range(1000):
        interval = random.choice((86400, 604800))
        due = 1790000000 + random.randrange(1000)
        now = due + random.randrange(100 * interval) + 301
        end = due + random.randrange(100) * interval if random.randrange(2) else None
        definition = {'recurrence': 'daily' if interval == 86400 else 'weekly', 'end_at': end}
        expected, value = [], due
        while value < now - 300 and (end is None or value <= end):
            expected.append(value)
            value += interval
        count, last, following = missed(definition, due, now)
        assert count == len(expected) and last == expected[-1]
        assert following == (value if end is None or value <= end else None)


@pytest.mark.parametrize('enabled', [True, False])
def test_schedule_flag_accepts_only_explicit_booleans(enabled):
    s = Settings(secret='s' * 48, db_password='synthetic', schedule_worker_enabled=enabled)
    assert s.check().schedule_worker_enabled is enabled


@pytest.mark.parametrize('enabled', [1, 0, 'true', None])
def test_schedule_flag_rejects_truthy_or_null_configuration(enabled):
    s = Settings(secret='s' * 48, db_password='synthetic', schedule_worker_enabled=enabled)
    with pytest.raises(ValueError, match='Schedule worker enabled'):
        s.check()
