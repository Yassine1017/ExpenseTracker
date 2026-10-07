import csv
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    make_response,
    redirect,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.getenv("DATABASE_PATH", BASE_DIR / "expense_tracker.db")).resolve()
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", BASE_DIR / "backups")).resolve()
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
APP_VERSION = "3.8"
SESSION_SECRET_FILE = BASE_DIR / ".flask_session_secret"

if os.getenv("FLASK_SECRET_KEY"):
    app.secret_key = os.getenv("FLASK_SECRET_KEY")
elif SESSION_SECRET_FILE.exists():
    app.secret_key = SESSION_SECRET_FILE.read_text(encoding="utf-8").strip()
else:
    app.secret_key = secrets.token_urlsafe(32)
    SESSION_SECRET_FILE.write_text(app.secret_key, encoding="utf-8")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
)

# These categories are used in the add form and in the dashboard summary.
CATEGORIES = [
    "Food",
    "Transport",
    "Shopping",
    "Bills",
    "Entertainment",
    "Health",
    "Education",
    "Other",
    "Income",
]

# Default setting values are used only when the settings table is empty.
DEFAULT_MONTHLY_BUDGET_LIMIT = 300.0
HIGH_TRANSACTION_LIMIT = 50.0
DEFAULT_USD_TO_BHD_RATE = 0.376
DEFAULT_CURRENCY_TO_BHD_RATES = {
    "USD": DEFAULT_USD_TO_BHD_RATE,
    "SAR": 0.1005,
}
OPENAI_CATEGORY_MODEL = os.getenv("OPENAI_CATEGORY_MODEL", "gpt-5-mini")
OPENAI_SMS_MODEL = os.getenv("OPENAI_SMS_MODEL", OPENAI_CATEGORY_MODEL)

DEFAULT_CATEGORY_RULES = [
    ("MCDONALDS", "Food"),
    ("OPENAI", "Education"),
    ("TALABAT", "Food"),
    ("UBER", "Transport"),
    ("PETROL", "Transport"),
]

DEFAULT_MERCHANT_ALIASES = [
    ("OPENAI", "OpenAI / ChatGPT"),
    ("MCDONALDS", "McDonald's"),
    ("TALABAT", "Talabat"),
    ("NETFLIX", "Netflix"),
    ("BENEFITPAY", "BenefitPay"),
]

CATEGORY_COLORS = {
    "Food": "#2563eb",
    "Transport": "#16a34a",
    "Shopping": "#db2777",
    "Bills": "#f97316",
    "Entertainment": "#7c3aed",
    "Health": "#dc2626",
    "Education": "#0891b2",
    "Other": "#64748b",
}

# This pattern supports messages like "BHD 4.250", "USD 93.05", and "4.250 BHD".
CURRENCY_AMOUNT_PATTERN = re.compile(
    r"(?:\b([A-Z]{3})\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?))|(?:([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*([A-Z]{3})\b)",
    re.IGNORECASE,
)

BBK_CARD_PATTERN = re.compile(
    r"for\s+([A-Z]{3})\s+([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s+at\s+(.+?)\s+on\s+([A-Z]{3}\s+\d{1,2}|\d{1,2}\s+[A-Z]{3}),?\s+(\d{1,2}:\d{2})",
    re.IGNORECASE,
)
BBK_AT_THEN_AMOUNT_PATTERN = re.compile(
    r"at\s+(.+?)\s+for\s+([A-Z]{3})\s+([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s+on\s+([A-Z]{3}\s+\d{2}|\d{2}\s+[A-Z]{3}),?\s+(\d{2}:\d{2})",
    re.IGNORECASE,
)
BBK_DATE_TIME_PATTERN = re.compile(
    r"\bon\s+([A-Z]{3}\s+\d{1,2}|\d{1,2}\s+[A-Z]{3})(?:\s+\d{4})?,?\s+(\d{1,2}:\d{2})",
    re.IGNORECASE,
)
BBK_MERCHANT_PATTERN = re.compile(
    r"\bat\s+(.+?)\s+on\s+([A-Z]{3}\s+\d{1,2}|\d{1,2}\s+[A-Z]{3})(?:\s+\d{4})?,?\s+\d{1,2}:\d{2}",
    re.IGNORECASE,
)
FAWRI_PAYMENT_PATTERN = re.compile(
    r"Fawri\+\s+payment\s+of\s+([A-Z]{3})\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s+was\s+credited\s+to\s+.+?\s+on\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})(?:\s+at\s+(\d{1,2}:\d{2}))?",
    re.IGNORECASE,
)
FAWRI_INCOMING_CREDIT_PATTERN = re.compile(
    r"account\s+\S+\s+was\s+credited\s+by\s+([A-Z]{3})\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s+from\s+\S+\s+for\s+Fawri\+\s+on\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+(\d{1,2}:\d{2})",
    re.IGNORECASE,
)
CARD_ENDING_PATTERN = re.compile(
    r"(CARD\s+ending\s+in\s+)(\S+)",
    re.IGNORECASE,
)
ACCOUNT_BALANCE_PATTERN = re.compile(
    r"(A/C\s+bal\s+)([A-Z]{3}\s+)?([0-9,]+(?:\.[0-9]+)?|x+)",
    re.IGNORECASE,
)
LOCATION_TERMS = [
    "AL HAMALA",
    "HAMAD TOWN",
    "ISA TOWN",
    "DIPLOMATIC AREA",
    "SEEF",
    "MANAMA",
    "MUHARRAQ",
    "RIFFA",
    "SITRA",
    "BUDAYA",
    "JANABIYA",
    "JUFFAIR",
    "AMWAJ",
    "DIYAR",
    "DILMUNIA",
    "HIDD",
    "GALALI",
    "HAMALA",
    "ZALLAQ",
    "SAAR",
    "TUBLI",
    "ADLIYA",
    "SALMABAD",
    "BUSAITEEN",
    "ARAD",
    "BAHRAIN",
    "BHR",
    "BH",
]
LOCATION_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(term) for term in LOCATION_TERMS) + r")\b",
    re.IGNORECASE,
)
ATTACHED_LOCATION_PATTERN = re.compile(
    r"\bD("
    + "|".join(
        re.escape(term)
        for term in LOCATION_TERMS
        if " " not in term and not term.startswith("D")
    )
    + r")\b",
    re.IGNORECASE,
)
REPEATED_LOCATION_PATTERN = re.compile(r"(\[location\](?:\s+\[location\])+)", re.IGNORECASE)
MERCHANT_LOCATION_SUFFIX_PATTERN = re.compile(
    r"(?:\s+D?)("
    + "|".join(re.escape(term) for term in LOCATION_TERMS)
    + r")\b(?:\s+(?:"
    + "|".join(re.escape(term) for term in LOCATION_TERMS)
    + r"))*$",
    re.IGNORECASE,
)
SUPPORTED_SMS_CURRENCIES = {
    "BHD",
    "USD",
    "EUR",
    "GBP",
    "AED",
    "SAR",
    "KWD",
    "QAR",
    "OMR",
}


def get_db_connection():
    """Open a connection to SQLite and return rows that behave like dictionaries."""
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def get_owner_user_id(connection=None):
    """Return the first local owner user id."""
    owns_connection = connection is None
    connection = connection or get_db_connection()
    row = connection.execute(
        """
        SELECT id
        FROM users
        ORDER BY id ASC
        LIMIT 1
        """
    ).fetchone()

    if owns_connection:
        connection.close()

    return row["id"] if row else 1


def current_user_id():
    """Return the active browser/API user id, defaulting to the first owner."""
    if getattr(g, "user_id", None):
        return g.user_id

    if session.get("user_id"):
        return session["user_id"]

    return get_owner_user_id()


def get_user_by_api_key(api_key):
    """Return an active user matching an API key, or None."""
    if not api_key:
        return None

    connection = get_db_connection()
    user = connection.execute(
        """
        SELECT *
        FROM users
        WHERE api_key = ?
          AND active = 1
        """,
        (api_key,),
    ).fetchone()
    connection.close()
    return user


def get_user_by_username(username):
    """Return an active user by username, or None."""
    normalized_username = normalize_username(username)
    if not normalized_username:
        return None

    connection = get_db_connection()
    user = connection.execute(
        """
        SELECT *
        FROM users
        WHERE LOWER(username) = ?
          AND active = 1
        """,
        (normalized_username,),
    ).fetchone()
    connection.close()
    return user


def get_current_user():
    """Return the current user row."""
    connection = get_db_connection()
    user = connection.execute(
        "SELECT * FROM users WHERE id = ?",
        (current_user_id(),),
    ).fetchone()
    connection.close()
    return user


def current_user_is_admin():
    """Return whether the active browser user can manage invites."""
    user = get_current_user()
    return bool(user and user["is_admin"])


def normalize_username(username):
    """Create a predictable lowercase username for login and invites."""
    return re.sub(r"[^a-z0-9_.-]+", "", (username or "").strip().lower())


def get_invite_token_hash(token):
    """Hash an invite token before saving or looking it up."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_pending_invite_by_token(token):
    """Return an unused, unexpired invite for a raw token."""
    if not token:
        return None

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connection = get_db_connection()
    invite = connection.execute(
        """
        SELECT *
        FROM user_invites
        WHERE token_hash = ?
          AND used_at IS NULL
          AND (expires_at IS NULL OR expires_at > ?)
        """,
        (get_invite_token_hash(token), now),
    ).fetchone()
    connection.close()
    return invite


def create_private_invite(username, display_name):
    """Create a one-time invite link for a future user."""
    normalized_username = normalize_username(username)
    clean_display_name = " ".join((display_name or normalized_username).split())

    if len(normalized_username) < 3:
        raise ValueError("Username must be at least 3 characters.")

    if not clean_display_name:
        clean_display_name = normalized_username

    connection = get_db_connection()
    existing_user = connection.execute(
        "SELECT id FROM users WHERE LOWER(username) = ?",
        (normalized_username,),
    ).fetchone()
    pending_invite = connection.execute(
        """
        SELECT id
        FROM user_invites
        WHERE LOWER(username) = ?
          AND used_at IS NULL
        """,
        (normalized_username,),
    ).fetchone()

    if existing_user:
        connection.close()
        raise ValueError("That username already exists.")

    if pending_invite:
        connection.close()
        raise ValueError("There is already a pending invite for that username.")

    token = secrets.token_urlsafe(32)
    created_at = datetime.now()
    expires_at = created_at + timedelta(days=7)
    connection.execute(
        """
        INSERT INTO user_invites (
            username, display_name, token_hash, created_by_user_id, created_at, expires_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            normalized_username,
            clean_display_name,
            get_invite_token_hash(token),
            current_user_id(),
            created_at.strftime("%Y-%m-%d %H:%M:%S"),
            expires_at.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    connection.commit()
    invite_id = connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    connection.close()

    return {
        "id": invite_id,
        "username": normalized_username,
        "display_name": clean_display_name,
        "token": token,
        "invite_url": f"{get_public_app_base_url()}{url_for('accept_invite', token=token)}",
        "expires_at": expires_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


def create_user_from_invite(token, password):
    """Turn a valid invite into a real user account and expire the token."""
    if len(password) < 8:
        raise ValueError("Use at least 8 characters for your password.")

    invite = get_pending_invite_by_token(token)
    if invite is None:
        raise ValueError("This invite link is invalid, expired, or already used.")

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connection = get_db_connection()
    existing_user = connection.execute(
        "SELECT id FROM users WHERE LOWER(username) = ?",
        (invite["username"].lower(),),
    ).fetchone()

    if existing_user:
        connection.execute(
            """
            UPDATE user_invites
            SET used_at = ?
            WHERE id = ?
            """,
            (created_at, invite["id"]),
        )
        connection.commit()
        connection.close()
        raise ValueError("This username already exists. Ask the app owner for a new invite.")

    cursor = connection.execute(
        """
        INSERT INTO users (
            username, display_name, password_hash, api_key, is_admin, active, created_at
        )
        VALUES (?, ?, ?, ?, 0, 1, ?)
        """,
        (
            invite["username"],
            invite["display_name"],
            generate_password_hash(password),
            secrets.token_urlsafe(32),
            created_at,
        ),
    )
    user_id = cursor.lastrowid
    connection.execute(
        """
        UPDATE user_invites
        SET used_at = ?,
            created_user_id = ?
        WHERE id = ?
        """,
        (created_at, user_id, invite["id"]),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO user_settings (user_id, key, value)
        VALUES (?, 'monthly_budget_limit', ?)
        """,
        (user_id, str(DEFAULT_MONTHLY_BUDGET_LIMIT)),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO user_settings (user_id, key, value)
        VALUES (?, 'shortcut_guide_dismissed', '0')
        """,
        (user_id,),
    )
    connection.commit()
    connection.close()
    return user_id


def get_message_hash(raw_message):
    """Create a stable fingerprint for a raw SMS message."""
    normalized_message = " ".join(raw_message.split()).strip().lower()
    return hashlib.sha256(normalized_message.encode("utf-8")).hexdigest()


def redact_sms(raw_message):
    """Mask sensitive card, balance, and location details before displaying SMS."""
    redacted = CARD_ENDING_PATTERN.sub(r"\1****", raw_message)
    redacted = ACCOUNT_BALANCE_PATTERN.sub(r"\1***", redacted)
    redacted = ATTACHED_LOCATION_PATTERN.sub("[location]", redacted)
    redacted = LOCATION_PATTERN.sub("[location]", redacted)
    redacted = REPEATED_LOCATION_PATTERN.sub("[location]", redacted)
    return redacted


def remove_location_from_merchant(merchant):
    """Remove location suffixes from merchant display names."""
    cleaned = " ".join((merchant or "").split())

    while True:
        updated = MERCHANT_LOCATION_SUFFIX_PATTERN.sub("", cleaned).strip(" .,-")
        if updated == cleaned:
            break
        cleaned = updated

    return cleaned or "Imported SMS"


def init_db():
    """Create the app tables if they do not already exist."""
    connection = get_db_connection()
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            password_hash TEXT,
            api_key TEXT NOT NULL UNIQUE,
            is_admin INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (user_id, key),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            display_name TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_by_user_id INTEGER NOT NULL,
            created_user_id INTEGER,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            used_at TEXT,
            FOREIGN KEY (created_by_user_id) REFERENCES users (id),
            FOREIGN KEY (created_user_id) REFERENCES users (id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            merchant TEXT NOT NULL,
            category TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS imported_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            transaction_id INTEGER,
            raw_message TEXT NOT NULL,
            message_hash TEXT,
            is_duplicate INTEGER DEFAULT 0,
            parsed_amount REAL,
            parsed_currency TEXT,
            parsed_merchant TEXT,
            parsed_category TEXT,
            parsed_date TEXT,
            parsed_date_text TEXT,
            parsed_description TEXT,
            ai_parse_confidence REAL,
            ai_parse_reason TEXT,
            ai_parsed_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (transaction_id) REFERENCES transactions (id)
        )
        """
    )
    ensure_imported_message_columns(connection)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS category_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            keyword TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS category_budgets (
            user_id INTEGER,
            category TEXT PRIMARY KEY,
            monthly_limit REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS merchant_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            keyword TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sms_parser_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            regex_pattern TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            example_message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            use_count INTEGER DEFAULT 0
        )
        """
    )
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    old_password_hash_row = connection.execute(
        "SELECT value FROM settings WHERE key = 'admin_password_hash'"
    ).fetchone()
    old_api_key_row = connection.execute(
        "SELECT value FROM settings WHERE key = 'api_key'"
    ).fetchone()
    owner_password_hash = old_password_hash_row["value"] if old_password_hash_row else ""
    owner_api_key = old_api_key_row["value"] if old_api_key_row else secrets.token_urlsafe(32)
    connection.execute(
        """
        INSERT OR IGNORE INTO users (
            id, username, display_name, password_hash, api_key, is_admin, active, created_at
        )
        VALUES (1, 'owner', 'Owner', ?, ?, 1, 1, ?)
        """,
        (owner_password_hash, owner_api_key, created_at),
    )
    ensure_user_columns(connection)
    backfill_owner_user_data(connection)
    ensure_user_scoped_constraints(connection)
    ensure_user_required_triggers(connection)
    connection.execute(
        """
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('monthly_budget_limit', ?)
        """,
        (str(DEFAULT_MONTHLY_BUDGET_LIMIT),),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('api_key', ?)
        """,
        (secrets.token_urlsafe(32),),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('shortcut_guide_dismissed', '0')
        """
    )
    owner_id = get_owner_user_id(connection)
    for keyword, category in DEFAULT_CATEGORY_RULES:
        connection.execute(
            """
            INSERT OR IGNORE INTO category_rules (user_id, keyword, category, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (owner_id, keyword, category, created_at),
        )
    for keyword, display_name in DEFAULT_MERCHANT_ALIASES:
        connection.execute(
            """
            INSERT OR IGNORE INTO merchant_aliases (user_id, keyword, display_name, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (owner_id, keyword, display_name, created_at),
        )
    connection.commit()
    connection.close()


def ensure_imported_message_columns(connection):
    """Add new import-debug columns when upgrading an existing database."""
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(imported_messages)").fetchall()
    }

    columns_to_add = {
        "message_hash": "TEXT",
        "is_duplicate": "INTEGER DEFAULT 0",
        "parsed_currency": "TEXT",
        "parsed_merchant": "TEXT",
        "parsed_category": "TEXT",
        "parsed_date": "TEXT",
        "parsed_date_text": "TEXT",
        "parsed_description": "TEXT",
        "ai_parse_confidence": "REAL",
        "ai_parse_reason": "TEXT",
        "ai_parsed_at": "TEXT",
        "ai_suggested_category": "TEXT",
        "ai_suggestion_reason": "TEXT",
        "ai_suggested_at": "TEXT",
        "review_status": "TEXT",
        "review_reason": "TEXT",
        "parser_confidence": "REAL",
    }

    for column_name, column_type in columns_to_add.items():
        if column_name not in existing_columns:
            connection.execute(
                f"ALTER TABLE imported_messages ADD COLUMN {column_name} {column_type}"
            )

    rows_missing_hash = connection.execute(
        """
        SELECT id, raw_message
        FROM imported_messages
        WHERE message_hash IS NULL
        """
    ).fetchall()

    for row in rows_missing_hash:
        connection.execute(
            "UPDATE imported_messages SET message_hash = ? WHERE id = ?",
            (get_message_hash(row["raw_message"]), row["id"]),
        )


def ensure_user_columns(connection):
    """Add user ownership columns when upgrading from the single-user database."""
    user_owned_tables = {
        "transactions": "INTEGER",
        "imported_messages": "INTEGER",
        "category_rules": "INTEGER",
        "category_budgets": "INTEGER",
        "merchant_aliases": "INTEGER",
        "sms_parser_rules": "INTEGER",
    }

    for table_name, column_type in user_owned_tables.items():
        existing_columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }

        if "user_id" not in existing_columns:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN user_id {column_type}"
            )


