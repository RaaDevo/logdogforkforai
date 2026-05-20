from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from routes.logs import _validate_table_allowlist


def test_allowlist_alias_join_passes() -> None:
    sql = "SELECT a.id FROM app_logs a JOIN app_events e ON a.id = e.log_id"
    err = _validate_table_allowlist(sql, {"app_logs", "app_events"})
    assert err is None


def test_allowlist_cte_passes() -> None:
    sql = """
    WITH recent AS (
      SELECT id, level FROM app_logs
    )
    SELECT r.id FROM recent r
    """
    err = _validate_table_allowlist(sql, {"app_logs"})
    assert err is None


def test_allowlist_nested_select_passes() -> None:
    sql = "SELECT id FROM (SELECT id FROM app_logs) s"
    err = _validate_table_allowlist(sql, {"app_logs"})
    assert err is None


def test_allowlist_disallowed_table_in_subquery_fails() -> None:
    sql = "SELECT id FROM (SELECT id FROM secret_logs) s"
    err = _validate_table_allowlist(sql, {"app_logs"})
    assert err is not None
    assert "secret_logs" in err


def test_allowlist_rejects_multi_statement_sql() -> None:
    sql = "SELECT id FROM app_logs; SELECT id FROM app_events;"
    err = _validate_table_allowlist(sql, {"app_logs", "app_events"})
    assert err == "Query must contain exactly one SQL statement."
