from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import sqlite3

import pytest

from personalkb.model_budget import (BudgetRevisionConflict, budget_entries, budget_snapshot,
                                    record_estimate, update_budget_limit)
from tools.api_smoke import reserve


def test_existing_ledger_and_shared_override(tmp_path):
    path = tmp_path / 'budget.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE reservations (request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, amount TEXT NOT NULL)')
        db.execute('INSERT INTO reservations VALUES (?,?,?)', ('old', 'task', '99.44'))
    assert budget_snapshot(path, '100')['available_cny'] == '0.56'
    assert budget_entries(path)[0]['estimated_cost_cny'] is None
    with pytest.raises(ValueError):
        reserve(path, 'new', 'new', '1', '5', '100')
    result = update_budget_limit(path, '100', '150.00', 0)
    assert result['revision'] == 1
    reserve(path, 'new', 'new', '1', '5', '100')
    with pytest.raises(ValueError):
        reserve(path, 'new', 'over-run-limit', '4.01', '5', '100')
    assert budget_snapshot(path, '100')['reserved_cny'] == '100.44'
    record_estimate(path, 'new', '0.012345')
    assert budget_entries(path)[0]['reserved_limit_cny'] == '1'
    assert budget_entries(path)[0]['estimated_cost_cny'] == '0.012345'
    snapshot = budget_snapshot(path, '100', include_entries=True)
    assert snapshot['entries'] == budget_entries(path)
    assert sum(Decimal(entry['reserved_cny']) for entry in snapshot['entries']) == Decimal(snapshot['reserved_cny'])
    with pytest.raises(BudgetRevisionConflict):
        update_budget_limit(path, '100', '200', 0)
    result = update_budget_limit(path, '100', '50', 1)
    assert result['available_cny'] == '0'
    assert len(result['changes']) == 2


def test_reconciling_charge_keeps_original_reservation_limit(tmp_path):
    path = tmp_path / 'budget.sqlite'
    reserve(path, 'run', 'step', '1.25', '2', '100')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE reservations SET amount='0.13' WHERE request_id='step'")
    record_estimate(path, 'step', '0.13')
    entry, = budget_entries(path)
    assert (entry['reserved_limit_cny'],entry['reserved_cny'],entry['estimated_cost_cny']) == ('1.25','0.13','0.13')


def test_lowering_budget_blocks_new_reservations_without_blocking_reuse(tmp_path):
    from personalkb.video_pipeline import _preflight
    from personalkb.workflow_store import WorkflowError

    path = tmp_path / 'budget.sqlite'
    config = {'budget': {'ledger': str(path), 'research_limit': '100', 'run_limit': '5'}}
    reserve(path, 'task', 'task:text', '0.7', '5', '100')
    reserve(path, 'task', 'task:text:retry:1', '0.7', '5', '100')
    update_budget_limit(path, '100', '1.00', 0)
    amounts = {'text': Decimal('0.7')}
    _preflight(None, 'task', config, amounts, retries={'text': 1})
    _preflight(None, 'task', config, amounts, restored={'text'})
    with pytest.raises(WorkflowError, match='budget_invalid_or_exceeded'):
        _preflight(None, 'task', config, amounts, retries={'text': 2})


@pytest.mark.parametrize('value', ['0', '-1', 'NaN', 'Infinity', '1.001', True, None])
def test_invalid_limits(tmp_path, value):
    with pytest.raises(ValueError):
        update_budget_limit(tmp_path / 'ledger.sqlite', '100', value, 0)


def test_concurrent_updates_and_reservations(tmp_path):
    path = tmp_path / 'budget.sqlite'
    update_budget_limit(path, '100', '1.00', 0)
    def attempt(index):
        try:
            reserve(path, str(index), str(index), '0.60', '1', '100')
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, range(2))) == [False, True]
    assert Decimal(budget_snapshot(path, '100')['reserved_cny']) == Decimal('0.60')