def ensure_user_scoped_constraints(connection):
    """Rebuild old single-user tables so uniqueness is scoped per user."""
    category_rules_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(category_rules)").fetchall()
    }
    category_rules_indexes = [
        row["name"]
        for row in connection.execute("PRAGMA index_list(category_rules)").fetchall()
    ]
    category_rules_needs_rebuild = (
        "user_id" in category_rules_columns
        and "idx_category_rules_user_keyword" not in category_rules_indexes
    )

    if category_rules_needs_rebuild:
        connection.execute(
            """
            CREATE TABLE category_rules_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                keyword TEXT NOT NULL,
                category TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, keyword)
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO category_rules_new (
                id, user_id, keyword, category, created_at
            )
            SELECT id, user_id, keyword, category, created_at
            FROM category_rules
            """
        )
        connection.execute("DROP TABLE category_rules")
        connection.execute("ALTER TABLE category_rules_new RENAME TO category_rules")

    merchant_aliases_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(merchant_aliases)").fetchall()
    }
    merchant_aliases_indexes = [
        row["name"]
        for row in connection.execute("PRAGMA index_list(merchant_aliases)").fetchall()
    ]
    merchant_aliases_needs_rebuild = (
        "user_id" in merchant_aliases_columns
        and "idx_merchant_aliases_user_keyword" not in merchant_aliases_indexes
    )

    if merchant_aliases_needs_rebuild:
        connection.execute(
            """
            CREATE TABLE merchant_aliases_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                keyword TEXT NOT NULL,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, keyword)
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO merchant_aliases_new (
                id, user_id, keyword, display_name, created_at
            )
            SELECT id, user_id, keyword, display_name, created_at
            FROM merchant_aliases
            """
        )
        connection.execute("DROP TABLE merchant_aliases")
        connection.execute("ALTER TABLE merchant_aliases_new RENAME TO merchant_aliases")

    category_budgets_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(category_budgets)").fetchall()
    }
    category_budgets_indexes = [
        row["name"]
        for row in connection.execute("PRAGMA index_list(category_budgets)").fetchall()
    ]
    category_budgets_needs_rebuild = (
        "user_id" in category_budgets_columns
        and "idx_category_budgets_user_category" not in category_budgets_indexes
    )

    if category_budgets_needs_rebuild:
        connection.execute(
            """
            CREATE TABLE category_budgets_new (
                user_id INTEGER,
                category TEXT NOT NULL,
                monthly_limit REAL NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, category)
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO category_budgets_new (
                user_id, category, monthly_limit, created_at
            )
            SELECT user_id, category, monthly_limit, created_at
            FROM category_budgets
            """
        )
        connection.execute("DROP TABLE category_budgets")
        connection.execute("ALTER TABLE category_budgets_new RENAME TO category_budgets")

    sms_parser_rule_indexes = [
        row["name"]
        for row in connection.execute("PRAGMA index_list(sms_parser_rules)").fetchall()
    ]

    if "idx_sms_parser_rules_user_regex" not in sms_parser_rule_indexes:
        connection.execute(
            """
            CREATE TABLE sms_parser_rules_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT NOT NULL,
                regex_pattern TEXT NOT NULL,
                category TEXT NOT NULL,
                example_message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                use_count INTEGER DEFAULT 0,
                UNIQUE(user_id, regex_pattern)
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO sms_parser_rules_new (
                id,
                user_id,
                name,
                regex_pattern,
                category,
                example_message,
                created_at,
                last_used_at,
                use_count
            )
            SELECT
                id,
                user_id,
                name,
                regex_pattern,
                category,
                example_message,
                created_at,
                last_used_at,
                use_count
            FROM sms_parser_rules
            """
        )
        connection.execute("DROP TABLE sms_parser_rules")
        connection.execute("ALTER TABLE sms_parser_rules_new RENAME TO sms_parser_rules")

    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_category_rules_user_keyword
        ON category_rules (user_id, keyword)
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_merchant_aliases_user_keyword
        ON merchant_aliases (user_id, keyword)
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_category_budgets_user_category
        ON category_budgets (user_id, category)
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sms_parser_rules_user_regex
        ON sms_parser_rules (user_id, regex_pattern)
        """
    )


def ensure_user_required_triggers(connection):
    """Prevent new private rows from being created without an owner."""
    required_user_tables = [
        "transactions",
        "imported_messages",
        "category_rules",
        "category_budgets",
        "merchant_aliases",
        "sms_parser_rules",
    ]

    for table_name in required_user_tables:
        trigger_name = f"require_{table_name}_user_id"
        connection.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {trigger_name}
            BEFORE INSERT ON {table_name}
            WHEN NEW.user_id IS NULL
            BEGIN
                SELECT RAISE(ABORT, '{table_name}.user_id is required');
            END
            """
        )


def backfill_owner_user_data(connection):
    """Assign existing single-user data and settings to the first owner user."""
    owner_id = get_owner_user_id(connection)
    user_tables = [
        "transactions",
        "imported_messages",
        "category_rules",
        "category_budgets",
        "merchant_aliases",
        "sms_parser_rules",
    ]

    for table_name in user_tables:
        connection.execute(
            f"UPDATE {table_name} SET user_id = ? WHERE user_id IS NULL",
            (owner_id,),
        )

    existing_settings = connection.execute("SELECT key, value FROM settings").fetchall()
    for row in existing_settings:
        connection.execute(
            """
            INSERT OR IGNORE INTO user_settings (user_id, key, value)
            VALUES (?, ?, ?)
            """,
            (owner_id, row["key"], row["value"]),
        )

    connection.execute(
        """
        INSERT OR IGNORE INTO user_settings (user_id, key, value)
        VALUES (?, 'monthly_budget_limit', ?)
        """,
        (owner_id, str(DEFAULT_MONTHLY_BUDGET_LIMIT)),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO user_settings (user_id, key, value)
        VALUES (?, 'shortcut_guide_dismissed', '0')
        """,
        (owner_id,),
    )


def get_setting(key, default_value):
    """Read one setting for the current user and return a default if missing."""
    user_id = current_user_id()
    connection = get_db_connection()
    row = connection.execute(
        """
        SELECT value
        FROM user_settings
        WHERE user_id = ?
          AND key = ?
        """,
        (user_id, key),
    ).fetchone()

    if row is None:
        row = connection.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()

    connection.close()

    if row is None:
        return default_value

    return row["value"]


def save_setting(key, value):
    """Insert or update one setting for the current user."""
    user_id = current_user_id()
    connection = get_db_connection()
    connection.execute(
        """
        INSERT INTO user_settings (user_id, key, value)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value
        """,
        (user_id, key, str(value)),
    )
    connection.commit()
    connection.close()


def normalize_shortcut_public_url(url_value):
    """Return a clean public Shortcut import URL or an empty string."""
    url_value = (url_value or "").strip()

    if not url_value:
        return ""

    if not re.match(r"^https?://", url_value, re.IGNORECASE):
        return ""

    url_value = url_value.rstrip("/")

    if not url_value.endswith("/import-message"):
        url_value = f"{url_value}/import-message"

    return url_value


def get_shortcut_public_url():
    """Return the saved iPhone/ngrok URL, if one has been configured."""
    return normalize_shortcut_public_url(get_setting("shortcut_public_url", ""))


def get_effective_import_url(local_import_url):
    """Use the saved public Shortcut URL when available, otherwise local URL."""
    return get_shortcut_public_url() or local_import_url


def get_public_app_base_url():
    """Return the public app base URL when an ngrok/domain URL is saved."""
    shortcut_url = get_shortcut_public_url()

    if shortcut_url:
        return shortcut_url.removesuffix("/import-message")

    return request.host_url.rstrip("/")


def get_monthly_budget_limit():
    """Return the monthly budget setting as a number."""
    return float(get_setting("monthly_budget_limit", DEFAULT_MONTHLY_BUDGET_LIMIT))


def get_api_key():
    """Return the API key used by Shortcuts and JSON write endpoints."""
    if os.getenv("EXPENSE_TRACKER_API_KEY"):
        return os.getenv("EXPENSE_TRACKER_API_KEY")

    user = get_current_user()
    return user["api_key"] if user else ""


def regenerate_api_key():
    """Create and store a new API key."""
    new_api_key = secrets.token_urlsafe(32)
    connection = get_db_connection()
    connection.execute(
        "UPDATE users SET api_key = ? WHERE id = ?",
        (new_api_key, current_user_id()),
    )
    connection.commit()
    connection.close()
    return new_api_key


def get_password_hash():
    """Return the stored login password hash, or an empty string before setup."""
    user = get_current_user()
    return user["password_hash"] if user and user["password_hash"] else ""


def password_is_configured():
    """Return True once the first login password has been created."""
    connection = get_db_connection()
    owner = connection.execute(
        "SELECT password_hash FROM users WHERE id = ?",
        (get_owner_user_id(connection),),
    ).fetchone()
    connection.close()
    return bool(owner and owner["password_hash"])


def user_is_logged_in():
    """Return True when the current browser has a valid login session."""
    return session.get("logged_in") is True and bool(session.get("user_id"))


def set_login_password(password):
    """Hash and store the private app login password."""
    connection = get_db_connection()
    connection.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(password), get_owner_user_id(connection)),
    )
    connection.commit()
    connection.close()


def login_password_is_valid(username, password):
    """Return the matching user when a username/password pair is valid."""
    user = get_user_by_username(username or "owner")

    if not user or not user["password_hash"]:
        return None

    if not check_password_hash(user["password_hash"], password):
        return None

    return user


def request_is_shortcut_import():
    """Allow iPhone Shortcut SMS posts to use the API key without a browser login."""
    return request.endpoint == "import_message" and request.method == "POST"


def request_is_public():
    """Return True for routes that must work before browser login."""
    public_endpoints = {
        "login",
        "accept_invite",
        "api_session",
        "api_login",
        "api_logout",
        "api_invite",
        "api_accept_invite",
        "react_assets",
        "api_health",
        "static",
    }
    return request.endpoint in public_endpoints or request_is_shortcut_import()


@app.before_request
def require_login():
    """Protect private pages and APIs with a browser login session."""
    if request_is_public():
        return None

    if user_is_logged_in():
        return None

    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Login required."}), 401

    return redirect(url_for("login", next=request.full_path or request.path))


@app.context_processor
def inject_api_key():
    """Make the API key available to templates that submit protected forms."""
    return {"api_key": get_api_key()}


def get_request_api_key():
    """Read an API key from a header, form field, JSON body, or query string."""
    if request.headers.get("X-API-Key"):
        return request.headers.get("X-API-Key")

    if request.form.get("api_key"):
        return request.form.get("api_key")

    if request.is_json:
        data = request.get_json(silent=True) or {}
        if data.get("api_key"):
            return str(data.get("api_key"))

    return request.args.get("api_key", "")


def api_key_is_valid():
    """Return True when the request includes a valid user API key."""
    provided_api_key = get_request_api_key()

    if os.getenv("EXPENSE_TRACKER_API_KEY") and secrets.compare_digest(
        provided_api_key,
        os.getenv("EXPENSE_TRACKER_API_KEY"),
    ):
        g.user_id = get_owner_user_id()
        return True

    user = get_user_by_api_key(provided_api_key)
    if user is None:
        return False

    g.user_id = user["id"]
    return True


def require_api_key():
    """Stop protected write requests that do not include the API key."""
    if api_key_is_valid():
        return None

    if wants_json_response() or request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Invalid or missing API key."}), 401

    return redirect(url_for("settings"))


def require_admin_user():
    """Stop non-admin browser users from managing private invites."""
    if current_user_is_admin():
        return None

    return jsonify({"success": False, "error": "Admin access required."}), 403


def get_spending_categories():
    """Return categories that represent spending, not income."""
    return [category for category in CATEGORIES if category != "Income"]


def get_category_budgets():
    """Return category budgets as a dictionary keyed by category."""
    connection = get_db_connection()
    rows = connection.execute(
        """
        SELECT category, monthly_limit
        FROM category_budgets
        WHERE user_id = ?
        ORDER BY category ASC
        """,
        (current_user_id(),),
    ).fetchall()
    connection.close()

    return {row["category"]: row["monthly_limit"] for row in rows}


def get_saved_category_rules():
    """Return user-saved category rules ordered by longest keyword first."""
    connection = get_db_connection()
    rules = [
        dict(rule)
        for rule in connection.execute(
        """
        SELECT *
        FROM category_rules
        WHERE user_id = ?
        ORDER BY LENGTH(keyword) DESC, keyword ASC
        """,
        (current_user_id(),),
        ).fetchall()
    ]
    connection.close()
    return rules


def get_category_rules():
    """Return saved rules plus built-in defaults for automatic matching."""
    rules = get_saved_category_rules()

    saved_keywords = {rule["keyword"].upper() for rule in rules}
    fallback_rules = [
        {"keyword": keyword, "category": category}
        for keyword, category in DEFAULT_CATEGORY_RULES
        if keyword.upper() not in saved_keywords
    ]

    return sorted(
        rules + fallback_rules,
        key=lambda rule: (-len(rule["keyword"]), rule["keyword"]),
    )


def guess_category_for_merchant(merchant):
    """Choose a category by matching merchant text against saved rules."""
    merchant_upper = merchant.upper()

    for rule in get_category_rules():
        keyword = rule["keyword"].upper()
        if keyword and keyword in merchant_upper:
            return rule["category"]

    return "Other"


def get_merchant_aliases():
    """Return merchant display-name rules ordered by longest keyword first."""
    connection = get_db_connection()
    aliases = connection.execute(
        """
        SELECT *
        FROM merchant_aliases
        WHERE user_id = ?
        ORDER BY LENGTH(keyword) DESC, keyword ASC
        """,
        (current_user_id(),),
    ).fetchall()
    connection.close()

    return aliases


def get_display_merchant(merchant):
    """Return the friendly display name for a merchant when an alias matches."""
    cleaned_merchant = remove_location_from_merchant(merchant)
    merchant_upper = cleaned_merchant.upper()

    for alias in get_merchant_aliases():
        keyword = alias["keyword"].upper()
        if keyword and keyword in merchant_upper:
            return alias["display_name"]

    return cleaned_merchant


def get_display_merchant_from_aliases(merchant, aliases):
    """Return a friendly merchant name using a provided alias list."""
    cleaned_merchant = remove_location_from_merchant(merchant)
    merchant_upper = cleaned_merchant.upper()

    for alias in aliases:
        keyword = alias["keyword"].upper()
        if keyword and keyword in merchant_upper:
            return alias["display_name"]

    return cleaned_merchant


def get_suggested_merchant_keyword(merchant):
    """Pick a stable keyword from noisy bank merchant text."""
    cleaned = re.sub(r"[^A-Z0-9+]+", " ", merchant.upper())
    tokens = [token for token in cleaned.split() if token not in {"BH", "BHR", "US", "USA"}]

    if not tokens:
        return merchant.upper()

    if tokens[0] in {"OPENAI", "MCDONALDS", "TALABAT", "NETFLIX", "BENEFITPAY"}:
        return tokens[0]

    if len(tokens[0]) <= 3 and len(tokens) > 1:
        return " ".join(tokens[:2])

    return tokens[0]


def get_suggested_merchant_display_name(merchant):
    """Create a readable display name suggestion from a raw merchant string."""
    merchant_upper = merchant.upper()

    known_names = [
        ("OPENAI", "OpenAI / ChatGPT"),
        ("MCDONALDS", "McDonald's"),
        ("TALABAT", "Talabat"),
        ("NETFLIX", "Netflix"),
        ("BENEFITPAY", "BenefitPay"),
    ]

    for keyword, display_name in known_names:
        if keyword in merchant_upper:
            return display_name

    cleaned = clean_bbk_merchant(merchant)
    cleaned = re.sub(r"[*_/]+", " ", cleaned)
    cleaned = re.sub(r"\b(SUBSCR|SUBSCRIPTION|PAYMENT|CARD|REF)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(BH|BHR|US|USA)\b$", "", cleaned, flags=re.IGNORECASE)
    cleaned = " ".join(cleaned.split()).strip(" .,-")

    if not cleaned:
        return "Imported SMS"

    small_words = {"and", "of", "the", "for", "at"}
    words = []

    for word in cleaned.lower().split():
        if word in small_words:
            words.append(word)
        elif len(word) <= 3 and word.isalpha():
            words.append(word.upper())
        else:
            words.append(word.capitalize())

    return " ".join(words)


def merchant_needs_cleanup(merchant):
    """Return whether a merchant name looks too noisy for reports."""
    if merchant == "Imported SMS":
        return True

    noisy_patterns = [
        r"\*",
        r"\+\d{5,}",
        r"\b[A-Z]{2}\b$",
        r"\d{4,}",
        r"\s{2,}",
    ]

    return len(merchant) > 24 or any(
        re.search(pattern, merchant, re.IGNORECASE) for pattern in noisy_patterns
    )


def is_placeholder_merchant(merchant):
    """Return whether a merchant name is too generic for insights."""
    normalized = " ".join((merchant or "").upper().split())
    return normalized in {
        "",
        "IMPORTED SMS",
        "UNKNOWN MERCHANT",
        "RECEIVED MESSAGE",
        "SMS IMPORT",
    }


def is_payment_rail_merchant(merchant):
    """Return whether a merchant is a payment method, not a recurring merchant."""
    normalized = " ".join((merchant or "").upper().split())
    return normalized in {
        "BENEFITPAY",
        "BENEFIT PAY",
        "FAWRI",
        "FAWRI+",
        "BENEFITPAY / FAWRI+",
    }


def get_merchant_intelligence():
    """Summarize merchant cleanup opportunities from saved transactions."""
    aliases = [dict(alias) for alias in get_merchant_aliases()]
    connection = get_db_connection()
    merchant_rows = connection.execute(
        """
        SELECT
            merchant,
            COUNT(*) AS transaction_count,
            SUM(amount) AS total_amount,
            MAX(date) AS last_date
        FROM transactions
        WHERE user_id = ?
        GROUP BY merchant
        ORDER BY total_amount DESC, transaction_count DESC
        """,
        (current_user_id(),),
    ).fetchall()
    connection.close()

    groups = {}
    suggestions_by_keyword = {}
    aliased_merchants = 0
    messy_merchants = 0

    for row in merchant_rows:
        merchant = row["merchant"]
        display_name = get_display_merchant_from_aliases(merchant, aliases)
        alias_applied = display_name != merchant
        transaction_count = row["transaction_count"] or 0
        total_amount = row["total_amount"] or 0

        if alias_applied:
            aliased_merchants += 1

        if merchant_needs_cleanup(merchant):
            messy_merchants += 1

        group = groups.setdefault(
            display_name,
            {
                "display_name": display_name,
                "raw_count": 0,
                "transaction_count": 0,
                "total_amount": 0,
                "last_date": row["last_date"],
                "aliases_applied": 0,
                "raw_merchants": [],
            },
        )
        group["raw_count"] += 1
        group["transaction_count"] += transaction_count
        group["total_amount"] += total_amount
        group["aliases_applied"] += 1 if alias_applied else 0
        group["last_date"] = max(group["last_date"] or "", row["last_date"] or "")
        group["raw_merchants"].append(
            {
                "merchant": merchant,
                "transaction_count": transaction_count,
                "total_amount": total_amount,
                "last_date": row["last_date"],
                "display_name": display_name,
                "alias_applied": alias_applied,
                "needs_cleanup": merchant_needs_cleanup(merchant),
            }
        )

        if not alias_applied and merchant_needs_cleanup(merchant):
            keyword = get_suggested_merchant_keyword(merchant)
            suggestion = suggestions_by_keyword.setdefault(
                keyword,
                {
                    "keyword": keyword,
                    "display_name": get_suggested_merchant_display_name(merchant),
                    "transaction_count": 0,
                    "total_amount": 0,
                    "examples": [],
                    "reason": "Messy bank merchant name",
                },
            )
            suggestion["transaction_count"] += transaction_count
            suggestion["total_amount"] += total_amount

            if len(suggestion["examples"]) < 3:
                suggestion["examples"].append(merchant)

    sorted_groups = sorted(
        groups.values(),
        key=lambda group: (group["total_amount"], group["transaction_count"]),
        reverse=True,
    )
    sorted_suggestions = sorted(
        suggestions_by_keyword.values(),
        key=lambda suggestion: (
            suggestion["transaction_count"],
            suggestion["total_amount"],
        ),
        reverse=True,
    )

    return {
        "summary": {
            "unique_merchants": len(merchant_rows),
            "display_groups": len(sorted_groups),
            "aliased_merchants": aliased_merchants,
            "messy_merchants": messy_merchants,
        },
        "groups": sorted_groups[:30],
        "suggestions": sorted_suggestions[:12],
    }


def add_display_merchants(rows):
    """Convert SQLite rows to dictionaries and add display_merchant."""
    items = []

    for row in rows:
        item = dict(row)
        item["display_merchant"] = get_display_merchant(row["merchant"])
        items.append(item)

    return items


def get_alias_keywords_for_search(search_text):
    """Return alias keywords when search text matches a friendly display name."""
    search_upper = search_text.upper()
    keywords = []

    for alias in get_merchant_aliases():
        display_upper = alias["display_name"].upper()
        keyword_upper = alias["keyword"].upper()
        if search_upper in display_upper or search_upper in keyword_upper:
            keywords.append(alias["keyword"])

    return keywords


def get_import_status(import_row):
    """Return a short review status for an imported SMS row."""
    if import_row["is_duplicate"]:
        return "Duplicate ignored"

    if import_row["review_status"] == "failed":
        return "Failed to parse"

    if import_row["review_status"] == "needs_review":
        return "Needs review"

    if import_row["parsed_amount"] is None:
        return "Failed to parse"

    if import_row["transaction_id"] is not None:
        return "Saved as transaction"

    if import_row["transaction_id"] is None:
        if import_row["ai_parsed_at"]:
            return "AI parsed, review"

        return "Parsed but not saved"

    if import_row["transaction_category"] == "Other":
        return "Needs category rule"

    return "Saved as transaction"


def get_automation_health():
    """Summarize recent import automation activity for the dashboard."""
    user_id = current_user_id()
    today_string = datetime.today().strftime("%Y-%m-%d")
    connection = get_db_connection()
    latest_import = connection.execute(
        """
        SELECT
            imported_messages.*,
            transactions.category AS transaction_category,
            transactions.merchant AS transaction_merchant
        FROM imported_messages
        LEFT JOIN transactions
            ON imported_messages.transaction_id = transactions.id
           AND imported_messages.user_id = transactions.user_id
        WHERE imported_messages.user_id = ?
        ORDER BY imported_messages.id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    imports_today = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM imported_messages
        WHERE user_id = ?
          AND date(created_at) = ?
        """,
        (user_id, today_string),
    ).fetchone()["count"]
    failed_today = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM imported_messages
        WHERE user_id = ?
          AND date(created_at) = ?
          AND COALESCE(is_duplicate, 0) = 0
          AND parsed_amount IS NULL
        """,
        (user_id, today_string),
    ).fetchone()["count"]
    duplicates_today = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM imported_messages
        WHERE user_id = ?
          AND date(created_at) = ?
          AND COALESCE(is_duplicate, 0) = 1
        """,
        (user_id, today_string),
    ).fetchone()["count"]
    connection.close()

    if latest_import is None:
        return {
            "last_status": "No imports yet",
            "last_time": "Never",
            "last_merchant": "None",
            "imports_today": 0,
            "failed_today": 0,
            "duplicates_today": 0,
        }

    return {
        "last_status": get_import_status(latest_import),
        "last_time": latest_import["created_at"],
        "last_merchant": latest_import["parsed_merchant"]
        or latest_import["transaction_merchant"]
        or "Unknown merchant",
        "imports_today": imports_today,
        "failed_today": failed_today,
        "duplicates_today": duplicates_today,
    }


def normalize_amount_text(amount_text):
    """Convert an amount string like 1,234.500 into a float."""
    return float(amount_text.replace(",", ""))


def clean_bbk_merchant(merchant):
    """Normalize noisy BBK merchant text without hiding the real merchant."""
    merchant = " ".join((merchant or "").split())
    merchant = re.sub(r"\s+\+\d{5,}\s+[A-Z]{2}$", "", merchant, flags=re.IGNORECASE)
    merchant = re.sub(r"\s+\+\d{5,}$", "", merchant)
    merchant = re.sub(r"\s+(BH|BHR|BAHRAIN|US|USA|GB|UK)$", "", merchant, flags=re.IGNORECASE)
    merchant = remove_location_from_merchant(merchant)
    merchant = re.sub(r"\s{2,}", " ", merchant).strip(" .,-")
    return merchant or "Imported SMS"


def parse_currency_amount(raw_message):
    """Return the first non-balance currency amount found in the SMS."""
    message_without_balance = ACCOUNT_BALANCE_PATTERN.sub("", raw_message)

    for match in CURRENCY_AMOUNT_PATTERN.finditer(message_without_balance):
        currency = (match.group(1) or match.group(4) or "BHD").upper()

        if currency not in SUPPORTED_SMS_CURRENCIES:
            continue

        amount_text = match.group(2) or match.group(3)
        return currency, normalize_amount_text(amount_text)

    return None


def parse_bbk_date(date_text):
    """Convert BBK text like JUN 02 or 02 JUN into YYYY-MM-DD."""
    current_year = datetime.today().year
    normalized_date = " ".join(date_text.upper().replace(",", " ").split())
    date_formats = ["%b %d %Y", "%d %b %Y"]

    for date_format in date_formats:
        try:
            parsed_date = datetime.strptime(
                f"{normalized_date} {current_year}",
                date_format,
            )

            if parsed_date.date() > (datetime.today() + timedelta(days=1)).date():
                parsed_date = parsed_date.replace(year=current_year - 1)

            return parsed_date.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return datetime.today().strftime("%Y-%m-%d")


def parse_learned_rule_date(date_text):
    """Convert a learned-rule date string into YYYY-MM-DD."""
    cleaned_date = " ".join((date_text or "").upper().replace(",", " ").split())
    current_year = datetime.today().year
    date_formats = [
        ("%Y-%m-%d", cleaned_date),
        ("%d/%m/%Y", cleaned_date),
        ("%d/%m/%y", cleaned_date),
        ("%d-%m-%Y", cleaned_date),
        ("%d-%m-%y", cleaned_date),
        ("%b %d %Y", f"{cleaned_date} {current_year}"),
        ("%d %b %Y", f"{cleaned_date} {current_year}"),
    ]

    for date_format, value in date_formats:
        try:
            parsed_date = datetime.strptime(value, date_format)

            if parsed_date.date() > (datetime.today() + timedelta(days=1)).date():
                parsed_date = parsed_date.replace(year=parsed_date.year - 1)

            return parsed_date.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return datetime.today().strftime("%Y-%m-%d")


def normalize_sms_text(raw_message):
    """Collapse an SMS into one stable line for learned parser matching."""
    return " ".join((raw_message or "").split())


def find_case_insensitive_span(text, value):
    """Find a value in text without caring about case."""
    if not value:
        return None

    match = re.search(re.escape(str(value)), text, re.IGNORECASE)

    if match is None:
        return None

    return match.span()


def find_amount_span(text, amount):
    """Find the numeric token in an SMS that matches the parsed amount."""
    for match in re.finditer(r"\d+(?:,\d{3})*(?:\.\d+)?", text):
        try:
            if abs(normalize_amount_text(match.group(0)) - float(amount)) < 0.0005:
                return match.span()
        except ValueError:
            continue

    return None


def infer_merchant_span(text, parsed):
    """Find a merchant span from exact text or common SMS wording."""
    exact_span = find_case_insensitive_span(text, parsed.get("merchant"))

    if exact_span:
        return exact_span

    merchant_match = re.search(
        r"\bat\s+(.+?)\s+(?:on|date|for help|\.|$)",
        text,
        re.IGNORECASE,
    )

    if merchant_match:
        return merchant_match.span(1)

    amount_span = find_amount_span(text, parsed.get("amount"))
    date_span = find_case_insensitive_span(text, parsed.get("date_text"))

    if amount_span and date_span and amount_span[1] < date_span[0]:
        middle_text = text[amount_span[1] : date_span[0]]
        middle_match = re.search(r"\bat\s+(.+?)\s+(?:on|$)", middle_text, re.IGNORECASE)

        if middle_match:
            start = amount_span[1] + middle_match.start(1)
            end = amount_span[1] + middle_match.end(1)
            return start, end

    return None


def build_learned_sms_regex(raw_message, parsed):
    """Create a reusable named-group regex from an AI-parsed SMS example."""
    text = normalize_sms_text(raw_message)
    currency_span = find_case_insensitive_span(text, parsed.get("currency"))
    amount_span = find_amount_span(text, parsed.get("amount"))
    merchant_span = infer_merchant_span(text, parsed)
    date_span = find_case_insensitive_span(text, parsed.get("date_text"))

    spans = [
        ("currency", currency_span, r"(?P<currency>[A-Z]{3})"),
        ("amount", amount_span, r"(?P<amount>\d+(?:,\d{3})*(?:\.\d+)?)"),
        ("merchant", merchant_span, r"(?P<merchant>.+?)"),
        (
            "date_text",
            date_span,
            r"(?P<date_text>[A-Z]{3}\s+\d{1,2}|\d{1,2}\s+[A-Z]{3}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})",
        ),
    ]
    spans = [(name, span, pattern) for name, span, pattern in spans if span]
    spans.sort(key=lambda item: item[1][0])

    required_groups = {"amount", "currency", "merchant", "date_text"}

    if not required_groups.issubset({name for name, _, _ in spans}):
        return None

    used_group_names = set()
    regex_parts = []
    position = 0

    for name, span, pattern in spans:
        if name in used_group_names or span[0] < position:
            continue

        regex_parts.append(re.escape(text[position : span[0]]))
        regex_parts.append(pattern)
        used_group_names.add(name)
        position = span[1]

    # Bank messages often end with changing reference/help numbers, so keep the
    # learned rule strict around the transaction fields and loose after them.
    regex_parts.append(r".*")
    regex_pattern = "".join(regex_parts)
    regex_pattern = re.sub(r"\\\s+", r"\\s+", regex_pattern)
    return regex_pattern


def save_learned_sms_rule(raw_message, parsed):
    """Save a reusable parser rule after AI successfully parses an SMS."""
    regex_pattern = build_learned_sms_regex(raw_message, parsed)

    if not regex_pattern:
        return None

    merchant_name = parsed.get("merchant") or "Bank SMS"
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connection = get_db_connection()
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO sms_parser_rules (
            user_id,
            name,
            regex_pattern,
            category,
            example_message,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            current_user_id(),
            f"AI learned - {merchant_name[:40]}",
            regex_pattern,
            parsed.get("category") or "Other",
            raw_message,
            created_at,
        ),
    )
    connection.commit()
    rule_id = cursor.lastrowid

    if not rule_id:
        existing_rule = connection.execute(
            """
            SELECT id
            FROM sms_parser_rules
            WHERE user_id = ?
              AND regex_pattern = ?
            """,
            (current_user_id(), regex_pattern),
        ).fetchone()
        rule_id = existing_rule["id"] if existing_rule else None

    connection.close()

    return rule_id or None


def parse_with_learned_sms_rules(raw_message):
    """Try stored AI-learned parser rules before using AI again."""
    text = normalize_sms_text(raw_message)
    connection = get_db_connection()
    rules = connection.execute(
        """
        SELECT *
        FROM sms_parser_rules
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (current_user_id(),),
    ).fetchall()

    for rule in rules:
        try:
            match = re.search(rule["regex_pattern"], text, re.IGNORECASE)
        except re.error:
            continue

        if not match:
            continue

        groups = match.groupdict()

        if not groups.get("amount") or not groups.get("currency"):
            continue

        merchant = clean_bbk_merchant(groups.get("merchant") or "Imported SMS")
        category = guess_category_for_merchant(merchant)

        if category == "Other":
            category = rule["category"] or "Other"

        date_text = groups.get("date_text") or ""
        parsed_date = parse_learned_rule_date(date_text)
        used_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        connection.execute(
            """
            UPDATE sms_parser_rules
            SET use_count = COALESCE(use_count, 0) + 1,
                last_used_at = ?
            WHERE id = ?
              AND user_id = ?
            """,
            (used_at, rule["id"], current_user_id()),
        )
        connection.commit()
        connection.close()

        currency = groups["currency"].upper()
        return {
            "date": parsed_date,
            "amount": normalize_amount_text(groups["amount"]),
            "merchant": merchant,
            "category": category,
            "source": "Bank SMS (learned rule)",
            "currency": currency,
            "date_text": date_text,
            "description": raw_message,
            "should_save_transaction": currency == "BHD",
            "learned_rule_id": rule["id"],
        }

    connection.close()
    return None


