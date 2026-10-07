import os
import sqlite3
import sys
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

INITIAL_TEST_DIR = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = str(Path(INITIAL_TEST_DIR) / "expense_tracker_parser_test.db")
os.environ["BACKUP_DIR"] = str(Path(INITIAL_TEST_DIR) / "backups")
os.environ["FLASK_SECRET_KEY"] = "parser-test-secret"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as expense_app  # noqa: E402


class SmsImportParserTest(unittest.TestCase):
    def setUp(self):
        expense_app.app.config.update(TESTING=True)
        self.temp_dir = Path(tempfile.mkdtemp())
        expense_app.DATABASE = self.temp_dir / "expense_tracker_parser_test.db"
        expense_app.BACKUP_DIR = self.temp_dir / "backups"
        expense_app.init_db()
        self.client = expense_app.app.test_client()
        self.api_key = "parser-owner-key"
        self._set_owner_api_key()
        self._login_owner()

    def tearDown(self):
        self.client = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _connect(self):
        connection = sqlite3.connect(expense_app.DATABASE)
        connection.row_factory = sqlite3.Row
        return connection

    def _set_owner_api_key(self):
        connection = self._connect()
        connection.execute("UPDATE users SET api_key = ? WHERE id = 1", (self.api_key,))
        connection.commit()
        connection.close()

    def _login_owner(self):
        with self.client.session_transaction() as session:
            session.clear()
            session["logged_in"] = True
            session["user_id"] = 1

    def _parse_as_owner(self, raw_message):
        with expense_app.app.test_request_context("/"):
            expense_app.session["logged_in"] = True
            expense_app.session["user_id"] = 1
            return expense_app.parse_bhd_sms(raw_message)

    def _assess_as_owner(self, parsed):
        with expense_app.app.test_request_context("/"):
            expense_app.session["logged_in"] = True
            expense_app.session["user_id"] = 1
            return expense_app.assess_import_review(parsed)

    def _post_import(self, raw_message):
        return self.client.post(
            "/import-message",
            headers={"X-API-Key": self.api_key, "Accept": "application/json"},
            json={"raw_message": raw_message},
        )

    def _table_count(self, table_name, where_clause="", params=()):
        connection = self._connect()
        row = connection.execute(
            f"SELECT COUNT(*) AS count FROM {table_name} {where_clause}",
            params,
        ).fetchone()
        connection.close()
        return row["count"]

    def _fetch_one(self, query, params=()):
        connection = self._connect()
        row = connection.execute(query, params).fetchone()
        connection.close()
        return dict(row) if row else None

    def test_parse_bbk_bhd_card_purchase(self):
        raw_message = (
            "BBK: Your CARD ending in 1234 was used for BHD 4.250 at "
            "MCDONALDS HAMALA on JUN 02, 14:35. A/C bal BHD 100.000"
        )

        parsed = self._parse_as_owner(raw_message)

        self.assertEqual(parsed["amount"], 4.25)
        self.assertEqual(parsed["currency"], "BHD")
        self.assertEqual(parsed["merchant"], "MCDONALDS")
        self.assertEqual(parsed["category"], "Food")
        self.assertEqual(parsed["source"], "BBK SMS")
        self.assertEqual(parsed["date_text"], "JUN 02, 14:35")
        self.assertTrue(parsed["should_save_transaction"])
        datetime.strptime(parsed["date"], "%Y-%m-%d")

    def test_parse_bbk_foreign_currency_goes_to_review(self):
        raw_message = (
            "BBK: Your CARD ending in 1234 was used for USD 93.05 at "
            "OPENAI SAN FRANCISCO US on 02 JUN, 09:10. A/C bal BHD 50.000"
        )

        parsed = self._parse_as_owner(raw_message)
        review = self._assess_as_owner(parsed)

        self.assertEqual(parsed["amount"], 93.05)
        self.assertEqual(parsed["currency"], "USD")
        self.assertEqual(parsed["merchant"], "OPENAI SAN FRANCISCO")
        self.assertEqual(parsed["category"], "Education")
        self.assertFalse(parsed["should_save_transaction"])
        self.assertEqual(review["review_status"], "needs_review")
        self.assertIn("exchange-rate review", review["review_reason"])

    def test_parse_benefitpay_fawri_payment(self):
        raw_message = (
            "BenefitPay: Fawri+ payment of BHD 12.345 was credited to "
            "someone on 05/06/2026 at 18:07."
        )

        parsed = self._parse_as_owner(raw_message)

        self.assertEqual(parsed["amount"], 12.345)
        self.assertEqual(parsed["currency"], "BHD")
        self.assertEqual(parsed["merchant"], "BenefitPay")
        self.assertEqual(parsed["source"], "BenefitPay / Fawri+")
        self.assertTrue(parsed["should_save_transaction"])
        self.assertEqual(parsed["date"], "2026-06-05")

    def test_parse_fawri_incoming_credit_as_income(self):
        raw_message = (
            "Your account BH94BBKU00200XXXXXXX43 was credited by BHD3.900 "
            "from BH90ABCO56925XXXXXXX01 for Fawri+ on 12/06/2026 23:36 "
            "ref:ABCO260612200226.For help 17207777"
        )

        parsed = self._parse_as_owner(raw_message)
        review = self._assess_as_owner(parsed)

        self.assertEqual(parsed["amount"], 3.9)
        self.assertEqual(parsed["currency"], "BHD")
        self.assertEqual(parsed["merchant"], "Fawri+ received")
        self.assertEqual(parsed["category"], "Income")
        self.assertEqual(parsed["source"], "BenefitPay / Fawri+ received")
        self.assertEqual(parsed["date"], "2026-06-12")
        self.assertEqual(parsed["date_text"], "12/06/2026, 23:36")
        self.assertTrue(parsed["should_save_transaction"])
        self.assertTrue(review["should_auto_save"])

    def test_parse_fawri_incoming_credit_does_not_become_was_currency(self):
        raw_message = (
            "Your account BH94BBKU00200XXXXXXX43 was credited by BHD3.227 "
            "from BH72ABCO55927XXXXXXX01 for Fawri+ on 12/06/2026 23:35 "
            "ref:ABCO260612200096.For help 17207777"
        )

        parsed = self._parse_as_owner(raw_message)

        self.assertEqual(parsed["amount"], 3.227)
        self.assertEqual(parsed["currency"], "BHD")
        self.assertEqual(parsed["category"], "Income")
        self.assertNotEqual(parsed["currency"], "WAS")

    def test_import_endpoint_auto_saves_confident_bbk_bhd_message(self):
        raw_message = (
            "BBK: Your CARD ending in 1234 was used for BHD 8.000 at "
            "TALABAT BAHRAIN on JUN 03, 20:15. A/C bal BHD 44.000"
        )

        response = self._post_import(raw_message)
        data = response.get_json()

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(data["success"])
        self.assertTrue(data["saved_transaction"])
        self.assertEqual(data["merchant"], "TALABAT")
        self.assertEqual(data["review_status"], "auto_saved")
        self.assertEqual(self._table_count("transactions"), 1)
        self.assertEqual(self._table_count("imported_messages"), 1)

    def test_import_endpoint_auto_saves_fawri_incoming_credit_as_income(self):
        raw_message = (
            "Your account BH94BBKU00200XXXXXXX43 was credited by BHD3.900 "
            "from BH90ABCO56925XXXXXXX01 for Fawri+ on 12/06/2026 23:36 "
            "ref:ABCO260612200226.For help 17207777"
        )

        response = self._post_import(raw_message)
        data = response.get_json()
        transaction = self._fetch_one("SELECT * FROM transactions LIMIT 1")

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(data["success"])
        self.assertTrue(data["saved_transaction"])
        self.assertEqual(data["amount"], 3.9)
        self.assertEqual(data["merchant"], "Fawri+ received")
        self.assertEqual(data["category"], "Income")
        self.assertEqual(transaction["category"], "Income")
        self.assertEqual(transaction["amount"], 3.9)

    def test_import_endpoint_queues_foreign_currency_without_transaction(self):
        raw_message = (
            "BBK: Your CARD ending in 1234 was used for USD 19.990 at "
            "OPENAI US on JUN 04, 08:00. A/C bal BHD 30.000"
        )

        response = self._post_import(raw_message)
        data = response.get_json()

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(data["success"])
        self.assertFalse(data["saved_transaction"])
        self.assertEqual(data["currency"], "USD")
        self.assertEqual(data["review_status"], "needs_review")
        self.assertEqual(self._table_count("transactions"), 0)
        self.assertEqual(
            self._table_count(
                "imported_messages",
                "WHERE parsed_currency = 'USD' AND transaction_id IS NULL",
            ),
            1,
        )

    def test_reviewed_bhd_import_save_creates_user_owned_transaction(self):
        import_id = self._insert_review_import(currency="BHD", amount=3.3)

        response = self.client.post(
            f"/api/imports/{import_id}/save-bhd",
            headers={"X-API-Key": self.api_key},
        )
        data = response.get_json()

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(data["success"])
        transaction = self._fetch_one(
            "SELECT * FROM transactions WHERE id = ?",
            (data["transaction"]["id"],),
        )
        self.assertEqual(transaction["user_id"], 1)
        self.assertEqual(transaction["amount"], 3.3)
        self.assertEqual(transaction["merchant"], "VOLUME SALON AND SPA")

    def test_foreign_currency_conversion_creates_user_owned_transaction(self):
        import_id = self._insert_review_import(currency="USD", amount=10.0)

        response = self.client.post(
            f"/api/imports/{import_id}/convert-currency",
            headers={"X-API-Key": self.api_key},
            json={"exchange_rate": 0.376},
        )
        data = response.get_json()

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(data["success"])
        transaction = self._fetch_one(
            "SELECT * FROM transactions WHERE id = ?",
            (data["transaction"]["id"],),
        )
        self.assertEqual(transaction["user_id"], 1)
        self.assertAlmostEqual(transaction["amount"], 3.76)

    def test_imports_api_returns_sar_default_rate(self):
        response = self.client.get("/api/imports")
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["default_currency_to_bhd_rates"]["SAR"], 0.1005)

    def test_sar_conversion_uses_sar_rate_when_provided(self):
        import_id = self._insert_review_import(currency="SAR", amount=330.3)

        response = self.client.post(
            f"/api/imports/{import_id}/convert-currency",
            headers={"X-API-Key": self.api_key},
            json={"exchange_rate": 0.1005},
        )
        data = response.get_json()
        transaction = self._fetch_one(
            "SELECT * FROM transactions WHERE id = ?",
            (data["transaction"]["id"],),
        )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(data["success"])
        self.assertEqual(transaction["user_id"], 1)
        self.assertAlmostEqual(transaction["amount"], 33.19515)

    def test_database_rejects_new_ownerless_transactions(self):
        connection = self._connect()

        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO transactions (date, amount, merchant, category, source, created_at)
                VALUES ('2026-06-10', 3.3, 'OWNERLESS', 'Other', 'Test', '2026-06-10 12:00:00')
                """
            )

        connection.close()

    def test_import_endpoint_records_duplicate_message(self):
        raw_message = (
            "BBK: Your CARD ending in 1234 was used for BHD 2.500 at "
            "MCDONALDS BAHRAIN on JUN 05, 12:00. A/C bal BHD 28.000"
        )

        first_response = self._post_import(raw_message)
        second_response = self._post_import(raw_message)
        data = second_response.get_json()

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(data["duplicate"])
        self.assertEqual(self._table_count("transactions"), 1)
        self.assertEqual(self._table_count("imported_messages"), 2)
        self.assertEqual(
            self._table_count("imported_messages", "WHERE is_duplicate = 1"),
            1,
        )

    def _insert_review_import(self, currency, amount):
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
                parsed_date_text,
                parsed_description,
                review_status,
                review_reason,
                parser_confidence,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, 'VOLUME SALON AND SPA', 'Other', '2026-06-10',
                    'JUN 10, 11:00', 'Sanitized reviewed import', 'needs_review',
                    'Test reviewed import.', 1, ?)
            """,
            (
                1,
                f"Reviewed {currency} import {amount}",
                f"review-{currency}-{amount}-{created_at}",
                amount,
                currency,
                created_at,
            ),
        )
        import_id = cursor.lastrowid
        connection.commit()
        connection.close()
        return import_id

    def test_import_endpoint_records_failed_unrecognized_message(self):
        response = self._post_import("Your statement is ready. No transaction amount here.")
        data = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertFalse(data["success"])
        self.assertEqual(data["error"], "No BHD amount was found.")
        self.assertEqual(self._table_count("transactions"), 0)
        self.assertEqual(
            self._table_count("imported_messages", "WHERE review_status = 'failed'"),
            1,
        )

    def test_learned_rule_replays_similar_message_without_ai(self):
        example_message = (
            "Card alert: Purchase BHD 7.500 at LOCAL CAFE on 2026-06-06 ref 111"
        )
        parsed = {
            "amount": 7.5,
            "currency": "BHD",
            "merchant": "LOCAL CAFE",
            "category": "Food",
            "date_text": "2026-06-06",
        }

        with expense_app.app.test_request_context("/"):
            expense_app.session["logged_in"] = True
            expense_app.session["user_id"] = 1
            rule_id = expense_app.save_learned_sms_rule(example_message, parsed)
            replay = expense_app.parse_with_learned_sms_rules(
                "Card alert: Purchase BHD 9.250 at LOCAL CAFE on 2026-06-07 ref 222"
            )

        self.assertIsNotNone(rule_id)
        self.assertEqual(replay["amount"], 9.25)
        self.assertEqual(replay["currency"], "BHD")
        self.assertEqual(replay["merchant"], "LOCAL CAFE")
        self.assertEqual(replay["category"], "Food")
        self.assertEqual(replay["date"], "2026-06-07")
        self.assertTrue(replay["should_save_transaction"])


if __name__ == "__main__":
    unittest.main()
