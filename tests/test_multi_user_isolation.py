import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


TEST_DIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = str(Path(TEST_DIR.name) / "expense_tracker_test.db")
os.environ["BACKUP_DIR"] = str(Path(TEST_DIR.name) / "backups")
os.environ["FLASK_SECRET_KEY"] = "test-secret"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as expense_app  # noqa: E402


class MultiUserIsolationTest(unittest.TestCase):
    def setUp(self):
        expense_app.app.config.update(TESTING=True)
        if expense_app.DATABASE.exists():
            expense_app.DATABASE.unlink()
        expense_app.init_db()
        self.client = expense_app.app.test_client()
        self.owner_id = 1
        self.owner_key = self._set_owner_api_key()
        self.friend_id, self.friend_key = self._create_user("friend")

    def tearDown(self):
        self.client = None

    def _connect(self):
        connection = sqlite3.connect(expense_app.DATABASE)
        connection.row_factory = sqlite3.Row
        return connection

    def _set_owner_api_key(self):
        api_key = "owner-test-key"
        connection = self._connect()
        connection.execute("UPDATE users SET api_key = ? WHERE id = 1", (api_key,))
        connection.commit()
        connection.close()
        return api_key

    def _create_user(self, username):
        api_key = f"{username}-test-key"
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        connection = self._connect()
        cursor = connection.execute(
            """
            INSERT INTO users (
                username, display_name, password_hash, api_key, is_admin, active, created_at
            )
            VALUES (?, ?, 'hash', ?, 0, 1, ?)
            """,
            (username, username.title(), api_key, created_at),
        )
        user_id = cursor.lastrowid
        connection.commit()
        connection.close()
        return user_id, api_key

    def _login_session(self, user_id):
        with self.client.session_transaction() as session:
            session.clear()
            session["logged_in"] = True
            session["user_id"] = user_id

    def _insert_transaction(self, user_id, merchant, amount=4.5, category="Other"):
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        connection = self._connect()
        cursor = connection.execute(
            """
            INSERT INTO transactions (
                user_id, date, amount, merchant, category, source, created_at
            )
            VALUES (?, '2026-06-01', ?, ?, ?, 'Manual', ?)
            """,
            (user_id, amount, merchant, category, created_at),
        )
        transaction_id = cursor.lastrowid
        connection.commit()
        connection.close()
        return transaction_id

    def _insert_import(self, user_id, merchant="Foreign Shop", currency="USD"):
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        connection = self._connect()
        cursor = connection.execute(
            """
            INSERT INTO imported_messages (
                user_id,
                raw_message,
                message_hash,
                parsed_amount,
                parsed_currency,
                parsed_merchant,
                parsed_category,
                parsed_date,
                created_at
            )
            VALUES (?, ?, ?, 10.0, ?, ?, 'Other', '2026-06-01', ?)
            """,
            (
                user_id,
                f"Test SMS for {merchant}",
                f"hash-{user_id}-{merchant}-{currency}",
                currency,
                merchant,
                created_at,
            ),
        )
        import_id = cursor.lastrowid
        connection.commit()
        connection.close()
        return import_id

    def _row_count(self, table_name, where_clause="", params=()):
        connection = self._connect()
        row = connection.execute(
            f"SELECT COUNT(*) AS count FROM {table_name} {where_clause}",
            params,
        ).fetchone()
        connection.close()
        return row["count"]

    def test_user_cannot_see_another_users_transactions(self):
        self._insert_transaction(self.owner_id, "Owner Only")
        self._insert_transaction(self.friend_id, "Friend Only")
        self._login_session(self.friend_id)

        response = self.client.get("/api/transactions?month=2026-06")

        self.assertEqual(response.status_code, 200)
        merchants = {row["merchant"] for row in response.get_json()["transactions"]}
        self.assertIn("Friend Only", merchants)
        self.assertNotIn("Owner Only", merchants)

    def test_dashboard_reports_net_spent_after_money_in(self):
        self._insert_transaction(self.owner_id, "Restaurant", amount=20, category="Food")
        self._insert_transaction(
            self.owner_id,
            "Friend paid back",
            amount=12,
            category="Income",
        )
        self._login_session(self.owner_id)

        response = self.client.get("/api/dashboard?month=2026-06")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["total_expenses"], 20)
        self.assertEqual(data["total_income"], 12)
        self.assertEqual(data["net_spent"], 8)
        expected_prediction = (
            (8 / datetime.today().day) * data["selected_month"]["days_in_month"]
            if data["selected_month"]["is_current"]
            else 8
        )
        self.assertAlmostEqual(data["monthly_prediction"], expected_prediction)
        self.assertEqual(data["spending_by_category"][0]["gross_total"], 20)
        self.assertEqual(data["spending_by_category"][0]["total"], 8)
        calendar_day = next(
            day for day in data["calendar_spending"]["days"] if day["date"] == "2026-06-01"
        )
        self.assertEqual(calendar_day["total"], 8)

    def test_config_defaults_to_latest_month_when_current_month_is_empty(self):
        self._insert_transaction(self.owner_id, "June Transaction")
        self._login_session(self.owner_id)

        response = self.client.get("/api/config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["default_dashboard_month"], "2026-06")

    def test_user_cannot_edit_or_delete_another_users_transaction(self):
        transaction_id = self._insert_transaction(self.owner_id, "Owner Protected")
        self._login_session(self.friend_id)

        edit_response = self.client.put(
            f"/api/transactions/{transaction_id}",
            headers={"X-API-Key": self.friend_key},
            json={
                "date": "2026-06-02",
                "amount": 99,
                "merchant": "Changed",
                "category": "Food",
                "source": "Manual",
            },
        )
        delete_response = self.client.delete(
            f"/api/transactions/{transaction_id}",
            headers={"X-API-Key": self.friend_key},
        )

        self.assertEqual(edit_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)
        connection = self._connect()
        row = connection.execute(
            "SELECT merchant FROM transactions WHERE id = ?",
            (transaction_id,),
        ).fetchone()
        connection.close()
        self.assertEqual(row["merchant"], "Owner Protected")

    def test_user_cannot_delete_or_save_another_users_import(self):
        import_id = self._insert_import(self.owner_id, currency="BHD")
        self._login_session(self.friend_id)

        delete_response = self.client.delete(
            f"/api/imports/{import_id}",
            headers={"X-API-Key": self.friend_key},
        )
        save_response = self.client.post(
            f"/api/imports/{import_id}/save-bhd",
            headers={"X-API-Key": self.friend_key},
        )

        self.assertEqual(delete_response.status_code, 404)
        self.assertEqual(save_response.status_code, 404)
        self.assertEqual(
            self._row_count("imported_messages", "WHERE id = ?", (import_id,)),
            1,
        )
        self.assertEqual(
            self._row_count(
                "transactions",
                "WHERE user_id = ? AND merchant = 'Foreign Shop'",
                (self.friend_id,),
            ),
            0,
        )

    def test_same_rule_and_budget_names_are_allowed_per_user(self):
        for user_id, api_key, category in (
            (self.owner_id, self.owner_key, "Food"),
            (self.friend_id, self.friend_key, "Transport"),
        ):
            self._login_session(user_id)
            response = self.client.post(
                "/api/category-rules",
                headers={"X-API-Key": api_key},
                json={"keyword": "SHARED MERCHANT", "category": category},
            )
            self.assertEqual(response.status_code, 201, response.get_data(as_text=True))

        for user_id, api_key, limit in (
            (self.owner_id, self.owner_key, 100),
            (self.friend_id, self.friend_key, 200),
        ):
            self._login_session(user_id)
            response = self.client.post(
                "/api/budgets",
                headers={"X-API-Key": api_key},
                json={
                    "monthly_budget_limit": limit,
                    "category_budgets": {"Food": limit},
                },
            )
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

        self.assertEqual(
            self._row_count("category_rules", "WHERE keyword = 'SHARED MERCHANT'"),
            2,
        )
        self.assertEqual(self._row_count("category_budgets", "WHERE category = 'Food'"), 2)

    def test_non_admin_settings_health_hides_admin_fields(self):
        self._login_session(self.friend_id)

        response = self.client.get("/api/settings/health")
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["permissions"]["is_admin"])
        self.assertFalse(data["permissions"]["can_manage_backups"])
        self.assertNotIn("backup_download_url", data)
        self.assertNotIn("backup_history", data)
        self.assertNotIn("deployment_readiness", data)
        self.assertNotIn("database_file", data)
        self.assertIsNone(data["multi_user"]["active_user_count"])
        self.assertIsNone(data["multi_user"]["pending_invite_count"])

    def test_non_admin_cannot_call_backup_apis(self):
        self._login_session(self.friend_id)

        create_response = self.client.post(
            "/api/backups/create",
            headers={"X-API-Key": self.friend_key},
        )
        restore_response = self.client.post(
            "/api/backups/restore",
            headers={"X-API-Key": self.friend_key},
        )
        download_response = self.client.get(
            f"/backup/download?api_key={self.friend_key}",
        )

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(restore_response.status_code, 403)
        self.assertEqual(download_response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