def parse_benefitpay_fawri_sms(raw_message):
    """Parse BenefitPay Fawri+ transfer SMS messages."""
    incoming_match = FAWRI_INCOMING_CREDIT_PATTERN.search(raw_message)

    if incoming_match:
        currency = incoming_match.group(1).upper()
        amount = normalize_amount_text(incoming_match.group(2))
        date_text = incoming_match.group(3)
        time_text = incoming_match.group(4)

        return {
            "date": parse_learned_rule_date(date_text),
            "amount": amount,
            "merchant": "Fawri+ received",
            "category": "Income",
            "source": "BenefitPay / Fawri+ received",
            "currency": currency,
            "date_text": f"{date_text}, {time_text}",
            "description": raw_message,
            "should_save_transaction": currency == "BHD",
        }

    match = FAWRI_PAYMENT_PATTERN.search(raw_message)

    if match is None:
        return None

    currency = match.group(1).upper()
    amount = normalize_amount_text(match.group(2))
    date_text = match.group(3)
    time_text = match.group(4)
    display_date_text = f"{date_text}, {time_text}" if time_text else date_text
    merchant = "BenefitPay"

    return {
        "date": parse_learned_rule_date(date_text),
        "amount": amount,
        "merchant": merchant,
        "category": guess_category_for_merchant(merchant),
        "source": "BenefitPay / Fawri+",
        "currency": currency,
        "date_text": display_date_text,
        "description": raw_message,
        "should_save_transaction": currency == "BHD",
    }


def parse_bhd_sms(raw_message):
    """Extract transaction details from a BBK SMS message."""
    benefitpay_match = parse_benefitpay_fawri_sms(raw_message)

    if benefitpay_match:
        return benefitpay_match

    bbk_match = BBK_CARD_PATTERN.search(raw_message)

    if bbk_match:
        currency = bbk_match.group(1).upper()
        amount = normalize_amount_text(bbk_match.group(2))
        merchant = clean_bbk_merchant(bbk_match.group(3))
        date_text = bbk_match.group(4).upper()
        time_text = bbk_match.group(5)

        return {
            "date": parse_bbk_date(date_text),
            "amount": amount,
            "merchant": merchant,
            "category": guess_category_for_merchant(merchant),
            "source": "BBK SMS",
            "currency": currency,
            "date_text": f"{date_text}, {time_text}",
            "description": raw_message,
            "should_save_transaction": currency == "BHD",
        }

    reverse_match = BBK_AT_THEN_AMOUNT_PATTERN.search(raw_message)

    if reverse_match:
        merchant = clean_bbk_merchant(reverse_match.group(1))
        currency = reverse_match.group(2).upper()
        amount = normalize_amount_text(reverse_match.group(3))
        date_text = reverse_match.group(4).upper()
        time_text = reverse_match.group(5)

        return {
            "date": parse_bbk_date(date_text),
            "amount": amount,
            "merchant": merchant,
            "category": guess_category_for_merchant(merchant),
            "source": "BBK SMS",
            "currency": currency,
            "date_text": f"{date_text}, {time_text}",
            "description": raw_message,
            "should_save_transaction": currency == "BHD",
        }

    amount_data = parse_currency_amount(raw_message)

    if amount_data is None:
        return None

    currency, amount = amount_data
    date_match = BBK_DATE_TIME_PATTERN.search(raw_message)
    merchant_match = BBK_MERCHANT_PATTERN.search(raw_message)
    date_text = ""
    transaction_date = datetime.today().strftime("%Y-%m-%d")

    if date_match:
        date_text = f"{date_match.group(1).upper()}, {date_match.group(2)}"
        transaction_date = parse_bbk_date(date_match.group(1))

    merchant = (
        clean_bbk_merchant(merchant_match.group(1))
        if merchant_match
        else "Imported SMS"
    )

    return {
        "date": transaction_date,
        "amount": amount,
        "merchant": merchant,
        "category": guess_category_for_merchant(merchant),
        "source": "BBK SMS",
        "currency": currency,
        "date_text": date_text,
        "description": raw_message,
        "should_save_transaction": currency == "BHD",
    }


def get_ai_category_suggestion(merchant):
    """Ask OpenAI for a category suggestion for an unknown merchant."""
    if not os.getenv("OPENAI_API_KEY"):
        return None, "Set OPENAI_API_KEY to enable AI suggestions."

    categories = get_spending_categories()

    try:
        from openai import OpenAI

        client = OpenAI()
        response = client.responses.create(
            model=OPENAI_CATEGORY_MODEL,
            input=(
                "Choose the best category for this merchant. "
                "Return only one category name from this exact list: "
                f"{', '.join(categories)}.\n"
                f"Merchant: {merchant}"
            ),
        )
        suggestion = response.output_text.strip()
    except Exception as error:
        return None, f"AI suggestion failed: {error}"

    if suggestion not in categories:
        return None, f"AI returned an unsupported category: {suggestion}"

    return suggestion, f"Suggested by {OPENAI_CATEGORY_MODEL}."


def get_json_object_from_text(text):
    """Extract one JSON object from a model response."""
    cleaned_text = text.strip()

    if cleaned_text.startswith("```"):
        cleaned_text = re.sub(r"^```(?:json)?", "", cleaned_text, flags=re.IGNORECASE).strip()
        cleaned_text = re.sub(r"```$", "", cleaned_text).strip()

    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError:
        start = cleaned_text.find("{")
        end = cleaned_text.rfind("}")

        if start == -1 or end == -1 or end <= start:
            raise

        return json.loads(cleaned_text[start : end + 1])


def parse_sms_with_ai(raw_message):
    """Ask OpenAI to extract transaction fields from a bank SMS."""
    if not os.getenv("OPENAI_API_KEY"):
        return None, "Set OPENAI_API_KEY before using AI SMS parsing."

    categories = get_spending_categories()

    try:
        from openai import OpenAI

        client = OpenAI()
        response = client.responses.create(
            model=OPENAI_SMS_MODEL,
            input=(
                "Extract one bank-card transaction from this SMS. "
                "Return only a JSON object with these keys: "
                "amount, currency, merchant, date, date_text, category, confidence, reason. "
                "Use date as YYYY-MM-DD. If the year is missing, infer the current year unless that would be in the future. "
                "Use currency as a three-letter code like BHD or USD. "
                "Choose category from this exact list: "
                f"{', '.join(categories)}. "
                "Set confidence from 0 to 1. Do not include account balance as the amount. "
                "If a value cannot be found, use null.\n\n"
                f"Current date: {datetime.today().strftime('%Y-%m-%d')}\n"
                f"SMS: {raw_message}"
            ),
        )
        parsed = get_json_object_from_text(response.output_text)
    except Exception as error:
        return None, f"AI SMS parse failed: {error}"

    try:
        amount = float(parsed.get("amount"))
    except (TypeError, ValueError):
        return None, "AI did not return a usable amount."

    currency = str(parsed.get("currency") or "").strip().upper()
    merchant = clean_bbk_merchant(str(parsed.get("merchant") or "Imported SMS"))
    category = str(parsed.get("category") or "Other").strip()
    confidence = parsed.get("confidence", 0)

    try:
        confidence = max(0, min(float(confidence), 1))
    except (TypeError, ValueError):
        confidence = 0

    if not currency or len(currency) != 3:
        return None, "AI did not return a usable currency."

    if category not in categories:
        category = guess_category_for_merchant(merchant)

    date_text = str(parsed.get("date_text") or "").strip()
    date_value = str(parsed.get("date") or "").strip()

    try:
        datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError:
        date_value = datetime.today().strftime("%Y-%m-%d")

    return {
        "date": date_value,
        "amount": amount,
        "merchant": merchant,
        "category": category,
        "source": "Bank SMS (AI parsed)",
        "currency": currency,
        "date_text": date_text,
        "description": raw_message,
        "confidence": confidence,
        "reason": str(parsed.get("reason") or f"Parsed by {OPENAI_SMS_MODEL}.").strip(),
        "should_save_transaction": False,
    }, None


def get_raw_message_from_request():
    """Read SMS text from JSON, a normal HTML form, or a raw text body."""
    if request.is_json:
        data = request.get_json(silent=True) or {}
        for key in ("raw_message", "message", "text", "body"):
            if data.get(key):
                return str(data.get(key)).strip()

    form_message = request.form.get("raw_message", "").strip()
    if form_message:
        return form_message

    raw_body = request.get_data(as_text=True).strip()
    if raw_body:
        return raw_body

    return ""


def wants_json_response():
    """Return True when the caller is an API client like iPhone Shortcuts."""
    return request.is_json or "application/json" in request.headers.get("Accept", "")


def assess_import_review(parsed):
    """Decide whether a parsed SMS is safe to auto-save or needs review."""
    source = parsed.get("source", "")
    merchant = parsed.get("merchant", "")
    currency = parsed.get("currency", "BHD")
    confidence = parsed.get("confidence")

    if confidence is None:
        if source in {"BBK SMS", "BenefitPay / Fawri+", "BenefitPay / Fawri+ received"} and merchant != "Imported SMS":
            confidence = 0.95
        elif source == "Bank SMS (learned rule)":
            confidence = 0.85
        else:
            confidence = 0.55

    confidence = max(0, min(float(confidence), 1))
    reasons = []

    if currency != "BHD":
        reasons.append("Foreign currency needs exchange-rate review.")

    if not merchant or merchant == "Imported SMS":
        reasons.append("Merchant could not be confirmed.")
        confidence = min(confidence, 0.45)

    if not parsed.get("date_text"):
        reasons.append("SMS date text was not found.")
        confidence = min(confidence, 0.65)

    if source == "Bank SMS (AI parsed)":
        reasons.append("AI-parsed imports need confirmation before saving.")

    if parsed.get("category") == "Other" and source not in {"BenefitPay / Fawri+"}:
        reasons.append("Category is still Other.")
        confidence = min(confidence, 0.78)

    if not parsed.get("should_save_transaction"):
        if not reasons:
            reasons.append("Import needs manual confirmation.")

    review_status = "auto_saved"
    if reasons or confidence < 0.8:
        review_status = "needs_review"

    return {
        "review_status": review_status,
        "review_reason": " ".join(reasons) or "Confident parser match.",
        "parser_confidence": confidence,
        "should_auto_save": parsed.get("should_save_transaction") and review_status == "auto_saved",
    }


def log_failed_import(raw_message, message_hash):
    """Store an import attempt that could not be parsed."""
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connection = get_db_connection()
    cursor = connection.execute(
        """
        INSERT INTO imported_messages (
            user_id,
            raw_message,
            message_hash,
            parsed_description,
            review_status,
            review_reason,
            parser_confidence,
            created_at
        )
        VALUES (?, ?, ?, ?, 'failed', 'No supported transaction format was found.', 0, ?)
        """,
        (
            current_user_id(),
            raw_message or "[empty request body]",
            message_hash,
            raw_message,
            created_at,
        ),
    )
    import_id = cursor.lastrowid
    connection.commit()
    connection.close()

    return import_id


def get_current_month_bounds():
    """Return date strings for the start of this month and the next month."""
    today = datetime.today()
    start_of_month = today.replace(day=1).strftime("%Y-%m-%d")

    if today.month == 12:
        next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month + 1, day=1)

    return start_of_month, next_month.strftime("%Y-%m-%d")


def get_month_bounds(month_date):
    """Return the first day and next month start for any month."""
    start_of_month = month_date.replace(day=1)

    if start_of_month.month == 12:
        next_month = start_of_month.replace(
            year=start_of_month.year + 1,
            month=1,
            day=1,
        )
    else:
        next_month = start_of_month.replace(month=start_of_month.month + 1, day=1)

    return start_of_month, next_month


def get_month_details(month_value=None):
    """Return useful month details from a YYYY-MM value."""
    today = datetime.today()
    current_month = today.strftime("%Y-%m")
    month_value = month_value or current_month

    try:
        month_date = datetime.strptime(month_value, "%Y-%m")
    except ValueError:
        month_value = current_month
        month_date = today

    start_of_month, next_month = get_month_bounds(month_date)

    return {
        "value": month_value,
        "label": start_of_month.strftime("%B %Y"),
        "start": start_of_month.strftime("%Y-%m-%d"),
        "next": next_month.strftime("%Y-%m-%d"),
        "is_current": month_value == current_month,
        "days_in_month": (next_month - timedelta(days=1)).day,
    }


def get_default_dashboard_month():
    """Prefer the current month, unless it has no data and an older month does."""
    current_month = datetime.today().strftime("%Y-%m")
    user_id = current_user_id()
    connection = get_db_connection()
    current_month_count = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM transactions
        WHERE user_id = ?
          AND substr(date, 1, 7) = ?
        """,
        (user_id, current_month),
    ).fetchone()["count"]

    if current_month_count:
        connection.close()
        return current_month

    latest_month = connection.execute(
        """
        SELECT substr(date, 1, 7) AS month
        FROM transactions
        WHERE user_id = ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    connection.close()

    return latest_month["month"] if latest_month else current_month


def get_selected_month():
    """Read ?month=YYYY-MM from the URL and return useful month details."""
    return get_month_details(request.args.get("month"))


def get_recurring_merchants(connection):
    """Find friendly merchant names that appear more than once."""
    rows = connection.execute(
        """
        SELECT *
        FROM transactions
        WHERE user_id = ?
          AND category != 'Income'
        ORDER BY date DESC
        """,
        (current_user_id(),),
    ).fetchall()
    grouped_merchants = {}

    for row in rows:
        display_merchant = get_display_merchant(row["merchant"])
        if is_placeholder_merchant(display_merchant) or is_payment_rail_merchant(
            display_merchant
        ):
            continue

        group = grouped_merchants.setdefault(
            display_merchant,
            {
                "merchant": display_merchant,
                "transaction_count": 0,
                "months": set(),
                "total_amount": 0,
                "last_seen": row["date"],
            },
        )
        group["transaction_count"] += 1
        group["months"].add(row["date"][:7])
        group["total_amount"] += row["amount"]
        group["last_seen"] = max(group["last_seen"], row["date"])

    recurring_merchants = []
    for group in grouped_merchants.values():
        if group["transaction_count"] >= 2:
            recurring_merchants.append(
                {
                    "merchant": group["merchant"],
                    "transaction_count": group["transaction_count"],
                    "months_seen": len(group["months"]),
                    "average_amount": group["total_amount"]
                    / group["transaction_count"],
                    "last_seen": group["last_seen"],
                }
            )

    return sorted(
        recurring_merchants,
        key=lambda item: (
            item["months_seen"],
            item["transaction_count"],
            item["last_seen"],
        ),
        reverse=True,
    )[:6]


def get_calendar_spending(connection, selected_month):
    """Return one net-spending total for each day in the selected month."""
    daily_rows = connection.execute(
        """
        SELECT
            date,
            COALESCE(
                SUM(CASE WHEN category = 'Income' THEN -amount ELSE amount END),
                0
            ) AS total
        FROM transactions
        WHERE user_id = ?
          AND date >= ?
          AND date < ?
        GROUP BY date
        ORDER BY date ASC
        """,
        (current_user_id(), selected_month["start"], selected_month["next"]),
    ).fetchall()
    daily_totals = {row["date"]: row["total"] for row in daily_rows}
    today_string = datetime.today().strftime("%Y-%m-%d")
    start_date = datetime.strptime(selected_month["start"], "%Y-%m-%d")
    days = []

    for day_number in range(1, selected_month["days_in_month"] + 1):
        day_date = start_date.replace(day=day_number)
        date_string = day_date.strftime("%Y-%m-%d")
        total = daily_totals.get(date_string, 0)
        days.append(
            {
                "date": date_string,
                "day": day_number,
                "weekday": day_date.strftime("%a"),
                "total": total,
                "has_spending": total != 0,
                "is_today": date_string == today_string,
            }
        )

    return {
        "leading_blank_days": start_date.weekday(),
        "days": days,
        "max_daily_spending": max((abs(total) for total in daily_totals.values()), default=0),
    }


def get_monthly_insights(
    connection,
    selected_month,
    spending_by_category,
    net_spent,
    monthly_budget_limit,
    monthly_prediction,
    recurring_merchants,
    pending_import_reviews,
):
    """Build short dashboard insights from local transaction data."""
    insights = []

    if spending_by_category:
        top_category = spending_by_category[0]
        insights.append(
            {
                "type": "top_category",
                "tone": "info",
                "text": f"You spent most on {top_category['category']}.",
            }
        )
    else:
        insights.append(
            {
                "type": "top_category",
                "tone": "muted",
                "text": "Add transactions to see your top spending category.",
            }
        )

    month_start = datetime.strptime(selected_month["start"], "%Y-%m-%d")
    previous_start, previous_next = get_month_bounds(month_start - timedelta(days=1))
    previous_rows = connection.execute(
        """
        SELECT category, COALESCE(SUM(amount), 0) AS total
        FROM transactions
        WHERE user_id = ?
          AND category != 'Income'
          AND date >= ?
          AND date < ?
        GROUP BY category
        """,
        (
            current_user_id(),
            previous_start.strftime("%Y-%m-%d"),
            previous_next.strftime("%Y-%m-%d"),
        ),
    ).fetchall()
    previous_totals = {row["category"]: row["total"] for row in previous_rows}
    biggest_increase = None

    for row in spending_by_category:
        previous_total = previous_totals.get(row["category"], 0)
        if previous_total <= 0:
            continue

        percent_change = ((row["total"] - previous_total) / previous_total) * 100
        if percent_change < 10:
            continue

        if not biggest_increase or percent_change > biggest_increase["percent_change"]:
            biggest_increase = {
                "category": row["category"],
                "percent_change": percent_change,
            }

    if biggest_increase:
        insights.append(
            {
                "type": "category_trend",
                "tone": "warning",
                "text": (
                    f"{biggest_increase['category']} is "
                    f"{round(biggest_increase['percent_change'])}% higher than last month."
                ),
            }
        )
    elif previous_totals:
        insights.append(
            {
                "type": "category_trend",
                "tone": "good",
                "text": "No category is sharply higher than last month.",
            }
        )

    if monthly_budget_limit:
        budget_value = monthly_prediction if selected_month["is_current"] else net_spent
        budget_percent = max(round((budget_value / monthly_budget_limit) * 100), 0)
        insights.append(
            {
                "type": "budget_pace",
                "tone": "warning" if budget_percent >= 90 else "good",
                "text": f"You are on pace to use {budget_percent}% of your budget.",
            }
        )
    else:
        insights.append(
            {
                "type": "budget_pace",
                "tone": "muted",
                "text": "Set a monthly budget to track your pace.",
            }
        )

    if pending_import_reviews:
        insights.append(
            {
                "type": "review_queue",
                "tone": "warning",
                "text": (
                    f"{pending_import_reviews} import"
                    f"{'' if pending_import_reviews == 1 else 's'} need review."
                ),
            }
        )
    else:
        insights.append(
            {
                "type": "review_queue",
                "tone": "good",
                "text": "No imports need review.",
            }
        )

    if recurring_merchants:
        insights.append(
            {
                "type": "recurring",
                "tone": "info",
                "text": f"{recurring_merchants[0]['merchant']} looks recurring.",
            }
        )

    biggest_transaction = connection.execute(
        """
        SELECT *
        FROM transactions
        WHERE user_id = ?
          AND category != 'Income'
          AND date >= ?
          AND date < ?
        ORDER BY amount DESC, date DESC, id DESC
        LIMIT 1
        """,
        (current_user_id(), selected_month["start"], selected_month["next"]),
    ).fetchone()

    if biggest_transaction:
        insights.append(
            {
                "type": "biggest_transaction",
                "tone": "info",
                "text": (
                    "Your biggest transaction was "
                    f"{get_display_merchant(biggest_transaction['merchant'])}, "
                    f"BHD {biggest_transaction['amount']:.3f}."
                ),
            }
        )

    return insights


def get_unusual_transaction_alerts(connection, start_of_month, next_month):
    """Compare this month's transactions against simple history-based rules."""
    user_id = current_user_id()
    transactions_to_check = connection.execute(
        """
        SELECT *
        FROM transactions
        WHERE user_id = ?
          AND category != 'Income'
          AND date >= ?
          AND date < ?
        ORDER BY amount DESC, date DESC
        """,
        (user_id, start_of_month, next_month),
    ).fetchall()
    alerts = []

    for transaction in transactions_to_check:
        reasons = []
        category_stats = connection.execute(
            """
            SELECT COUNT(*) AS count, AVG(amount) AS average_amount
            FROM transactions
            WHERE user_id = ?
              AND category = ?
              AND category != 'Income'
              AND id != ?
            """,
            (user_id, transaction["category"], transaction["id"]),
        ).fetchone()
        merchant_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM transactions
            WHERE user_id = ?
              AND merchant = ?
              AND id != ?
            """,
            (user_id, transaction["merchant"], transaction["id"]),
        ).fetchone()["count"]

        if transaction["amount"] >= HIGH_TRANSACTION_LIMIT:
            reasons.append(f"Above the {HIGH_TRANSACTION_LIMIT:.3f} high amount check")

        if merchant_count == 0 and transaction["amount"] >= 10:
            reasons.append("New merchant with a higher amount")

        if (
            category_stats["count"] >= 3
            and category_stats["average_amount"]
            and transaction["amount"] >= category_stats["average_amount"] * 2.5
            and transaction["amount"] >= category_stats["average_amount"] + 5
        ):
            reasons.append(
                f"Much higher than your usual {transaction['category']} spending"
            )

        if reasons:
            transaction_item = dict(transaction)
            transaction_item["display_merchant"] = get_display_merchant(
                transaction["merchant"]
            )
            alerts.append(
                {
                    "transaction": transaction_item,
                    "reason": reasons[0],
                }
            )

    return alerts[:6]


def get_data_quality_alerts():
    """Return practical warnings about data that may need cleanup."""
    user_id = current_user_id()
    connection = get_db_connection()
    alerts = []
    failed_imports = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM imported_messages
        WHERE user_id = ?
          AND COALESCE(is_duplicate, 0) = 0
          AND parsed_amount IS NULL
        """
        ,
        (user_id,),
    ).fetchone()["count"]
    unsaved_imports = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM imported_messages
        WHERE user_id = ?
          AND COALESCE(is_duplicate, 0) = 0
          AND parsed_amount IS NOT NULL
          AND transaction_id IS NULL
        """
        ,
        (user_id,),
    ).fetchone()["count"]
    other_transactions = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM transactions
        WHERE user_id = ?
          AND category = 'Other'
        """,
        (user_id,),
    ).fetchone()["count"]
    total_transactions = connection.execute(
        "SELECT COUNT(*) AS count FROM transactions WHERE user_id = ?",
        (user_id,),
    ).fetchone()["count"]
    duplicate_groups = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT date, merchant, amount, COUNT(*) AS row_count
            FROM transactions
            WHERE user_id = ?
            GROUP BY date, merchant, amount
            HAVING row_count > 1
        )
        """
        ,
        (user_id,),
    ).fetchone()["count"]
    parser_rules_unused = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM sms_parser_rules
        WHERE user_id = ?
          AND COALESCE(use_count, 0) = 0
        """,
        (user_id,),
    ).fetchone()["count"]
    connection.close()

    if failed_imports:
        alerts.append(
            {
                "level": "warning",
                "title": "Failed imports need repair",
                "detail": f"{failed_imports} import row{'s' if failed_imports != 1 else ''} could not be parsed.",
            }
        )

    if unsaved_imports:
        alerts.append(
            {
                "level": "warning",
                "title": "Parsed imports are not saved",
                "detail": f"{unsaved_imports} parsed import{'s' if unsaved_imports != 1 else ''} still need review.",
            }
        )

    if total_transactions and other_transactions / total_transactions >= 0.25:
        alerts.append(
            {
                "level": "info",
                "title": "Many transactions are Other",
                "detail": f"{other_transactions} of {total_transactions} transactions use Other. Category rules may help.",
            }
        )

    if duplicate_groups:
        alerts.append(
            {
                "level": "warning",
                "title": "Possible duplicate transactions",
                "detail": f"{duplicate_groups} date/merchant/amount group{'s' if duplicate_groups != 1 else ''} appear more than once.",
            }
        )

    if parser_rules_unused:
        alerts.append(
            {
                "level": "info",
                "title": "Learned rules unused so far",
                "detail": f"{parser_rules_unused} learned parser rule{'s' if parser_rules_unused != 1 else ''} have not matched a future SMS yet.",
            }
        )

    backup_history = get_backup_history(1)
    if not backup_history:
        alerts.append(
            {
                "level": "warning",
                "title": "No local backup yet",
                "detail": "Create a backup before importing more real transactions.",
            }
        )

    return alerts[:8]


def get_days_in_month(today):
    """Return how many days are in the current month."""
    _, next_month = get_month_bounds(today)
    last_day_this_month = next_month - timedelta(days=1)
    return last_day_this_month.day


def parse_optional_amount(value):
    """Return a number from a filter field, or None when it is blank/invalid."""
    if not value:
        return None

    try:
        return float(value)
    except ValueError:
        return None


def backup_current_database(prefix="expense-tracker-backup"):
    """Copy the current SQLite database into the backups folder."""
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    backup_path = BACKUP_DIR / f"{prefix}-{timestamp}.db"
    shutil.copy2(DATABASE, backup_path)
    return backup_path


def get_backup_history(limit=8):
    """Return recent local database backups with simple metadata."""
    BACKUP_DIR.mkdir(exist_ok=True)
    backup_files = sorted(
        BACKUP_DIR.glob("*.db"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:limit]

    return [
        {
            "filename": path.name,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "created_at": datetime.fromtimestamp(path.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }
        for path in backup_files
    ]


def get_private_deployment_readiness(import_url):
    """Return a detailed checklist for running the app as a reliable private service."""
    backup_history = get_backup_history(1)
    latest_backup = backup_history[0] if backup_history else None
    backup_age_hours = None

    if latest_backup:
        backup_created = datetime.strptime(latest_backup["created_at"], "%Y-%m-%d %H:%M:%S")
        backup_age_hours = (datetime.now() - backup_created).total_seconds() / 3600

    is_https = import_url.startswith("https://")
    is_localhost = "127.0.0.1" in import_url or "localhost" in import_url
    is_lan = bool(re.search(r"http://(?:10\.|172\.(?:1[6-9]|2\d|3[0-1])\.|192\.168\.)", import_url))
    is_ngrok = "ngrok" in import_url
    flask_debug = os.getenv("FLASK_DEBUG", "0") == "1"
    cookie_secure = app.config.get("SESSION_COOKIE_SECURE", False)
    api_key = get_api_key()
    automation_health = get_automation_health()

    checks = []

    def add_check(key, title, status, detail, recommendation):
        checks.append(
            {
                "key": key,
                "title": title,
                "status": status,
                "detail": detail,
                "recommendation": recommendation,
            }
        )

    if is_localhost:
        add_check(
            "import_url",
            "Import URL",
            "error",
            "The current import URL uses 127.0.0.1, which only works on this PC.",
            "Use an ngrok HTTPS URL for testing outside the PC, or a real HTTPS domain for production.",
        )
    elif is_ngrok:
        add_check(
            "import_url",
            "Import URL",
            "warning",
            "The current import URL is ngrok. Good for testing, but it may change unless you configure a stable domain.",
            "For a reliable private app, move to a stable HTTPS domain or a reserved tunnel/domain.",
        )
    elif is_lan:
        add_check(
            "import_url",
            "Import URL",
            "warning",
            "The current import URL is a same-Wi-Fi address. It works only when your iPhone and PC are on the same network.",
            "Use HTTPS hosting if you want imports while you are outside.",
        )
    elif is_https:
        add_check(
            "import_url",
            "Import URL",
            "pass",
            "The import URL is HTTPS and does not look local.",
            "Keep this URL in your iPhone Shortcut.",
        )
    else:
        add_check(
            "import_url",
            "Import URL",
            "warning",
            "The import URL is not HTTPS.",
            "Use HTTPS before relying on this online.",
        )

    add_check(
        "https",
        "HTTPS",
        "pass" if is_https else "error",
        "HTTPS is active for the import URL." if is_https else "HTTPS is not active for the current import URL.",
        "Set up a domain with HTTPS before using the app outside local testing.",
    )
    add_check(
        "debug_mode",
        "Flask debug mode",
        "error" if flask_debug else "pass",
        "Flask debug mode is enabled." if flask_debug else "Flask debug mode is off.",
        "Run with Waitress and FLASK_DEBUG=0 for private deployment.",
    )
    add_check(
        "session_cookie",
        "Secure session cookie",
        "pass" if (cookie_secure or not is_https) else "warning",
        "SESSION_COOKIE_SECURE is enabled."
        if cookie_secure
        else "SESSION_COOKIE_SECURE is off. This is okay for local HTTP, but not for HTTPS deployment.",
        "Set SESSION_COOKIE_SECURE=1 when hosted behind HTTPS.",
    )
    add_check(
        "api_key",
        "Shortcut API key",
        "pass" if len(api_key) >= 32 else "warning",
        "A Shortcut API key is configured and protected in Settings."
        if len(api_key) >= 32
        else "The API key looks short.",
        "Use Regenerate API key if you want a fresh strong key, then update your Shortcut.",
    )
    add_check(
        "backups",
        "Recent backup",
        "pass" if backup_age_hours is not None and backup_age_hours <= 72 else "warning",
        f"Latest backup is {backup_age_hours:.1f} hours old."
        if backup_age_hours is not None
        else "No local backup was found.",
        "Create a backup before relying on automation or deploying online.",
    )
    add_check(
        "shortcut_health",
        "Shortcut import health",
        "pass" if automation_health["imports_today"] > 0 else "warning",
        f"{automation_health['imports_today']} import(s) received today."
        if automation_health["imports_today"] > 0
        else "No imports received today.",
        "Use Send test import in Settings, then confirm it appears in Imports.",
    )

    score = sum(1 for check in checks if check["status"] == "pass")
    total = len(checks)
    blocking_count = sum(1 for check in checks if check["status"] == "error")
    warning_count = sum(1 for check in checks if check["status"] == "warning")

    if blocking_count:
        level = "Not ready"
    elif warning_count:
        level = "Almost ready"
    else:
        level = "Ready for private deployment"

    return {
        "level": level,
        "score": score,
        "total": total,
        "blocking_count": blocking_count,
        "warning_count": warning_count,
        "checks": checks,
        "summary": {
            "is_https": is_https,
            "is_localhost": is_localhost,
            "is_lan": is_lan,
            "is_ngrok": is_ngrok,
            "flask_debug": flask_debug,
            "session_cookie_secure": cookie_secure,
            "latest_backup": latest_backup,
        },
    }


def get_backup_path_from_name(filename):
    """Return a safe backup path from a filename, or None if it is invalid."""
    safe_name = Path(filename).name
    backup_path = (BACKUP_DIR / safe_name).resolve()

    if backup_path.parent != BACKUP_DIR.resolve() or backup_path.suffix != ".db":
        return None

    if not backup_path.exists():
        return None

    return backup_path


def is_valid_backup_database(path):
    """Check that an uploaded file looks like this app's SQLite database."""
    try:
        connection = sqlite3.connect(path)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        connection.close()
    except sqlite3.DatabaseError:
        return False

    return "transactions" in tables


def get_transaction_filters(args):
    """Read transaction filters from a request query dictionary."""
    return {
        "date": args.get("date", "").strip(),
        "merchant": args.get("merchant", "").strip(),
        "category": args.get("category", ""),
        "source": args.get("source", ""),
        "min_amount": args.get("min_amount", "").strip(),
        "max_amount": args.get("max_amount", "").strip(),
        "sort": args.get("sort", "newest"),
        "unusual_only": args.get("unusual_only") == "1",
    }


def get_filtered_transactions(selected_month, filters):
    """Return filtered transaction rows and source options."""
    user_id = current_user_id()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", filters["date"]):
        where_clauses = ["user_id = ?", "date = ?"]
        query_values = [user_id, filters["date"]]
    else:
        where_clauses = [
            "user_id = ?",
            "date >= ?",
            "date < ?",
        ]
        query_values = [
            user_id,
            selected_month["start"],
            selected_month["next"],
        ]

    if filters["merchant"]:
        alias_keywords = get_alias_keywords_for_search(filters["merchant"])
        merchant_search_clauses = ["merchant LIKE ?"]
        query_values.append(f"%{filters['merchant']}%")

        for keyword in alias_keywords:
            merchant_search_clauses.append("merchant LIKE ?")
            query_values.append(f"%{keyword}%")

        where_clauses.append(f"({' OR '.join(merchant_search_clauses)})")

    if filters["category"]:
        where_clauses.append("category = ?")
        query_values.append(filters["category"])

    if filters["source"]:
        where_clauses.append("source = ?")
        query_values.append(filters["source"])

    min_amount = parse_optional_amount(filters["min_amount"])
    max_amount = parse_optional_amount(filters["max_amount"])

    if min_amount is not None:
        where_clauses.append("amount >= ?")
        query_values.append(min_amount)

    if max_amount is not None:
        where_clauses.append("amount <= ?")
        query_values.append(max_amount)

    connection = get_db_connection()
    source_rows = connection.execute(
        """
        SELECT DISTINCT source
        FROM transactions
        WHERE user_id = ?
        ORDER BY source ASC
        """,
        (user_id,),
    ).fetchall()

    if filters["unusual_only"]:
        unusual_alerts = get_unusual_transaction_alerts(
            connection,
            selected_month["start"],
            selected_month["next"],
        )
        unusual_ids = [alert["transaction"]["id"] for alert in unusual_alerts]

        if unusual_ids:
            placeholders = ", ".join("?" for _ in unusual_ids)
            where_clauses.append(f"id IN ({placeholders})")
            query_values.extend(unusual_ids)
        else:
            where_clauses.append("1 = 0")

    sort_options = {
        "newest": "date DESC, id DESC",
        "oldest": "date ASC, id ASC",
        "highest": "amount DESC, date DESC",
        "lowest": "amount ASC, date DESC",
    }
    order_by = sort_options.get(filters["sort"], sort_options["newest"])
    transactions = connection.execute(
        f"""
        SELECT *
        FROM transactions
        WHERE {" AND ".join(where_clauses)}
        ORDER BY {order_by}
        """,
        query_values,
    ).fetchall()
    connection.close()

    return {
        "transactions": add_display_merchants(transactions),
        "sources": [row["source"] for row in source_rows],
    }


def get_dashboard_data(selected_month):
    """Build dashboard data for both HTML templates and JSON API responses."""
    user_id = current_user_id()
    today = datetime.today()
    today_string = today.strftime("%Y-%m-%d")
    start_of_month = selected_month["start"]
    next_month = selected_month["next"]
    monthly_budget_limit = get_monthly_budget_limit()
    connection = get_db_connection()

    today_spending = connection.execute(
        """
        SELECT
            COALESCE(
                SUM(CASE WHEN category = 'Income' THEN -amount ELSE amount END),
                0
            ) AS total
        FROM transactions
        WHERE user_id = ?
          AND date = ?
        """,
        (user_id, today_string),
    ).fetchone()["total"]
    total_expenses = connection.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM transactions
        WHERE user_id = ?
          AND category != 'Income'
          AND date >= ?
          AND date < ?
        """,
        (user_id, start_of_month, next_month),
    ).fetchone()["total"]
    total_income = connection.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM transactions
        WHERE user_id = ?
          AND category = 'Income'
          AND date >= ?
          AND date < ?
        """,
        (user_id, start_of_month, next_month),
    ).fetchone()["total"]
    net_spent = total_expenses - total_income
    recent_transactions = add_display_merchants(
        connection.execute(
            """
            SELECT *
            FROM transactions
            WHERE user_id = ?
              AND date >= ?
              AND date < ?
            ORDER BY date DESC, id DESC
            LIMIT 5
            """,
            (user_id, start_of_month, next_month),
        ).fetchall()
    )
    spending_by_category = [
        dict(row)
        for row in connection.execute(
            """
            SELECT category, SUM(amount) AS total
            FROM transactions
            WHERE user_id = ?
              AND category != 'Income'
              AND date >= ?
              AND date < ?
            GROUP BY category
            ORDER BY total DESC
            """,
            (user_id, start_of_month, next_month),
        ).fetchall()
    ]
    net_category_ratio = (
        max(net_spent, 0) / total_expenses if total_expenses > 0 else 0
    )
    spending_by_category = [
        {
            **row,
            "gross_total": row["total"],
            "total": row["total"] * net_category_ratio,
        }
        for row in spending_by_category
        if row["total"] * net_category_ratio > 0
    ]
    category_spending_totals = {
        row["category"]: row["total"] for row in spending_by_category
    }
    category_budget_statuses = []

    for category, monthly_limit in get_category_budgets().items():
        spent = category_spending_totals.get(category, 0)
        percent_used = (spent / monthly_limit) * 100 if monthly_limit else 0
        category_budget_statuses.append(
            {
                "category": category,
                "spent": spent,
                "monthly_limit": monthly_limit,
                "percent_used": percent_used,
                "is_over": percent_used >= 100,
                "is_warning": percent_used >= 80,
            }
        )

    category_budget_statuses.sort(
        key=lambda item: item["percent_used"],
        reverse=True,
    )
    max_category_spending = max(category_spending_totals.values(), default=0)
    category_chart_rows = []

    for row in spending_by_category:
        total = row["total"]
        category_chart_rows.append(
            {
                "category": row["category"],
                "total": total,
                "color": CATEGORY_COLORS.get(row["category"], "#64748b"),
                "percent": (total / max_category_spending) * 100
                if max_category_spending
                else 0,
            }
        )

    unusual_alerts = get_unusual_transaction_alerts(
        connection,
        start_of_month,
        next_month,
    )
    recurring_merchants = get_recurring_merchants(connection)
    calendar_spending = get_calendar_spending(connection, selected_month)
    pending_import_reviews = get_pending_import_review_count()

    if selected_month["is_current"] and today.day > 0:
        monthly_prediction = (
            net_spent / today.day
        ) * selected_month["days_in_month"]
    elif selected_month["is_current"]:
        monthly_prediction = 0
    else:
        monthly_prediction = net_spent

    budget_warning = None
    if net_spent >= monthly_budget_limit:
        budget_warning = "You have reached or passed your monthly budget limit."
    elif selected_month["is_current"] and monthly_prediction >= monthly_budget_limit:
        budget_warning = "At this pace, you may pass your monthly budget limit."

    monthly_insights = get_monthly_insights(
        connection,
        selected_month,
        spending_by_category,
        net_spent,
        monthly_budget_limit,
        monthly_prediction,
        recurring_merchants,
        pending_import_reviews,
    )
    connection.close()

    return {
        "selected_month": selected_month,
        "today_spending": today_spending,
        "total_expenses": total_expenses,
        "total_income": total_income,
        "net_spent": net_spent,
        "monthly_budget_limit": monthly_budget_limit,
        "monthly_prediction": monthly_prediction,
        "budget_warning": budget_warning,
        "unusual_alerts": unusual_alerts,
        "recurring_merchants": recurring_merchants,
        "recent_transactions": recent_transactions,
        "spending_by_category": spending_by_category,
        "category_budget_statuses": category_budget_statuses,
        "category_chart_rows": category_chart_rows,
        "automation_health": get_automation_health(),
        "pending_import_reviews": pending_import_reviews,
        "monthly_insights": monthly_insights,
        "calendar_spending": calendar_spending,
    }


def get_monthly_report_data(selected_month):
    """Build monthly report data for HTML and API responses."""
    user_id = current_user_id()
    connection = get_db_connection()
    totals = dict(
        connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN category != 'Income' THEN amount ELSE 0 END), 0) AS expenses,
                COALESCE(SUM(CASE WHEN category = 'Income' THEN amount ELSE 0 END), 0) AS income
            FROM transactions
            WHERE user_id = ?
              AND date >= ?
              AND date < ?
            """,
            (user_id, selected_month["start"], selected_month["next"]),
        ).fetchone()
    )
    selected_net_spent = totals["expenses"] - totals["income"]
    selected_net_ratio = (
        max(selected_net_spent, 0) / totals["expenses"]
        if totals["expenses"] > 0
        else 0
    )
    category_rows = [
        {
            **dict(row),
            "gross_total": row["total"],
            "total": row["total"] * selected_net_ratio,
        }
        for row in connection.execute(
            """
            SELECT category, SUM(amount) AS total
            FROM transactions
            WHERE user_id = ?
              AND category != 'Income'
              AND date >= ?
              AND date < ?
            GROUP BY category
            ORDER BY total DESC
            """,
            (user_id, selected_month["start"], selected_month["next"]),
        ).fetchall()
        if row["total"] * selected_net_ratio > 0
    ]
    transaction_count = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM transactions
        WHERE user_id = ?
          AND date >= ?
          AND date < ?
        """,
        (user_id, selected_month["start"], selected_month["next"]),
    ).fetchone()["count"]
    merchant_rows = [
        {
            **dict(row),
            "gross_total": row["total"],
            "total": row["total"] * selected_net_ratio,
        }
        for row in connection.execute(
            """
            SELECT merchant, category, COUNT(*) AS transaction_count, SUM(amount) AS total
            FROM transactions
            WHERE user_id = ?
              AND category != 'Income'
              AND date >= ?
              AND date < ?
            GROUP BY merchant, category
            ORDER BY total DESC
            LIMIT 6
            """,
            (user_id, selected_month["start"], selected_month["next"]),
        ).fetchall()
        if row["total"] * selected_net_ratio > 0
    ]
    trend_rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT
                substr(date, 1, 7) AS month,
                COALESCE(SUM(CASE WHEN category != 'Income' THEN amount ELSE 0 END), 0) AS expenses,
                COALESCE(SUM(CASE WHEN category = 'Income' THEN amount ELSE 0 END), 0) AS income
            FROM transactions
            WHERE user_id = ?
            GROUP BY substr(date, 1, 7)
            ORDER BY month DESC
            LIMIT 6
            """
            ,
            (user_id,),
        ).fetchall()
    ]
    trend_rows.reverse()
    category_trend_rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT category, SUM(amount) AS total
            FROM transactions
            WHERE user_id = ?
              AND category != 'Income'
              AND date >= date(?, '-5 months')
              AND date < ?
            GROUP BY category
            ORDER BY total DESC
            LIMIT 6
            """,
            (user_id, selected_month["start"], selected_month["next"]),
        ).fetchall()
    ]
    trend_period_totals = dict(
        connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN category != 'Income' THEN amount ELSE 0 END), 0) AS expenses,
                COALESCE(SUM(CASE WHEN category = 'Income' THEN amount ELSE 0 END), 0) AS income
            FROM transactions
            WHERE user_id = ?
              AND date >= date(?, '-5 months')
              AND date < ?
            """,
            (user_id, selected_month["start"], selected_month["next"]),
        ).fetchone()
    )
    trend_net_spent = trend_period_totals["expenses"] - trend_period_totals["income"]
    trend_net_ratio = (
        max(trend_net_spent, 0) / trend_period_totals["expenses"]
        if trend_period_totals["expenses"] > 0
        else 0
    )
    category_trend_rows = [
        {
            **row,
            "gross_total": row["total"],
            "total": row["total"] * trend_net_ratio,
        }
        for row in category_trend_rows
        if row["total"] * trend_net_ratio > 0
    ]
    merchant_trend_rows = [
        {
            **dict(row),
            "gross_total": row["total"],
            "total": row["total"] * trend_net_ratio,
        }
        for row in connection.execute(
            """
            SELECT merchant, COUNT(*) AS transaction_count, SUM(amount) AS total
            FROM transactions
            WHERE user_id = ?
              AND category != 'Income'
              AND date >= date(?, '-5 months')
              AND date < ?
            GROUP BY merchant
            ORDER BY total DESC
            LIMIT 6
            """,
            (user_id, selected_month["start"], selected_month["next"]),
        ).fetchall()
        if row["total"] * trend_net_ratio > 0
    ]
    connection.close()
    for row in trend_rows:
        row["net_spent"] = row["expenses"] - row["income"]
    max_trend_expenses = max((max(row["net_spent"], 0) for row in trend_rows), default=0)
    max_category_total = max((row["total"] for row in category_trend_rows), default=0)
    max_merchant_total = max((row["total"] for row in merchant_trend_rows), default=0)

    return {
        "selected_month": selected_month,
        "totals": totals,
        "net": totals["income"] - totals["expenses"],
        "net_spent": selected_net_spent,
        "category_rows": category_rows,
        "top_merchants": [
            {
                **row,
                "display_merchant": get_display_merchant(row["merchant"]),
            }
            for row in merchant_rows
        ],
        "transaction_count": transaction_count,
        "monthly_trends": [
            {
                **row,
                "label": datetime.strptime(row["month"], "%Y-%m").strftime("%b %Y"),
                "percent": (max(row["net_spent"], 0) / max_trend_expenses) * 100
                if max_trend_expenses
                else 0,
            }
            for row in trend_rows
        ],
        "category_trends": [
            {
                **row,
                "percent": (row["total"] / max_category_total) * 100
                if max_category_total
                else 0,
                "color": CATEGORY_COLORS.get(row["category"], "#64748b"),
            }
            for row in category_trend_rows
        ],
        "merchant_trends": [
            {
                **row,
                "display_merchant": get_display_merchant(row["merchant"]),
                "percent": (row["total"] / max_merchant_total) * 100
                if max_merchant_total
                else 0,
            }
            for row in merchant_trend_rows
        ],
    }


def get_imports_for_review():
    """Return SMS import rows with review status and redacted raw messages."""
    user_id = current_user_id()
    connection = get_db_connection()
    imported_rows = connection.execute(
        """
        SELECT
            imported_messages.*,
            transactions.date AS transaction_date,
            transactions.merchant AS transaction_merchant,
            transactions.category AS transaction_category,
            transactions.amount AS transaction_amount
        FROM imported_messages
        LEFT JOIN transactions
            ON imported_messages.transaction_id = transactions.id
           AND imported_messages.user_id = transactions.user_id
        WHERE imported_messages.user_id = ?
        ORDER BY imported_messages.id DESC
        """,
        (user_id,),
    ).fetchall()
    connection.close()

    imports_for_review = []
    for row in imported_rows:
        item = dict(row)
        item["status"] = get_import_status(row)
        item["redacted_raw_message"] = redact_sms(row["raw_message"])
        item["raw_message"] = item["redacted_raw_message"]
        if item.get("parsed_merchant"):
            item["redacted_parsed_merchant"] = remove_location_from_merchant(
                item["parsed_merchant"]
            )
        else:
            item["redacted_parsed_merchant"] = None

        if item.get("parsed_description"):
            item["parsed_description"] = redact_sms(item["parsed_description"])

        imports_for_review.append(item)

    return imports_for_review


def get_pending_import_review_count():
    """Count imports waiting for manual review."""
    connection = get_db_connection()
    count = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM imported_messages
        WHERE user_id = ?
          AND COALESCE(is_duplicate, 0) = 0
          AND (
            review_status = 'needs_review'
            OR (
              review_status IS NULL
              AND parsed_amount IS NOT NULL
              AND transaction_id IS NULL
            )
          )
        """
        ,
        (current_user_id(),),
    ).fetchone()["count"]
    connection.close()
    return count


@app.route("/login", methods=["GET", "POST"])
def login():
    """Serve the React login page, with form fallback for old clients."""
    if request.method == "GET":
        return index()

    setup_required = not password_is_configured()
    password = request.form.get("password", "")
    next_url = request.args.get("next") or url_for("index")

    if setup_required:
        confirm_password = request.form.get("confirm_password", "")

        if len(password) >= 8 and password == confirm_password:
            set_login_password(password)
            session.clear()
            session["logged_in"] = True
            session["user_id"] = get_owner_user_id()
            return redirect(url_for("index"))
    else:
        username = request.form.get("username", "owner")
        user = login_password_is_valid(username, password)

        if user:
            session.clear()
            session["logged_in"] = True
            session["user_id"] = user["id"]
            return redirect(next_url)

    return redirect(url_for("login", next=next_url))


@app.route("/invite/<token>", methods=["GET", "POST"])
def accept_invite(token):
    """Serve the React invite acceptance page, with form fallback."""
    if request.method == "GET":
        return index()

    invite = get_pending_invite_by_token(token)
    if invite is None:
        return redirect(url_for("login"))

    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if password == confirm_password:
        try:
            user_id = create_user_from_invite(token, password)
            session.clear()
            session["logged_in"] = True
            session["user_id"] = user_id
            return redirect(url_for("index"))
        except ValueError:
            return redirect(url_for("accept_invite", token=token))

    return redirect(url_for("accept_invite", token=token))


@app.route("/logout", methods=["POST"])
def logout():
    """End the browser login session."""
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/session")
def api_session():
    """Return the public login/session state for the React auth screens."""
    user = get_current_user() if user_is_logged_in() else None

    return jsonify(
        {
            "authenticated": user_is_logged_in(),
            "setup_required": not password_is_configured(),
            "user": (
                {
                    "id": user["id"],
                    "username": user["username"],
                    "display_name": user["display_name"],
                    "is_admin": bool(user["is_admin"]),
                }
                if user
                else None
            ),
        }
    )


@app.route("/api/login", methods=["POST"])
def api_login():
    """Create the first password or authenticate a user from React."""
    data = request.get_json(silent=True) or {}
    setup_required = not password_is_configured()
    password = str(data.get("password", ""))

    if setup_required:
        confirm_password = str(data.get("confirm_password", ""))

        if len(password) < 8:
            return jsonify({"success": False, "error": "Use at least 8 characters."}), 400

        if password != confirm_password:
            return jsonify({"success": False, "error": "Passwords do not match."}), 400

        set_login_password(password)
        session.clear()
        session["logged_in"] = True
        session["user_id"] = get_owner_user_id()
        return jsonify({"success": True, "redirect_url": url_for("index")})

    user = login_password_is_valid(str(data.get("username", "owner")), password)

    if user is None:
        return jsonify({"success": False, "error": "Incorrect username or password."}), 401

    session.clear()
    session["logged_in"] = True
    session["user_id"] = user["id"]
    return jsonify({"success": True, "redirect_url": data.get("next_url") or url_for("index")})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    """End the browser login session from React."""
    session.clear()
    return jsonify({"success": True, "redirect_url": url_for("login")})


@app.route("/api/invite/<token>")
def api_invite(token):
    """Return public invite details for the React invite screen."""
    invite = get_pending_invite_by_token(token)

    if invite is None:
        return jsonify({"success": False, "error": "This invite link is invalid, expired, or already used."}), 404

    return jsonify(
        {
            "success": True,
            "invite": {
                "username": invite["username"],
                "display_name": invite["display_name"],
                "expires_at": invite["expires_at"],
            },
        }
    )


@app.route("/api/invite/<token>/accept", methods=["POST"])
def api_accept_invite(token):
    """Accept a one-time invite and create a user from React."""
    data = request.get_json(silent=True) or {}
    password = str(data.get("password", ""))
    confirm_password = str(data.get("confirm_password", ""))

    if password != confirm_password:
        return jsonify({"success": False, "error": "Passwords do not match."}), 400

    try:
        user_id = create_user_from_invite(token, password)
    except ValueError as invite_error:
        return jsonify({"success": False, "error": str(invite_error)}), 400

    session.clear()
    session["logged_in"] = True
    session["user_id"] = user_id
    return jsonify({"success": True, "redirect_url": url_for("index")})


@app.route("/")
def index():
    """Serve the built React dashboard as the main homepage."""
    react_index = FRONTEND_DIST / "index.html"

    if not react_index.exists():
        return "React build not found. Run npm.cmd run build inside the frontend folder.", 500

    response = make_response(send_file(react_index))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/assets/<path:filename>")
def react_assets(filename):
    """Serve React build assets generated by Vite."""
    return send_file(FRONTEND_DIST / "assets" / filename)


@app.route("/budgets")
@app.route("/cleanup")
@app.route("/app-settings")
@app.route("/day/<selected_date>")
def react_app_page(selected_date=None):
    """Serve React for client-side app pages that do not have Flask templates."""
    return index()


@app.route("/classic")
def classic_dashboard():
    """Redirect the old classic dashboard URL back to the React app."""
    return redirect(url_for("index"))


@app.route("/add", methods=["GET", "POST"])
def add_transaction():
    """Show the add form on GET and save a new transaction on POST."""
    if request.method == "GET":
        return index()

    if request.method == "POST":
        date = request.form["date"]
        amount = float(request.form["amount"])
        merchant = request.form["merchant"].strip()
        category = request.form["category"]
        source = request.form["source"].strip()
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        connection = get_db_connection()
        connection.execute(
            """
            INSERT INTO transactions (
                user_id, date, amount, merchant, category, source, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (current_user_id(), date, amount, merchant, category, source, created_at),
        )
        connection.commit()
        connection.close()

        return redirect(url_for("transactions"))

    return index()


@app.route("/import-message", methods=["GET", "POST"])
def import_message():
    """Import a raw SMS message and create a transaction from a BHD amount."""
    if request.method == "POST":
        api_key_error = require_api_key()
        if api_key_error:
            return api_key_error

        raw_message = get_raw_message_from_request()
        message_hash = get_message_hash(raw_message)
        user_id = current_user_id()
        connection = get_db_connection()
        existing_import = connection.execute(
            """
            SELECT id, transaction_id
            FROM imported_messages
            WHERE message_hash = ?
              AND user_id = ?
              AND COALESCE(is_duplicate, 0) = 0
            ORDER BY id ASC
            LIMIT 1
            """,
            (message_hash, user_id),
        ).fetchone()
        connection.close()

        if existing_import is not None:
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            connection = get_db_connection()
            duplicate_cursor = connection.execute(
                """
                INSERT INTO imported_messages (
                    user_id,
                    transaction_id,
                    raw_message,
                    message_hash,
                    is_duplicate,
                    review_status,
                    review_reason,
                    parser_confidence,
                    created_at
                )
                VALUES (?, ?, ?, ?, 1, 'duplicate', 'This SMS matches an earlier import.', 1, ?)
                """,
                (
                    user_id,
                    existing_import["transaction_id"],
                    raw_message,
                    message_hash,
                    created_at,
                ),
            )
            duplicate_import_id = duplicate_cursor.lastrowid
            connection.commit()
            connection.close()

            if wants_json_response():
                return jsonify(
                    {
                        "success": True,
                        "duplicate": True,
                        "duplicate_import_id": duplicate_import_id,
                        "existing_import_id": existing_import["id"],
                        "existing_transaction_id": existing_import["transaction_id"],
                        "message": "This SMS was already imported.",
                    }
                )

            return redirect(url_for("imports"))

        parsed = parse_bhd_sms(raw_message)

        if parsed is None or parsed.get("merchant") == "Imported SMS":
            learned_parse = parse_with_learned_sms_rules(raw_message)

            if learned_parse:
                parsed = learned_parse

        if parsed is None:
            failed_import_id = log_failed_import(raw_message, message_hash)

            if wants_json_response():
                return jsonify(
                    {
                        "success": False,
                        "import_id": failed_import_id,
                        "error": "No BHD amount was found.",
                    }
                ), 400

            return redirect(url_for("imports"))

        today = datetime.today().strftime("%Y-%m-%d")
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        connection = get_db_connection()
        transaction_id = None
        review = assess_import_review(parsed)

        if review["should_auto_save"]:
            cursor = connection.execute(
                """
                INSERT INTO transactions (
                    user_id, date, amount, merchant, category, source, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    parsed.get("date", today),
                    parsed["amount"],
                    parsed["merchant"],
                    parsed["category"],
                    parsed["source"],
                    created_at,
                ),
            )
            transaction_id = cursor.lastrowid

        connection.execute(
            """
            INSERT INTO imported_messages (
                user_id,
                transaction_id,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                transaction_id,
                raw_message,
                message_hash,
                parsed["amount"],
                parsed["currency"],
                parsed["merchant"],
                parsed["category"],
                parsed.get("date", today),
                parsed["date_text"],
                parsed["description"],
                review["review_status"],
                review["review_reason"],
                review["parser_confidence"],
                created_at,
            ),
        )
        connection.commit()
        connection.close()

        if wants_json_response():
            return jsonify(
                {
                    "success": True,
                    "transaction_id": transaction_id,
                    "amount": parsed["amount"],
                    "currency": parsed["currency"],
                    "merchant": parsed["merchant"],
                    "date": parsed.get("date", today),
                    "category": parsed["category"],
                    "source": parsed["source"],
                    "saved_transaction": bool(transaction_id),
                    "review_status": review["review_status"],
                    "review_reason": review["review_reason"],
                    "parser_confidence": review["parser_confidence"],
                }
            )

        if not transaction_id:
            return redirect(url_for("imports"))

        return redirect(url_for("transactions"))

    return redirect(url_for("imports"))


@app.route("/shortcut-setup")
def shortcut_setup():
    """Redirect the old Shortcut setup page to React Settings."""
    return redirect(url_for("settings"))


@app.route("/category-rules", methods=["GET", "POST"])
def category_rules():
    """List and create merchant keyword category rules."""
    if request.method == "POST":
        keyword = request.form["keyword"].strip().upper()
        category = request.form["category"]
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if keyword:
            connection = get_db_connection()
            connection.execute(
                """
                INSERT INTO category_rules (user_id, keyword, category, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, keyword) DO UPDATE SET category = excluded.category
                """,
                (current_user_id(), keyword, category, created_at),
            )
            connection.commit()
            connection.close()

        return redirect("/cleanup")

    return redirect("/cleanup")


@app.route("/category-rules/<int:rule_id>/delete", methods=["POST"])
def delete_category_rule(rule_id):
    """Delete one category rule."""
    connection = get_db_connection()
    connection.execute(
        "DELETE FROM category_rules WHERE id = ? AND user_id = ?",
        (rule_id, current_user_id()),
    )
    connection.commit()
    connection.close()

    return redirect("/cleanup")


@app.route("/category-budgets", methods=["GET", "POST"])
def category_budgets():
    """Show and update monthly budget limits for each spending category."""
    spending_categories = get_spending_categories()

    if request.method == "POST":
        monthly_budget_limit = float(request.form["monthly_budget_limit"])
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_setting("monthly_budget_limit", monthly_budget_limit)
        connection = get_db_connection()

        for category in spending_categories:
            field_name = f"budget_{category}"
            monthly_limit = float(request.form.get(field_name, 0) or 0)

            if monthly_limit > 0:
                connection.execute(
                    """
                    INSERT INTO category_budgets (user_id, category, monthly_limit, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, category) DO UPDATE SET monthly_limit = excluded.monthly_limit
                    """,
                    (current_user_id(), category, monthly_limit, created_at),
                )
            else:
                connection.execute(
                    "DELETE FROM category_budgets WHERE category = ? AND user_id = ?",
                    (category, current_user_id()),
                )

        connection.commit()
        connection.close()

        return redirect("/budgets")

    return redirect("/budgets")


@app.route("/imports")
def imports():
    """Serve the React import review page."""
    return index()


@app.route("/imports/<int:import_id>/convert-currency", methods=["POST"])
def convert_currency_import(import_id):
    """Convert a reviewed foreign-currency import into a BHD transaction."""
    exchange_rate = float(request.form["exchange_rate"])
    result = convert_foreign_currency_import(import_id, exchange_rate)

    if result is None:
        abort(404)

    return redirect(url_for("imports"))


def convert_foreign_currency_import(import_id, exchange_rate):
    """Convert one non-BHD import row into a BHD transaction."""
    connection = get_db_connection()
    imported_row = connection.execute(
        """
        SELECT *
        FROM imported_messages
        WHERE id = ?
          AND user_id = ?
        """,
        (import_id, current_user_id()),
    ).fetchone()

    if (
        imported_row is None
        or imported_row["transaction_id"] is not None
        or imported_row["parsed_amount"] is None
        or imported_row["parsed_currency"] == "BHD"
        or exchange_rate <= 0
    ):
        connection.close()
        return None

    merchant = imported_row["parsed_merchant"] or "Imported SMS"
    amount_bhd = imported_row["parsed_amount"] * exchange_rate
    category = guess_category_for_merchant(merchant)
    transaction_date = imported_row["parsed_date"] or datetime.today().strftime("%Y-%m-%d")
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = connection.execute(
        """
        INSERT INTO transactions (user_id, date, amount, merchant, category, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            current_user_id(),
            transaction_date,
            amount_bhd,
            merchant,
            category,
            f"BBK SMS ({imported_row['parsed_currency']} converted)",
            created_at,
        ),
    )
    transaction_id = cursor.lastrowid
    connection.execute(
        """
        UPDATE imported_messages
        SET transaction_id = ?,
            review_status = 'saved',
            review_reason = 'Reviewed and converted to BHD transaction.',
            parser_confidence = 1
        WHERE id = ?
          AND user_id = ?
        """,
        (transaction_id, import_id, current_user_id()),
    )
    connection.commit()
    transaction = connection.execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
        (transaction_id, current_user_id()),
    ).fetchone()
    connection.close()

    return add_display_merchants([transaction])[0]


def save_parsed_bhd_import(import_id):
    """Create a BHD transaction from a parsed import that is awaiting review."""
    connection = get_db_connection()
    imported_row = connection.execute(
        """
        SELECT *
        FROM imported_messages
        WHERE id = ?
          AND user_id = ?
        """,
        (import_id, current_user_id()),
    ).fetchone()

    if (
        imported_row is None
        or imported_row["transaction_id"] is not None
        or imported_row["parsed_amount"] is None
        or imported_row["parsed_currency"] != "BHD"
    ):
        connection.close()
        return None

    merchant = imported_row["parsed_merchant"] or "Imported SMS"
    category = imported_row["parsed_category"] or guess_category_for_merchant(merchant)
    transaction_date = imported_row["parsed_date"] or datetime.today().strftime("%Y-%m-%d")
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source = "Bank SMS (AI parsed)" if imported_row["ai_parsed_at"] else "Bank SMS (reviewed)"
    cursor = connection.execute(
        """
        INSERT INTO transactions (user_id, date, amount, merchant, category, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            current_user_id(),
            transaction_date,
            imported_row["parsed_amount"],
            merchant,
            category,
            source,
            created_at,
        ),
    )
    transaction_id = cursor.lastrowid
    connection.execute(
        """
        UPDATE imported_messages
        SET transaction_id = ?,
            review_status = 'saved',
            review_reason = 'Reviewed and saved as BHD transaction.',
            parser_confidence = 1
        WHERE id = ?
          AND user_id = ?
        """,
        (transaction_id, import_id, current_user_id()),
    )
    connection.commit()
    transaction = connection.execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
        (transaction_id, current_user_id()),
    ).fetchone()
    connection.close()

    return add_display_merchants([transaction])[0]


@app.route("/imports/<int:import_id>/create-rule", methods=["POST"])
def create_rule_from_import(import_id):
    """Create a category rule from one imported merchant."""
    category = request.form["category"]
    connection = get_db_connection()
    imported_row = connection.execute(
        """
        SELECT parsed_merchant
        FROM imported_messages
        WHERE id = ?
          AND user_id = ?
        """,
        (import_id, current_user_id()),
    ).fetchone()

    if imported_row is None or not imported_row["parsed_merchant"]:
        connection.close()
        abort(404)

    keyword = imported_row["parsed_merchant"].strip().upper()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connection.execute(
        """
        INSERT INTO category_rules (user_id, keyword, category, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, keyword) DO UPDATE SET category = excluded.category
        """,
        (current_user_id(), keyword, category, created_at),
    )
    connection.execute(
        """
        UPDATE transactions
        SET category = ?
        WHERE user_id = ?
          AND merchant = ?
          AND category = 'Other'
        """,
        (category, current_user_id(), imported_row["parsed_merchant"]),
    )
    connection.commit()
    connection.close()

    return redirect(url_for("imports"))


@app.route("/imports/<int:import_id>/suggest-category", methods=["POST"])
def suggest_category_for_import(import_id):
    """Store an optional AI category suggestion for one import row."""
    connection = get_db_connection()
    imported_row = connection.execute(
        """
        SELECT parsed_merchant
        FROM imported_messages
        WHERE id = ?
          AND user_id = ?
        """,
        (import_id, current_user_id()),
    ).fetchone()
    connection.close()

    if imported_row is None or not imported_row["parsed_merchant"]:
        abort(404)

    suggestion, reason = get_ai_category_suggestion(imported_row["parsed_merchant"])
    suggested_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connection = get_db_connection()
    connection.execute(
        """
        UPDATE imported_messages
        SET ai_suggested_category = ?,
            ai_suggestion_reason = ?,
            ai_suggested_at = ?
        WHERE id = ?
          AND user_id = ?
        """,
        (suggestion, reason, suggested_at, import_id, current_user_id()),
    )
    connection.commit()
    connection.close()

    return redirect(url_for("imports"))


@app.route("/imports/<int:import_id>/apply-ai-category", methods=["POST"])
def apply_ai_category_for_import(import_id):
    """Apply a saved AI suggestion as a rule and update matching transactions."""
    connection = get_db_connection()
    imported_row = connection.execute(
        """
        SELECT parsed_merchant, ai_suggested_category
        FROM imported_messages
        WHERE id = ?
          AND user_id = ?
        """,
        (import_id, current_user_id()),
    ).fetchone()

    if (
        imported_row is None
        or not imported_row["parsed_merchant"]
        or not imported_row["ai_suggested_category"]
    ):
        connection.close()
        abort(404)

    keyword = imported_row["parsed_merchant"].strip().upper()
    category = imported_row["ai_suggested_category"]
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connection.execute(
        """
        INSERT INTO category_rules (user_id, keyword, category, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, keyword) DO UPDATE SET category = excluded.category
        """,
        (current_user_id(), keyword, category, created_at),
    )
    connection.execute(
        """
        UPDATE transactions
        SET category = ?
        WHERE user_id = ?
          AND merchant = ?
          AND category = 'Other'
        """,
        (category, current_user_id(), imported_row["parsed_merchant"]),
    )
    connection.commit()
    connection.close()

    return redirect(url_for("imports"))


@app.route("/imports/<int:import_id>/delete", methods=["POST"])
def delete_import(import_id):
    """Delete one import history row without deleting its transaction."""
    connection = get_db_connection()
    connection.execute(
        "DELETE FROM imported_messages WHERE id = ? AND user_id = ?",
        (import_id, current_user_id()),
    )
    connection.commit()
    connection.close()

    return redirect(url_for("imports"))


@app.route("/imports/clear-failed", methods=["POST"])
def clear_failed_imports():
    """Delete import rows that failed to parse."""
    connection = get_db_connection()
    connection.execute(
        """
        DELETE FROM imported_messages
        WHERE COALESCE(is_duplicate, 0) = 0
          AND user_id = ?
          AND parsed_amount IS NULL
        """,
        (current_user_id(),),
    )
    connection.commit()
    connection.close()

    return redirect(url_for("imports"))


@app.route("/imports/clear-duplicates", methods=["POST"])
def clear_duplicate_imports():
    """Delete duplicate import history rows."""
    connection = get_db_connection()
    connection.execute(
        """
        DELETE FROM imported_messages
        WHERE user_id = ?
          AND COALESCE(is_duplicate, 0) = 1
        """,
        (current_user_id(),),
    )
    connection.commit()
    connection.close()

    return redirect(url_for("imports"))


@app.route("/merchant-aliases", methods=["GET", "POST"])
def merchant_aliases():
    """List and create rules that clean up merchant display names."""
    if request.method == "POST":
        keyword = request.form["keyword"].strip().upper()
        display_name = request.form["display_name"].strip()
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if keyword and display_name:
            connection = get_db_connection()
            connection.execute(
                """
                INSERT INTO merchant_aliases (user_id, keyword, display_name, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, keyword) DO UPDATE SET display_name = excluded.display_name
                """,
                (current_user_id(), keyword, display_name, created_at),
            )
            connection.commit()
            connection.close()

        return redirect("/cleanup")

    return redirect("/cleanup")


@app.route("/merchant-aliases/<int:alias_id>/delete", methods=["POST"])
def delete_merchant_alias(alias_id):
    """Delete one merchant display-name rule."""
    connection = get_db_connection()
    connection.execute(
        "DELETE FROM merchant_aliases WHERE id = ? AND user_id = ?",
        (alias_id, current_user_id()),
    )
    connection.commit()
    connection.close()

    return redirect("/cleanup")


@app.route("/transactions/<int:transaction_id>/edit", methods=["GET", "POST"])
def edit_transaction(transaction_id):
    """Show one transaction in a form and save changes after editing."""
    if request.method == "GET":
        return redirect(url_for("transactions"))

    connection = get_db_connection()
    transaction = connection.execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
        (transaction_id, current_user_id()),
    ).fetchone()

    if transaction is None:
        connection.close()
        abort(404)

    if request.method == "POST":
        date = request.form["date"]
        amount = float(request.form["amount"])
        merchant = request.form["merchant"].strip()
        category = request.form["category"]
        source = request.form["source"].strip()

        connection.execute(
            """
            UPDATE transactions
            SET date = ?, amount = ?, merchant = ?, category = ?, source = ?
            WHERE id = ?
              AND user_id = ?
            """,
            (date, amount, merchant, category, source, transaction_id, current_user_id()),
        )
        connection.commit()
        connection.close()

        return redirect(url_for("transactions"))

    connection.close()
    return redirect(url_for("transactions"))


@app.route("/transactions/<int:transaction_id>/delete", methods=["GET", "POST"])
def delete_transaction(transaction_id):
    """Ask for confirmation on GET and delete one transaction on POST."""
    if request.method == "GET":
        return redirect(url_for("transactions"))

    connection = get_db_connection()
    transaction = connection.execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
        (transaction_id, current_user_id()),
    ).fetchone()

    if transaction is None:
        connection.close()
        abort(404)

    if request.method == "POST":
        connection.execute(
            """
            UPDATE imported_messages
            SET transaction_id = NULL
            WHERE transaction_id = ?
              AND user_id = ?
            """,
            (transaction_id, current_user_id()),
        )
        connection.execute(
            "DELETE FROM transactions WHERE id = ? AND user_id = ?",
            (transaction_id, current_user_id()),
        )
        connection.commit()
        connection.close()

        return redirect(url_for("transactions"))

    connection.close()
    return redirect(url_for("transactions"))


@app.route("/api/health")
def api_health():
    """Return a small health check for API clients."""
    database_connected = False

    try:
        connection = get_db_connection()
        connection.execute("SELECT 1").fetchone()
        connection.close()
        database_connected = True
    except sqlite3.DatabaseError:
        database_connected = False

    return jsonify(
        {
            "status": "ok" if database_connected else "database_error",
            "app": "Expense Tracker",
            "version": APP_VERSION,
            "database_connected": database_connected,
        }
    )


@app.route("/api/config")
def api_config():
    """Return small app settings the React frontend needs."""
    local_import_url = url_for("import_message", _external=True)
    import_url = get_effective_import_url(local_import_url)

    return jsonify(
        {
            "categories": CATEGORIES,
            "spending_categories": get_spending_categories(),
            "api_key": get_api_key(),
            "import_url": import_url,
            "local_import_url": local_import_url,
            "shortcut_public_url": get_shortcut_public_url(),
            "default_usd_to_bhd_rate": DEFAULT_USD_TO_BHD_RATE,
            "default_currency_to_bhd_rates": DEFAULT_CURRENCY_TO_BHD_RATES,
            "default_dashboard_month": get_default_dashboard_month(),
            "show_shortcut_guide": get_setting("shortcut_guide_dismissed", "0") != "1",
        }
    )


@app.route("/api/onboarding/shortcut-guide/dismiss", methods=["POST"])
def api_dismiss_shortcut_guide():
    """Remember that the user has finished the Shortcut setup guide."""
    save_setting("shortcut_guide_dismissed", "1")
    return jsonify({"success": True})


@app.route("/api/dashboard")
def api_dashboard():
    """Return dashboard data as JSON."""
    selected_month = get_month_details(request.args.get("month"))
    return jsonify(get_dashboard_data(selected_month))


@app.route("/api/transactions", methods=["GET", "POST"])
def api_transactions():
    """List or create transactions for API clients."""
    if request.method == "POST":
        api_key_error = require_api_key()
        if api_key_error:
            return api_key_error

        data = request.get_json(silent=True) or {}
        required_fields = ("date", "amount", "merchant", "category", "source")

        if any(not data.get(field) for field in required_fields):
            return jsonify({"success": False, "error": "Missing required fields."}), 400

        if data["category"] not in CATEGORIES:
            return jsonify({"success": False, "error": "Unsupported category."}), 400

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        connection = get_db_connection()
        cursor = connection.execute(
            """
            INSERT INTO transactions (
                user_id, date, amount, merchant, category, source, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                current_user_id(),
                data["date"],
                float(data["amount"]),
                str(data["merchant"]).strip(),
                data["category"],
                str(data["source"]).strip(),
                created_at,
            ),
        )
        transaction_id = cursor.lastrowid
        connection.commit()
        row = connection.execute(
            "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
            (transaction_id, current_user_id()),
        ).fetchone()
        connection.close()

        return jsonify(
            {
                "success": True,
                "transaction": add_display_merchants([row])[0],
            }
        ), 201

    selected_month = get_month_details(request.args.get("month"))
    filters = get_transaction_filters(request.args)
    transaction_data = get_filtered_transactions(selected_month, filters)

    return jsonify(
        {
            "selected_month": selected_month,
            "filters": filters,
            "categories": CATEGORIES,
            "transactions": transaction_data["transactions"],
            "sources": transaction_data["sources"],
            "count": len(transaction_data["transactions"]),
        }
    )


@app.route("/api/transactions/<int:transaction_id>", methods=["PUT", "DELETE"])
def api_transaction_detail(transaction_id):
    """Update or delete one transaction from the React transactions page."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    connection = get_db_connection()
    transaction = connection.execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
        (transaction_id, current_user_id()),
    ).fetchone()

    if transaction is None:
        connection.close()
        return jsonify({"success": False, "error": "Transaction not found."}), 404

    if request.method == "DELETE":
        connection.execute(
            """
            UPDATE imported_messages
            SET transaction_id = NULL
            WHERE transaction_id = ?
              AND user_id = ?
            """,
            (transaction_id, current_user_id()),
        )
        connection.execute(
            "DELETE FROM transactions WHERE id = ? AND user_id = ?",
            (transaction_id, current_user_id()),
        )
        connection.commit()
        connection.close()
        return jsonify({"success": True})

    data = request.get_json(silent=True) or {}
    required_fields = ("date", "amount", "merchant", "category", "source")

    if any(not data.get(field) for field in required_fields):
        connection.close()
        return jsonify({"success": False, "error": "Missing required fields."}), 400

    if data["category"] not in CATEGORIES:
        connection.close()
        return jsonify({"success": False, "error": "Unsupported category."}), 400

    try:
        amount = float(data["amount"])
    except (TypeError, ValueError):
        connection.close()
        return jsonify({"success": False, "error": "Amount must be a number."}), 400

    connection.execute(
        """
        UPDATE transactions
        SET date = ?, amount = ?, merchant = ?, category = ?, source = ?
        WHERE id = ?
          AND user_id = ?
        """,
        (
            str(data["date"]).strip(),
            amount,
            str(data["merchant"]).strip(),
            data["category"],
            str(data["source"]).strip(),
            transaction_id,
            current_user_id(),
        ),
    )
    connection.commit()
    updated_transaction = connection.execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
        (transaction_id, current_user_id()),
    ).fetchone()
    connection.close()

    return jsonify(
        {
            "success": True,
            "transaction": add_display_merchants([updated_transaction])[0],
        }
    )


@app.route("/api/reports")
def api_reports():
    """Return monthly report data as JSON."""
    selected_month = get_month_details(request.args.get("month"))
    return jsonify(get_monthly_report_data(selected_month))


@app.route("/api/imports")
def api_imports():
    """Return SMS import history as JSON for the React review page."""
    imports_for_review = get_imports_for_review()
    counts = {
        "all": len(imports_for_review),
        "failed": sum(1 for item in imports_for_review if item["status"] == "Failed to parse"),
        "duplicates": sum(
            1 for item in imports_for_review if item["status"] == "Duplicate ignored"
        ),
        "needs_review": sum(
            1
            for item in imports_for_review
            if item["status"] in {"Parsed but not saved", "AI parsed, review", "Needs category rule"}
        ),
    }

    return jsonify(
        {
            "imports": imports_for_review,
            "counts": counts,
            "categories": [category for category in CATEGORIES if category != "Income"],
            "default_usd_to_bhd_rate": DEFAULT_USD_TO_BHD_RATE,
            "default_currency_to_bhd_rates": DEFAULT_CURRENCY_TO_BHD_RATES,
        }
    )


@app.route("/api/imports/<int:import_id>", methods=["DELETE"])
def api_delete_import(import_id):
    """Delete one import history row from the React review page."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    connection = get_db_connection()
    cursor = connection.execute(
        "DELETE FROM imported_messages WHERE id = ? AND user_id = ?",
        (import_id, current_user_id()),
    )
    connection.commit()
    connection.close()

    if cursor.rowcount == 0:
        return jsonify({"success": False, "error": "Import row not found."}), 404

    return jsonify({"success": True})


@app.route("/api/imports/<int:import_id>/convert-currency", methods=["POST"])
def api_convert_currency_import(import_id):
    """Convert a foreign-currency import into a BHD transaction from React."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    data = request.get_json(silent=True) or {}

    try:
        exchange_rate = float(data.get("exchange_rate", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Exchange rate must be a number."}), 400

    if exchange_rate <= 0:
        return jsonify({"success": False, "error": "Exchange rate must be greater than 0."}), 400

    transaction = convert_foreign_currency_import(import_id, exchange_rate)

    if transaction is None:
        return jsonify({"success": False, "error": "Import cannot be converted."}), 404

    return jsonify({"success": True, "transaction": transaction})


@app.route("/api/imports/<int:import_id>/ai-parse", methods=["POST"])
def api_ai_parse_import(import_id):
    """Use AI to extract transaction fields from one import row."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    connection = get_db_connection()
    imported_row = connection.execute(
        """
        SELECT *
        FROM imported_messages
        WHERE id = ?
          AND user_id = ?
        """,
        (import_id, current_user_id()),
    ).fetchone()
    connection.close()

    if imported_row is None:
        return jsonify({"success": False, "error": "Import row not found."}), 404

    parsed, error = parse_sms_with_ai(imported_row["raw_message"])

    if error:
        return jsonify({"success": False, "error": error}), 400

    parsed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    review = assess_import_review(parsed)
    connection = get_db_connection()
    connection.execute(
        """
        UPDATE imported_messages
        SET parsed_amount = ?,
            parsed_currency = ?,
            parsed_merchant = ?,
            parsed_category = ?,
            parsed_date = ?,
            parsed_date_text = ?,
            parsed_description = ?,
            ai_parse_confidence = ?,
            ai_parse_reason = ?,
            ai_parsed_at = ?,
            review_status = 'needs_review',
            review_reason = ?,
            parser_confidence = ?
        WHERE id = ?
          AND user_id = ?
        """,
        (
            parsed["amount"],
            parsed["currency"],
            parsed["merchant"],
            parsed["category"],
            parsed["date"],
            parsed["date_text"],
            parsed["description"],
            parsed["confidence"],
            parsed["reason"],
            parsed_at,
            review["review_reason"],
            review["parser_confidence"],
            import_id,
            current_user_id(),
        ),
    )
    connection.commit()
    connection.close()
    learned_rule_id = save_learned_sms_rule(imported_row["raw_message"], parsed)

    return jsonify(
        {
            "success": True,
            "parsed": parsed,
            "learned_rule_id": learned_rule_id,
        }
    )


@app.route("/api/imports/<int:import_id>/repair", methods=["POST"])
def api_repair_import(import_id):
    """Manually repair parsed fields for an import row before saving."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    data = request.get_json(silent=True) or {}
    required_fields = ("amount", "currency", "merchant", "date", "category")

    if any(not data.get(field) for field in required_fields):
        return jsonify({"success": False, "error": "Missing repair fields."}), 400

    try:
        amount = float(data["amount"])
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Amount must be a number."}), 400

    currency = str(data["currency"]).strip().upper()
    merchant = str(data["merchant"]).strip()
    category = data["category"]
    date_value = str(data["date"]).strip()

    if len(currency) != 3:
        return jsonify({"success": False, "error": "Currency must be a 3-letter code."}), 400

    if category not in CATEGORIES:
        return jsonify({"success": False, "error": "Unsupported category."}), 400

    try:
        datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError:
        return jsonify({"success": False, "error": "Date must use YYYY-MM-DD."}), 400

    if amount <= 0:
        return jsonify({"success": False, "error": "Amount must be greater than 0."}), 400

    if not merchant:
        return jsonify({"success": False, "error": "Merchant is required."}), 400

    connection = get_db_connection()
    imported_row = connection.execute(
        """
        SELECT *
        FROM imported_messages
        WHERE id = ?
          AND user_id = ?
        """,
        (import_id, current_user_id()),
    ).fetchone()

    if imported_row is None:
        connection.close()
        return jsonify({"success": False, "error": "Import row not found."}), 404

    if imported_row["transaction_id"] is not None:
        connection.close()
        return jsonify({"success": False, "error": "This import already has a transaction."}), 400

    repaired_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_text = str(data.get("date_text") or date_value).strip()
    repair_note = f"Manually repaired on {repaired_at}."
    connection.execute(
        """
        UPDATE imported_messages
        SET parsed_amount = ?,
            parsed_currency = ?,
            parsed_merchant = ?,
            parsed_category = ?,
            parsed_date = ?,
            parsed_date_text = ?,
            parsed_description = ?,
            ai_parse_reason = COALESCE(ai_parse_reason, ?),
            review_status = 'needs_review',
            review_reason = 'Manually repaired. Review and save when ready.',
            parser_confidence = 1
        WHERE id = ?
          AND user_id = ?
        """,
        (
            amount,
            currency,
            merchant,
            category,
            date_value,
            date_text,
            imported_row["raw_message"],
            repair_note,
            import_id,
            current_user_id(),
        ),
    )
    connection.commit()
    repaired_import = connection.execute(
        """
        SELECT *
        FROM imported_messages
        WHERE id = ?
          AND user_id = ?
        """,
        (import_id, current_user_id()),
    ).fetchone()
    connection.close()

    return jsonify({"success": True, "import": dict(repaired_import)})


@app.route("/api/imports/<int:import_id>/save-bhd", methods=["POST"])
def api_save_bhd_import(import_id):
    """Save a reviewed parsed BHD import as a transaction."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    transaction = save_parsed_bhd_import(import_id)

    if transaction is None:
        return jsonify({"success": False, "error": "Import cannot be saved as BHD."}), 404

    return jsonify({"success": True, "transaction": transaction})


@app.route("/api/imports/<int:import_id>/learn-rule", methods=["POST"])
def api_learn_rule_from_import(import_id):
    """Create a learned parser rule from a repaired or parsed import row."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    connection = get_db_connection()
    imported_row = connection.execute(
        """
        SELECT *
        FROM imported_messages
        WHERE id = ?
          AND user_id = ?
        """,
        (import_id, current_user_id()),
    ).fetchone()
    connection.close()

    if imported_row is None:
        return jsonify({"success": False, "error": "Import row not found."}), 404

    if (
        imported_row["parsed_amount"] is None
        or not imported_row["parsed_currency"]
        or not imported_row["parsed_merchant"]
    ):
        return jsonify({"success": False, "error": "Repair this import before learning a rule."}), 400

    parsed = {
        "amount": imported_row["parsed_amount"],
        "currency": imported_row["parsed_currency"],
        "merchant": imported_row["parsed_merchant"],
        "category": imported_row["parsed_category"] or guess_category_for_merchant(imported_row["parsed_merchant"]),
        "date_text": imported_row["parsed_date_text"] or imported_row["parsed_date"] or "",
    }
    rule_id = save_learned_sms_rule(imported_row["raw_message"], parsed)

    if not rule_id:
        return jsonify(
            {
                "success": False,
                "error": "Could not learn a safe parser rule from this SMS. Make sure the repaired values appear in the raw SMS.",
            }
        ), 400

    return jsonify({"success": True, "rule_id": rule_id})


@app.route("/api/imports/clear", methods=["POST"])
def api_clear_imports():
    """Clear failed or duplicate import rows from the React review page."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    data = request.get_json(silent=True) or {}
    clear_type = data.get("type")
    connection = get_db_connection()

    if clear_type == "failed":
        cursor = connection.execute(
            """
            DELETE FROM imported_messages
            WHERE COALESCE(is_duplicate, 0) = 0
              AND user_id = ?
              AND parsed_amount IS NULL
            """,
            (current_user_id(),),
        )
    elif clear_type == "duplicates":
        cursor = connection.execute(
            """
            DELETE FROM imported_messages
            WHERE user_id = ?
              AND COALESCE(is_duplicate, 0) = 1
            """,
            (current_user_id(),),
        )
    else:
        connection.close()
        return jsonify({"success": False, "error": "Unsupported clear type."}), 400

    deleted_count = cursor.rowcount
    connection.commit()
    connection.close()

    return jsonify({"success": True, "deleted_count": deleted_count})


@app.route("/api/category-rules", methods=["GET", "POST"])
def api_category_rules():
    """List or create merchant keyword category rules for React."""
    if request.method == "POST":
        api_key_error = require_api_key()
        if api_key_error:
            return api_key_error

        data = request.get_json(silent=True) or {}
        keyword = str(data.get("keyword", "")).strip().upper()
        category = data.get("category")

        if not keyword:
            return jsonify({"success": False, "error": "Keyword is required."}), 400

        if category not in get_spending_categories():
            return jsonify({"success": False, "error": "Unsupported category."}), 400

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        connection = get_db_connection()
        connection.execute(
            """
            INSERT INTO category_rules (user_id, keyword, category, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, keyword) DO UPDATE SET category = excluded.category
            """,
            (current_user_id(), keyword, category, created_at),
        )
        updated_rows = connection.execute(
            """
            UPDATE transactions
            SET category = ?
            WHERE user_id = ?
              AND UPPER(merchant) LIKE ?
              AND category = 'Other'
            """,
            (category, current_user_id(), f"%{keyword}%"),
        ).rowcount
        connection.commit()
        connection.close()

        return jsonify({"success": True, "updated_transactions": updated_rows}), 201

    return jsonify(
        {
            "rules": get_saved_category_rules(),
            "categories": get_spending_categories(),
        }
    )


@app.route("/api/category-rules/<int:rule_id>", methods=["DELETE"])
def api_delete_category_rule(rule_id):
    """Delete one category rule from React."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    connection = get_db_connection()
    cursor = connection.execute(
        "DELETE FROM category_rules WHERE id = ? AND user_id = ?",
        (rule_id, current_user_id()),
    )
    connection.commit()
    connection.close()

    if cursor.rowcount == 0:
        return jsonify({"success": False, "error": "Rule not found."}), 404

    return jsonify({"success": True})


@app.route("/api/merchant-aliases", methods=["GET", "POST"])
def api_merchant_aliases():
    """List or create merchant display-name cleanup rules for React."""
    if request.method == "POST":
        api_key_error = require_api_key()
        if api_key_error:
            return api_key_error

        data = request.get_json(silent=True) or {}
        keyword = str(data.get("keyword", "")).strip().upper()
        display_name = str(data.get("display_name", "")).strip()

        if not keyword or not display_name:
            return jsonify(
                {"success": False, "error": "Keyword and display name are required."}
            ), 400

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        connection = get_db_connection()
        connection.execute(
            """
            INSERT INTO merchant_aliases (user_id, keyword, display_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, keyword) DO UPDATE SET display_name = excluded.display_name
            """,
            (current_user_id(), keyword, display_name, created_at),
        )
        connection.commit()
        connection.close()

        return jsonify({"success": True}), 201

    return jsonify({"aliases": [dict(alias) for alias in get_merchant_aliases()]})


@app.route("/api/merchant-aliases/<int:alias_id>", methods=["DELETE"])
def api_delete_merchant_alias(alias_id):
    """Delete one merchant alias from React."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    connection = get_db_connection()
    cursor = connection.execute(
        "DELETE FROM merchant_aliases WHERE id = ? AND user_id = ?",
        (alias_id, current_user_id()),
    )
    connection.commit()
    connection.close()

    if cursor.rowcount == 0:
        return jsonify({"success": False, "error": "Alias not found."}), 404

    return jsonify({"success": True})


@app.route("/api/merchant-intelligence")
def api_merchant_intelligence():
    """Return merchant cleanup suggestions and grouping data for React."""
    return jsonify(get_merchant_intelligence())


@app.route("/api/sms-parser-rules")
def api_sms_parser_rules():
    """List AI/manual learned SMS parser rules for React cleanup tools."""
    connection = get_db_connection()
    rules = [
        {
            **dict(row),
            "example_message": redact_sms(row["example_message"]),
        }
        for row in connection.execute(
            """
            SELECT *
            FROM sms_parser_rules
            WHERE user_id = ?
            ORDER BY id DESC
            """
            ,
            (current_user_id(),),
        ).fetchall()
    ]
    connection.close()

    return jsonify({"rules": rules})


@app.route("/api/sms-parser-rules/<int:rule_id>", methods=["DELETE"])
def api_delete_sms_parser_rule(rule_id):
    """Delete one learned SMS parser rule."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    connection = get_db_connection()
    cursor = connection.execute(
        "DELETE FROM sms_parser_rules WHERE id = ? AND user_id = ?",
        (rule_id, current_user_id()),
    )
    connection.commit()
    connection.close()

    if cursor.rowcount == 0:
        return jsonify({"success": False, "error": "Parser rule not found."}), 404

    return jsonify({"success": True})


@app.route("/api/budgets", methods=["GET", "POST"])
def api_budgets():
    """Return or update monthly and per-category budgets for React."""
    spending_categories = get_spending_categories()

    if request.method == "POST":
        api_key_error = require_api_key()
        if api_key_error:
            return api_key_error

        data = request.get_json(silent=True) or {}
        monthly_budget_limit = float(data.get("monthly_budget_limit", 0) or 0)
        category_budgets = data.get("category_budgets", {})
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_id = current_user_id()

        save_setting("monthly_budget_limit", monthly_budget_limit)
        connection = get_db_connection()

        for category in spending_categories:
            monthly_limit = float(category_budgets.get(category, 0) or 0)

            if monthly_limit > 0:
                connection.execute(
                    """
                    INSERT INTO category_budgets (user_id, category, monthly_limit, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, category) DO UPDATE SET monthly_limit = excluded.monthly_limit
                    """,
                    (user_id, category, monthly_limit, created_at),
                )
            else:
                connection.execute(
                    "DELETE FROM category_budgets WHERE category = ? AND user_id = ?",
                    (category, user_id),
                )

        connection.commit()
        connection.close()

        return jsonify({"success": True})

    budgets = get_category_budgets()

    return jsonify(
        {
            "monthly_budget_limit": get_monthly_budget_limit(),
            "category_budgets": {
                category: budgets.get(category, 0) for category in spending_categories
            },
            "categories": spending_categories,
        }
    )


@app.route("/api/settings/health")
def api_settings_health():
    """Return Shortcut health, backup links, and security details for React."""
    local_import_url = url_for("import_message", _external=True)
    shortcut_public_url = get_shortcut_public_url()
    import_url = get_effective_import_url(local_import_url)
    shortcut_body = {"raw_message": "Expense Tracker test import"}
    url_hint = (
        "Saved iPhone/ngrok URL"
        if shortcut_public_url
        else (
            "Public URL detected"
            if "ngrok" in import_url or "https://" in import_url
            else "Local URL only"
        )
    )
    current_user = get_current_user()
    is_admin = bool(current_user and current_user["is_admin"])
    user_count = None
    pending_invite_count = None

    if is_admin:
        connection = get_db_connection()
        user_count = connection.execute(
            "SELECT COUNT(*) AS count FROM users WHERE active = 1"
        ).fetchone()["count"]
        pending_invite_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM user_invites
            WHERE used_at IS NULL
              AND (expires_at IS NULL OR expires_at > ?)
            """,
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),),
        ).fetchone()["count"]
        connection.close()

    response = {
        "permissions": {
            "is_admin": is_admin,
            "can_manage_invites": is_admin,
            "can_manage_backups": is_admin,
            "can_view_server_health": is_admin,
        },
        "multi_user": {
            "enabled": True,
            "public_registration": False,
            "current_user": {
                "id": current_user["id"],
                "username": current_user["username"],
                "display_name": current_user["display_name"],
                "is_admin": bool(current_user["is_admin"]),
            }
            if current_user
            else None,
            "active_user_count": user_count,
            "pending_invite_count": pending_invite_count,
            "mode": "Manual users only",
        },
        "automation_health": get_automation_health(),
        "api_key": get_api_key(),
        "import_url": import_url,
        "local_import_url": local_import_url,
        "shortcut_public_url": shortcut_public_url,
        "shortcut_body": shortcut_body,
        "shortcut_body_text": json.dumps(shortcut_body),
        "shortcut_header_key": "X-API-Key",
        "shortcut_header_value": get_api_key(),
        "url_hint": url_hint,
        "data_quality_alerts": get_data_quality_alerts(),
    }

    if is_admin:
        response.update(
            {
                "backup_download_url": url_for(
                    "download_backup",
                    api_key=get_api_key(),
                    _external=False,
                ),
                "backup_history": get_backup_history(),
                "deployment_readiness": get_private_deployment_readiness(import_url),
                "database_file": str(DATABASE),
            }
        )

    return jsonify(response)


@app.route("/api/admin/invites", methods=["GET", "POST"])
def api_admin_invites():
    """List users/invites or create a private one-time invite."""
    admin_error = require_admin_user()
    if admin_error:
        return admin_error

    connection = get_db_connection()

    if request.method == "POST":
        data = request.get_json(silent=True) or {}

        try:
            invite = create_private_invite(
                str(data.get("username", "")),
                str(data.get("display_name", "")),
            )
        except ValueError as invite_error:
            connection.close()
            return jsonify({"success": False, "error": str(invite_error)}), 400

        connection.close()
        return jsonify({"success": True, "invite": invite}), 201

    users = [
        {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "is_admin": bool(row["is_admin"]),
            "active": bool(row["active"]),
            "created_at": row["created_at"],
            "api_key_last6": row["api_key"][-6:] if row["api_key"] else "",
        }
        for row in connection.execute(
            """
            SELECT id, username, display_name, is_admin, active, created_at, api_key
            FROM users
            ORDER BY id ASC
            """
        ).fetchall()
    ]
    invites = [
        {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "used_at": row["used_at"],
            "status": (
                "used"
                if row["used_at"]
                else (
                    "expired"
                    if row["expires_at"]
                    and row["expires_at"] <= datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    else "pending"
                )
            ),
        }
        for row in connection.execute(
            """
            SELECT id, username, display_name, created_at, expires_at, used_at
            FROM user_invites
            ORDER BY id DESC
            LIMIT 12
            """
        ).fetchall()
    ]
    connection.close()

    return jsonify({"success": True, "users": users, "invites": invites})


@app.route("/api/settings/shortcut-public-url", methods=["POST"])
def api_save_shortcut_public_url():
    """Save the public iPhone/ngrok Shortcut URL used outside the PC."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    data = request.get_json(silent=True) or {}
    url_value = str(data.get("shortcut_public_url", "")).strip()

    if not url_value:
        save_setting("shortcut_public_url", "")
        return jsonify({"success": True, "shortcut_public_url": ""})

    normalized_url = normalize_shortcut_public_url(url_value)

    if not normalized_url:
        return jsonify(
            {
                "success": False,
                "error": "Enter a URL starting with http:// or https://.",
            }
        ), 400

    save_setting("shortcut_public_url", normalized_url)
    return jsonify({"success": True, "shortcut_public_url": normalized_url})


@app.route("/api/backups/create", methods=["POST"])
def api_create_backup():
    """Create a backup immediately from React Settings."""
    admin_error = require_admin_user()
    if admin_error:
        return admin_error

    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    backup_path = backup_current_database()
    return jsonify(
        {
            "success": True,
            "backup": {
                "filename": backup_path.name,
                "path": str(backup_path),
                "size_bytes": backup_path.stat().st_size,
                "created_at": datetime.fromtimestamp(backup_path.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            },
            "backup_history": get_backup_history(),
        }
    )


@app.route("/api/backups/restore", methods=["POST"])
def api_restore_backup():
    """Restore an uploaded SQLite backup after creating a safety backup."""
    admin_error = require_admin_user()
    if admin_error:
        return admin_error

    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    confirmation = request.form.get("confirmation", "")

    if confirmation != "RESTORE":
        return jsonify({"success": False, "error": "Type RESTORE to confirm."}), 400

    uploaded_file = request.files.get("backup_file")

    if uploaded_file is None or not uploaded_file.filename:
        return jsonify({"success": False, "error": "Choose a backup file."}), 400

    BACKUP_DIR.mkdir(exist_ok=True)
    temporary_path = BACKUP_DIR / "restore-upload-temp.db"
    uploaded_file.save(temporary_path)

    if not is_valid_backup_database(temporary_path):
        temporary_path.unlink(missing_ok=True)
        return jsonify({"success": False, "error": "That file is not a valid backup."}), 400

    safety_backup_path = backup_current_database("before-restore")
    shutil.copy2(temporary_path, DATABASE)
    temporary_path.unlink(missing_ok=True)
    init_db()

    return jsonify(
        {
            "success": True,
            "message": "Backup restored successfully.",
            "safety_backup": safety_backup_path.name,
            "backup_history": get_backup_history(),
        }
    )


@app.route("/api/backups/<path:filename>/download")
def api_download_saved_backup(filename):
    """Download one saved backup by filename."""
    admin_error = require_admin_user()
    if admin_error:
        return admin_error

    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    backup_path = get_backup_path_from_name(filename)

    if backup_path is None:
        abort(404)

    return send_file(
        backup_path,
        as_attachment=True,
        download_name=backup_path.name,
    )


@app.route("/api/settings/send-test-import", methods=["POST"])
def api_send_test_import():
    """Create a harmless import-history row to verify Shortcut plumbing."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    raw_message = f"Expense Tracker test import created from Settings at {created_at}"
    message_hash = get_message_hash(f"{raw_message}-{secrets.token_urlsafe(8)}")
    connection = get_db_connection()
    cursor = connection.execute(
        """
        INSERT INTO imported_messages (
            user_id,
            raw_message,
            message_hash,
            parsed_description,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (current_user_id(), raw_message, message_hash, raw_message, created_at),
    )
    connection.commit()
    import_id = cursor.lastrowid
    connection.close()

    return jsonify(
        {
            "success": True,
            "import_id": import_id,
            "message": "Test import received by Flask and stored in import history.",
        }
    )


@app.route("/api/settings/regenerate-key", methods=["POST"])
def api_regenerate_key():
    """Regenerate the API key from React settings."""
    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    return jsonify({"success": True, "api_key": regenerate_api_key()})


@app.route("/transactions")
def transactions():
    """Serve the React transactions page."""
    return index()


@app.route("/reports")
def reports():
    """Serve the React reports page."""
    return index()


@app.route("/reports/monthly.csv")
def export_monthly_report_csv():
    """Download the selected month's transactions as a CSV file."""
    selected_month = get_selected_month()
    connection = get_db_connection()
    rows = connection.execute(
        """
        SELECT *
        FROM transactions
        WHERE user_id = ?
          AND date >= ?
          AND date < ?
        ORDER BY date ASC, id ASC
        """,
        (current_user_id(), selected_month["start"], selected_month["next"]),
    ).fetchall()
    connection.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "date",
            "merchant",
            "display_merchant",
            "category",
            "source",
            "amount_bhd",
            "created_at",
        ]
    )

    for row in rows:
        writer.writerow(
            [
                row["id"],
                row["date"],
                row["merchant"],
                get_display_merchant(row["merchant"]),
                row["category"],
                row["source"],
                f"{row['amount']:.3f}",
                row["created_at"],
            ]
        )

    response = make_response(output.getvalue())
    filename = f"expense-report-{selected_month['value']}.csv"
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@app.route("/backup", methods=["GET", "POST"])
def backup():
    """Download or restore the SQLite database."""
    admin_error = require_admin_user()
    if admin_error:
        return admin_error

    if request.method == "POST":
        api_key_error = require_api_key()
        if api_key_error:
            return api_key_error

        uploaded_file = request.files.get("backup_file")

        if uploaded_file is None or not uploaded_file.filename:
            return redirect(url_for("settings"))

        BACKUP_DIR.mkdir(exist_ok=True)
        temporary_path = BACKUP_DIR / "restore-upload-temp.db"
        uploaded_file.save(temporary_path)

        if not is_valid_backup_database(temporary_path):
            temporary_path.unlink(missing_ok=True)
            return redirect(url_for("settings"))

        safety_backup_path = backup_current_database("before-restore")
        shutil.copy2(temporary_path, DATABASE)
        temporary_path.unlink(missing_ok=True)
        init_db()

        return redirect(url_for("settings"))

    return redirect(url_for("settings"))


@app.route("/backup/download")
def download_backup():
    """Download the current SQLite database as a backup file."""
    admin_error = require_admin_user()
    if admin_error:
        return admin_error

    api_key_error = require_api_key()
    if api_key_error:
        return api_key_error

    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return send_file(
        DATABASE,
        as_attachment=True,
        download_name=f"expense-tracker-backup-{timestamp}.db",
    )


@app.route("/security", methods=["GET", "POST"])
def security():
    """Show and regenerate the API key."""
    if request.method == "POST":
        api_key_error = require_api_key()
        if api_key_error:
            return api_key_error

        new_api_key = regenerate_api_key()
        return redirect(url_for("settings"))

    return redirect(url_for("settings"))


@app.route("/MULTI_USER_PLAN.md")
def multi_user_plan_file():
    """Serve the internal multi-user planning document."""
    admin_error = require_admin_user()
    if admin_error:
        return admin_error

    return send_file(BASE_DIR / "MULTI_USER_PLAN.md", mimetype="text/markdown")


@app.route("/settings", methods=["GET", "POST"])
def settings():
    """Show and update beginner-friendly app settings."""
    if request.method == "POST":
        monthly_budget_limit = float(request.form["monthly_budget_limit"])
        save_setting("monthly_budget_limit", monthly_budget_limit)

        return redirect(url_for("settings"))

    return index()


# Initialize the database when the app starts.
init_db()


if __name__ == "__main__":
    # host="0.0.0.0" lets other devices on the same Wi-Fi reach this app.
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
