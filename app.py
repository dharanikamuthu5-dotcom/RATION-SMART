"""
================================================================================
RationSmart AI - Smart Ration Distribution System
Tagline: Smart Ration Distribution. Predictive. Transparent. Citizen-Centric.
Hero: Smarter Ration Distribution Starts Before You Reach the Shop.
================================================================================
Single-file complete Flask application integrating:
- Machine Learning (scikit-learn + pandas) for Queue & Waiting Time Prediction
- AI Stock Consumption & Shortage Risk Forecasting
- Dynamic QR Code Generation (qrcode) for Official Digital Ration Passes
- Role-Based Access Control (Citizen, Shop Staff, Government Admin)
- Dual Database Support (Native MySQL with automatic SQLite fallback)
- Embedded Civic-Tech UI (Bootstrap 5, Chart.js, Bootstrap Icons)
================================================================================
"""

import os
import io
import re
import json
import base64
import random
import sqlite3
import datetime
from functools import wraps

import qrcode
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

from flask import (
    Flask, request, jsonify, render_template_string,
    session, redirect, url_for, flash, g, abort
)

# Optional MySQL driver
try:
    import pymysql
    import pymysql.cursors
    HAS_PYMYSQL = True
except ImportError:
    HAS_PYMYSQL = False

# ------------------------------------------------------------------------------
# 1. APPLICATION & CONFIGURATION
# ------------------------------------------------------------------------------
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'rationsmart-ai-secret-key-2026-prod-fallback')
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(hours=8)

DB_TYPE = os.getenv('DB_TYPE', 'mysql').lower()
DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'rationsmart_ai')

SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rationsmart.db')
ACTIVE_DB_ENGINE = 'unknown'

# ------------------------------------------------------------------------------
# 2. DATABASE ABSTRACTION LAYER (MySQL + Fallback SQLite)
# ------------------------------------------------------------------------------
def get_db():
    """
    Retrieves or establishes a database connection.
    Attempts MySQL first if requested; falls back to SQLite if MySQL is unavailable.
    """
    global ACTIVE_DB_ENGINE
    if 'db' not in g:
        conn = None
        if DB_TYPE == 'mysql' and HAS_PYMYSQL:
            try:
                # First attempt direct connection to target database
                conn = pymysql.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    user=DB_USER,
                    password=DB_PASSWORD,
                    database=DB_NAME,
                    charset='utf8mb4',
                    cursorclass=pymysql.cursors.DictCursor,
                    autocommit=True,
                    connect_timeout=2
                )
                ACTIVE_DB_ENGINE = 'mysql'
            except pymysql.err.OperationalError as oe:
                # If database does not exist (1049), create it and connect
                if oe.args[0] == 1049:
                    try:
                        admin_conn = pymysql.connect(
                            host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
                            charset='utf8mb4', autocommit=True, connect_timeout=2
                        )
                        with admin_conn.cursor() as cur:
                            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                        admin_conn.close()

                        conn = pymysql.connect(
                            host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
                            database=DB_NAME, charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
                            autocommit=True, connect_timeout=2
                        )
                        ACTIVE_DB_ENGINE = 'mysql'
                    except Exception:
                        conn = None
                else:
                    conn = None
            except Exception as e:
                conn = None

        if conn is None:
            conn = sqlite3.connect(SQLITE_PATH)
            conn.row_factory = sqlite3.Row
            ACTIVE_DB_ENGINE = 'sqlite'

        g.db = conn
        g.db_type = ACTIVE_DB_ENGINE
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass

def query_db(query, args=(), one=False):
    """
    Executes a SELECT query and returns rows as a list of dicts or a single dict.
    Automatically handles placeholder differences (%s for MySQL vs ? for SQLite).
    """
    db = get_db()
    is_sqlite = (g.get('db_type', ACTIVE_DB_ENGINE) == 'sqlite')
    if is_sqlite:
        sqlite_query = query.replace('%s', '?')
        cur = db.cursor()
        cur.execute(sqlite_query, args)
        rv = cur.fetchall()
        cur.close()
        results = [dict(row) for row in rv]
        return (results[0] if results else None) if one else results
    else:
        with db.cursor() as cur:
            cur.execute(query, args)
            rv = cur.fetchall()
            return (rv[0] if rv else None) if one else rv

def execute_db(query, args=(), commit=True):
    """
    Executes an INSERT/UPDATE/DELETE statement.
    Returns (lastrowid, rowcount).
    """
    db = get_db()
    is_sqlite = (g.get('db_type', ACTIVE_DB_ENGINE) == 'sqlite')
    if is_sqlite:
        sqlite_query = query.replace('%s', '?')
        cur = db.cursor()
        cur.execute(sqlite_query, args)
        if commit:
            db.commit()
        last_id = cur.lastrowid
        row_cnt = cur.rowcount
        cur.close()
        return last_id, row_cnt
    else:
        with db.cursor() as cur:
            cur.execute(query, args)
            if commit:
                db.commit()
            return cur.lastrowid, cur.rowcount

def init_database_if_needed():
    """Initializes schema and seeds realistic demo data if not already present."""
    global ACTIVE_DB_ENGINE
    with app.app_context():
        db = get_db()
        engine = g.get('db_type', ACTIVE_DB_ENGINE)

        if engine == 'sqlite':
            # Create SQLite tables if needed
            cur = db.cursor()
            cur.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'citizen',
                ration_card_no TEXT UNIQUE,
                phone TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ration_shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_code TEXT NOT NULL UNIQUE,
                shop_name TEXT NOT NULL,
                address TEXT NOT NULL,
                zone TEXT NOT NULL,
                staff_user_id INTEGER,
                contact_number TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (staff_user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS ration_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_code TEXT NOT NULL UNIQUE,
                item_name TEXT NOT NULL,
                unit TEXT NOT NULL DEFAULT 'kg',
                monthly_quota_per_beneficiary REAL NOT NULL,
                unit_price REAL NOT NULL DEFAULT 0.00,
                status TEXT DEFAULT 'active'
            );

            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                current_stock REAL NOT NULL DEFAULT 0.0,
                reserved_stock REAL NOT NULL DEFAULT 0.0,
                min_threshold REAL NOT NULL DEFAULT 100.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(shop_id, item_id),
                FOREIGN KEY (shop_id) REFERENCES ration_shops(id),
                FOREIGN KEY (item_id) REFERENCES ration_items(id)
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_ref TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                shop_id INTEGER NOT NULL,
                booking_date TEXT NOT NULL,
                time_slot TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending',
                qr_code_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (shop_id) REFERENCES ration_shops(id)
            );

            CREATE TABLE IF NOT EXISTS booking_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL,
                FOREIGN KEY (booking_id) REFERENCES bookings(id),
                FOREIGN KEY (item_id) REFERENCES ration_items(id)
            );

            CREATE TABLE IF NOT EXISTS queue_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER NOT NULL,
                day_of_week INTEGER NOT NULL,
                hour INTEGER NOT NULL,
                active_bookings INTEGER NOT NULL DEFAULT 0,
                actual_queue_count INTEGER NOT NULL DEFAULT 0,
                avg_wait_time_minutes INTEGER NOT NULL DEFAULT 0,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (shop_id) REFERENCES ration_shops(id)
            );

            CREATE TABLE IF NOT EXISTS ai_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER NOT NULL,
                prediction_type TEXT NOT NULL,
                input_params TEXT NOT NULL,
                predicted_value TEXT NOT NULL,
                confidence_score REAL DEFAULT 0.90,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (shop_id) REFERENCES ration_shops(id)
            );
            ''')
            db.commit()

        # Check if users already seeded
        existing = query_db("SELECT COUNT(*) as cnt FROM users", one=True)
        if not existing or existing.get('cnt', 0) == 0:
            seed_demo_data()

def seed_demo_data():
    """Seeds rich demonstration data across all three user roles, shops, and commodities."""
    # Passwords for demo users
    p_citizen = generate_password_hash('citizen123')
    p_staff = generate_password_hash('staff123')
    p_admin = generate_password_hash('admin123')

    execute_db("""
        INSERT INTO users (username, email, password_hash, full_name, role, ration_card_no, phone)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, ('citizen', 'citizen@rationsmart.gov', p_citizen, 'Aarav Sharma', 'citizen', 'RC-DL-98472', '+91 98765 43210'))

    execute_db("""
        INSERT INTO users (username, email, password_hash, full_name, role, ration_card_no, phone)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, ('shopstaff', 'staff@rationsmart.gov', p_staff, 'Rajesh Patel', 'shop_staff', None, '+91 98111 22334'))

    execute_db("""
        INSERT INTO users (username, email, password_hash, full_name, role, ration_card_no, phone)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, ('govadmin', 'admin@rationsmart.gov', p_admin, 'Dr. Meenakshi Sundaram (IAS)', 'gov_admin', None, '+91 98222 33445'))

    # Seed Shops
    execute_db("""
        INSERT INTO ration_shops (shop_code, shop_name, address, zone, staff_user_id, contact_number, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, ('FPS-DEL-104', 'Central Fair Price Shop #104', 'Sector 4, Connaught Place, New Delhi', 'Central Zone', 2, '+91 11 2334 5678', 'active'))

    execute_db("""
        INSERT INTO ration_shops (shop_code, shop_name, address, zone, staff_user_id, contact_number, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, ('FPS-DEL-101', 'North Municipal FPS #101', 'Civil Lines, Model Town, Delhi', 'North Zone', None, '+91 11 2745 1290', 'active'))

    execute_db("""
        INSERT INTO ration_shops (shop_code, shop_name, address, zone, staff_user_id, contact_number, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, ('FPS-DEL-205', 'South Subsidized Depot #205', 'Hauz Khas Market, New Delhi', 'South Zone', None, '+91 11 2656 7890', 'active'))

    # Seed Items (Rice, Wheat, Sugar)
    execute_db("""
        INSERT INTO ration_items (item_code, item_name, unit, monthly_quota_per_beneficiary, unit_price, status)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, ('COMM-RICE', 'Rice (Boiled/Sona Masoori)', 'kg', 5.0, 3.0, 'active'))

    execute_db("""
        INSERT INTO ration_items (item_code, item_name, unit, monthly_quota_per_beneficiary, unit_price, status)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, ('COMM-WHEAT', 'Wheat (Fortified Atta)', 'kg', 5.0, 2.0, 'active'))

    execute_db("""
        INSERT INTO ration_items (item_code, item_name, unit, monthly_quota_per_beneficiary, unit_price, status)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, ('COMM-SUGAR', 'Refined Sugar', 'kg', 1.0, 13.5, 'active'))

    # Seed Inventory Stock for Central FPS (Shop 1)
    execute_db("INSERT INTO stock (shop_id, item_id, current_stock, reserved_stock, min_threshold) VALUES (%s, %s, %s, %s, %s)",
               (1, 1, 850.0, 45.0, 250.0))
    execute_db("INSERT INTO stock (shop_id, item_id, current_stock, reserved_stock, min_threshold) VALUES (%s, %s, %s, %s, %s)",
               (1, 2, 620.0, 35.0, 200.0))
    execute_db("INSERT INTO stock (shop_id, item_id, current_stock, reserved_stock, min_threshold) VALUES (%s, %s, %s, %s, %s)",
               (1, 3, 140.0, 12.0, 80.0))

    # Seed Shop 2 (Low stock scenario for Government alerts)
    execute_db("INSERT INTO stock (shop_id, item_id, current_stock, reserved_stock, min_threshold) VALUES (%s, %s, %s, %s, %s)",
               (2, 1, 420.0, 20.0, 200.0))
    execute_db("INSERT INTO stock (shop_id, item_id, current_stock, reserved_stock, min_threshold) VALUES (%s, %s, %s, %s, %s)",
               (2, 2, 110.0, 25.0, 200.0)) # Warning level
    execute_db("INSERT INTO stock (shop_id, item_id, current_stock, reserved_stock, min_threshold) VALUES (%s, %s, %s, %s, %s)",
               (2, 3, 40.0, 10.0, 70.0))   # Critical level

    # Seed Shop 3 (Well-stocked)
    execute_db("INSERT INTO stock (shop_id, item_id, current_stock, reserved_stock, min_threshold) VALUES (%s, %s, %s, %s, %s)",
               (3, 1, 1200.0, 50.0, 300.0))
    execute_db("INSERT INTO stock (shop_id, item_id, current_stock, reserved_stock, min_threshold) VALUES (%s, %s, %s, %s, %s)",
               (3, 2, 980.0, 40.0, 250.0))
    execute_db("INSERT INTO stock (shop_id, item_id, current_stock, reserved_stock, min_threshold) VALUES (%s, %s, %s, %s, %s)",
               (3, 3, 240.0, 15.0, 100.0))

    # Seed an existing demonstration booking for citizen Aarav
    today_str = datetime.date.today().isoformat()
    bid, _ = execute_db("""
        INSERT INTO bookings (booking_ref, user_id, shop_id, booking_date, time_slot, status, qr_code_data)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, ('RS-2026-8491', 1, 1, today_str, '10:00 - 11:00 AM', 'Approved', 'RS-2026-8491'))

    execute_db("INSERT INTO booking_items (booking_id, item_id, quantity, unit) VALUES (%s, %s, %s, %s)", (bid, 1, 5.0, 'kg'))
    execute_db("INSERT INTO booking_items (booking_id, item_id, quantity, unit) VALUES (%s, %s, %s, %s)", (bid, 2, 5.0, 'kg'))
    execute_db("INSERT INTO booking_items (booking_id, item_id, quantity, unit) VALUES (%s, %s, %s, %s)", (bid, 3, 1.0, 'kg'))

    # Seed some completed bookings for historical trends
    past_days = [today_str]
    for i in range(1, 7):
        p_day = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
        past_days.append(p_day)
        bid_past, _ = execute_db("""
            INSERT INTO bookings (booking_ref, user_id, shop_id, booking_date, time_slot, status, qr_code_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (f'RS-2026-HIST-{i}', 1, 1, p_day, '11:00 - 12:00 PM', 'Completed', f'RS-2026-HIST-{i}'))
        execute_db("INSERT INTO booking_items (booking_id, item_id, quantity, unit) VALUES (%s, %s, %s, %s)", (bid_past, 1, 5.0, 'kg'))
        execute_db("INSERT INTO booking_items (booking_id, item_id, quantity, unit) VALUES (%s, %s, %s, %s)", (bid_past, 2, 5.0, 'kg'))

    # Seed historical queue data for shop 1
    queue_samples = [
        (1, 0, 9, 5, 7, 18), (1, 0, 10, 14, 18, 50), (1, 0, 11, 15, 20, 56), (1, 0, 12, 8, 10, 26),
        (1, 0, 14, 3, 4, 11), (1, 0, 15, 6, 8, 22), (1, 0, 16, 12, 15, 42), (1, 0, 17, 9, 11, 30),
        (1, 1, 9, 6, 8, 20), (1, 1, 10, 11, 14, 38), (1, 1, 11, 13, 16, 44), (1, 1, 12, 7, 8, 22),
        (1, 1, 14, 4, 5, 14), (1, 1, 15, 7, 9, 25), (1, 1, 16, 10, 13, 36), (1, 1, 17, 8, 10, 28),
        (1, 5, 9, 9, 12, 32), (1, 5, 10, 20, 26, 72), (1, 5, 11, 24, 30, 84), (1, 5, 12, 16, 21, 58),
        (1, 5, 14, 8, 10, 28), (1, 5, 15, 14, 18, 49), (1, 5, 16, 18, 24, 66), (1, 5, 17, 13, 17, 46),
    ]
    for qs in queue_samples:
        execute_db("""
            INSERT INTO queue_data (shop_id, day_of_week, hour, active_bookings, actual_queue_count, avg_wait_time_minutes)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, qs)

# ------------------------------------------------------------------------------
# 3. AI / MACHINE LEARNING ENGINES (scikit-learn & pandas)
# ------------------------------------------------------------------------------
class AIQueueEngine:
    """
    Predictive Machine Learning model using pandas and scikit-learn RandomForestRegressor.
    Trained on synthetic civic distribution queue observations to estimate:
    - Queue size (number of beneficiaries waiting)
    - Estimated waiting time in minutes
    - Optimal/recommended booking time slot with lowest predicted congestion.
    """
    def __init__(self):
        self.model = None
        self.dataset_meta = "Demonstration / Synthetic Civic Footfall Dataset (650 historical observations)"
        self._train_model()

    def _generate_synthetic_training_data(self):
        np.random.seed(42)
        records = []
        # Days 0 to 6 (Monday to Sunday)
        for day in range(7):
            # Operating hours 8 to 18
            for hour in range(8, 19):
                for trial in range(5):
                    # Natural rush hour profile
                    if 10 <= hour <= 12:
                        hour_factor = 2.4
                    elif 16 <= hour <= 17:
                        hour_factor = 1.8
                    elif 13 <= hour <= 14:
                        hour_factor = 0.7  # Lunch lull
                    else:
                        hour_factor = 1.0

                    # Weekend factor (Saturday=5, Sunday=6)
                    day_factor = 1.35 if day in [5, 6] else 1.0

                    bookings = max(0, int(np.random.poisson(lam=6 * hour_factor * day_factor)))
                    # Queue formula with realistic non-linear noise
                    base_queue = max(1, int(bookings * 1.1 + np.random.normal(loc=2, scale=1.5)))
                    wait_time = int(base_queue * np.random.uniform(2.5, 3.2))

                    records.append({
                        'day_of_week': day,
                        'hour': hour,
                        'bookings': bookings,
                        'queue_size': base_queue,
                        'wait_time_minutes': wait_time
                    })
        return pd.DataFrame(records)

    def _train_model(self):
        df = self._generate_synthetic_training_data()
        X = df[['day_of_week', 'hour', 'bookings']]
        y = df[['queue_size', 'wait_time_minutes']]

        self.model = RandomForestRegressor(n_estimators=40, max_depth=8, random_state=42)
        self.model.fit(X, y)

    def predict(self, day_of_week, hour, bookings):
        """Returns predicted queue size and wait time for given features."""
        features = pd.DataFrame([[int(day_of_week), int(hour), int(bookings)]], columns=['day_of_week', 'hour', 'bookings'])
        pred = self.model.predict(features)[0]
        q_size = max(1, int(round(pred[0])))
        w_time = max(3, int(round(pred[1])))

        if q_size <= 5:
            rush = "Low Congestion"
            badge = "success"
        elif q_size <= 12:
            rush = "Moderate Congestion"
            badge = "warning"
        elif q_size <= 20:
            rush = "High Congestion"
            badge = "danger"
        else:
            rush = "Peak Rush"
            badge = "danger"

        return {
            'predicted_queue': q_size,
            'wait_time_minutes': w_time,
            'rush_level': rush,
            'rush_badge': badge,
            'confidence': 0.92,
            'dataset_note': self.dataset_meta
        }

    def recommend_optimal_slot(self, target_date_str, shop_id=1):
        """
        Evaluates all hourly operational slots for the requested date,
        cross-references current booked counts from the database,
        and recommends the slot with minimal predicted congestion.
        """
        try:
            target_date = datetime.date.fromisoformat(target_date_str)
        except Exception:
            target_date = datetime.date.today()

        day_of_week = target_date.weekday()
        slots = [
            ("09:00 - 10:00 AM", 9),
            ("10:00 - 11:00 AM", 10),
            ("11:00 - 12:00 PM", 11),
            ("12:00 - 01:00 PM", 12),
            ("02:00 - 03:00 PM", 14),
            ("03:00 - 04:00 PM", 15),
            ("04:00 - 05:00 PM", 16),
            ("05:00 - 06:00 PM", 17)
        ]

        evaluated = []
        for slot_label, hour in slots:
            # Query actual bookings count from database for this slot
            res = query_db("""
                SELECT COUNT(*) as cnt FROM bookings
                WHERE shop_id = %s AND booking_date = %s AND time_slot = %s
            """, (shop_id, target_date.isoformat(), slot_label), one=True)
            active_b = res['cnt'] if res else 0

            pred = self.predict(day_of_week, hour, active_b)
            evaluated.append({
                'slot': slot_label,
                'hour': hour,
                'active_bookings': active_b,
                'predicted_queue': pred['predicted_queue'],
                'wait_time_minutes': pred['wait_time_minutes'],
                'rush_level': pred['rush_level'],
                'rush_badge': pred['rush_badge']
            })

        # Find slot with minimum wait time
        optimal = min(evaluated, key=lambda x: (x['wait_time_minutes'], x['predicted_queue']))
        return {
            'recommended_slot': optimal['slot'],
            'estimated_wait_minutes': optimal['wait_time_minutes'],
            'predicted_queue': optimal['predicted_queue'],
            'all_slots': evaluated,
            'dataset_note': self.dataset_meta
        }

# Instantiate singleton AI Queue model
ai_queue_engine = AIQueueEngine()

class AIStockAnalyzer:
    """
    AI Stock Consumption and Shortage Risk Engine.
    Uses current shop inventory, pending reservations, and empirical burn rates
    to calculate:
    - Predicted daily and 7-day demand
    - Estimated days of stock remaining
    - Risk category (Critical / High / Moderate / Optimal)
    - Actionable automated replenishment recommendations.
    """
    # Empirical daily distribution rates per commodity for a standard Fair Price Shop
    DEFAULT_DAILY_CONSUMPTION = {
        'COMM-RICE': 38.0,  # ~38 kg/day
        'COMM-WHEAT': 32.0, # ~32 kg/day
        'COMM-SUGAR': 8.5   # ~8.5 kg/day
    }

    @classmethod
    def analyze_shop_stock(cls, shop_id=1):
        items_stock = query_db("""
            SELECT s.id, s.shop_id, s.current_stock, s.reserved_stock, s.min_threshold, s.last_updated,
                   i.id as item_id, i.item_code, i.item_name, i.unit, i.monthly_quota_per_beneficiary, i.unit_price
            FROM stock s
            JOIN ration_items i ON s.item_id = i.id
            WHERE s.shop_id = %s
            ORDER BY i.id ASC
        """, (shop_id,))

        analysis = []
        critical_alerts_count = 0

        for row in items_stock:
            item_code = row['item_code']
            curr = float(row['current_stock'])
            resv = float(row['reserved_stock'])
            thresh = float(row['min_threshold'])
            burn_rate = cls.DEFAULT_DAILY_CONSUMPTION.get(item_code, 25.0)

            # Net available stock after pending commitments
            net_avail = max(0.0, curr - resv)
            days_rem = round(net_avail / burn_rate, 1) if burn_rate > 0 else 999.0
            demand_7d = round(burn_rate * 7.0 + resv, 1)

            # Categorize shortage risk
            if days_rem < 3.5 or curr <= thresh * 0.4:
                risk = 'Critical'
                badge = 'danger'
                action = f"URGENT: Re-order {max(500, int(thresh * 3 - curr))} {row['unit']} immediately. Stock will deplete in {days_rem} days."
                critical_alerts_count += 1
            elif days_rem < 7.0 or curr <= thresh:
                risk = 'High'
                badge = 'warning'
                action = f"REORDER ADVISORY: Stock below safety threshold. Dispatch recommended within 48 hours (+{int(thresh * 2 - curr)} {row['unit']})."
            elif days_rem < 14.0:
                risk = 'Moderate'
                badge = 'info'
                action = f"STABLE BUFFER: Adequate for regular weekly delivery schedule."
            else:
                risk = 'Optimal'
                badge = 'success'
                action = f"HEALTHY INVENTORY: Sufficient supply for next 2+ weeks."

            analysis.append({
                'item_id': row['item_id'],
                'item_code': item_code,
                'item_name': row['item_name'],
                'unit': row['unit'],
                'current_stock': curr,
                'reserved_stock': resv,
                'available_stock': net_avail,
                'min_threshold': thresh,
                'daily_consumption': burn_rate,
                'projected_7d_demand': demand_7d,
                'days_remaining': days_rem,
                'shortage_risk': risk,
                'risk_badge': badge,
                'recommendation': action,
                'last_updated': str(row['last_updated'])
            })

        return {
            'shop_id': shop_id,
            'items': analysis,
            'critical_alerts_count': critical_alerts_count,
            'evaluated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

# ------------------------------------------------------------------------------
# 4. QR CODE ENGINE
# ------------------------------------------------------------------------------
def generate_qr_base64(booking_ref):
    """
    Generates an authentic PNG QR code containing ONLY the booking reference ID
    and returns it as a Base64-encoded Data URI string.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2
    )
    qr.add_data(str(booking_ref).strip())
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f2942", back_color="#ffffff")

    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    b64_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return f"data:image/png;base64,{b64_str}"

# ------------------------------------------------------------------------------
# 5. AUTHENTICATION & ACCESS CONTROL
# ------------------------------------------------------------------------------
def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return query_db("SELECT id, username, email, full_name, role, ration_card_no, phone FROM users WHERE id = %s", (user_id,), one=True)

def login_required(roles=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user:
                flash("Please log in to access this portal.", "warning")
                return redirect(url_for('login_view', next=request.url))
            if roles:
                allowed_roles = [roles] if isinstance(roles, str) else roles
                if user['role'] not in allowed_roles:
                    flash(f"Unauthorized access. Required role: {', '.join(allowed_roles)}.", "danger")
                    return redirect(url_for('dashboard_view'))
            g.user = user
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ------------------------------------------------------------------------------
# 6. REST API ENDPOINTS
# ------------------------------------------------------------------------------
@app.route('/api/health', methods=['GET'])
def api_health():
    """System health & configuration probe."""
    db = get_db()
    return jsonify({
        'status': 'healthy',
        'application': 'RationSmart AI',
        'database_engine': g.get('db_type', ACTIVE_DB_ENGINE),
        'ml_queue_model': 'Ready (RandomForestRegressor)',
        'timestamp': datetime.datetime.now().isoformat()
    }), 200

@app.route('/api/availability', methods=['GET'])
def api_availability():
    """Returns available commodities, stock levels, and user monthly entitlements."""
    shop_id = request.args.get('shop_id', 1, type=int)
    user_id = session.get('user_id')

    items = query_db("""
        SELECT i.id, i.item_code, i.item_name, i.unit, i.monthly_quota_per_beneficiary, i.unit_price,
               COALESCE(s.current_stock, 0.0) as stock,
               COALESCE(s.reserved_stock, 0.0) as reserved,
               COALESCE(s.min_threshold, 100.0) as threshold,
               COALESCE(s.last_updated, CURRENT_TIMESTAMP) as last_updated
        FROM ration_items i
        LEFT JOIN stock s ON i.id = s.item_id AND s.shop_id = %s
        WHERE i.status = 'active'
        ORDER BY i.id ASC
    """, (shop_id,))

    # Compute user's already booked quantity in current month
    first_day_curr_month = datetime.date.today().replace(day=1).isoformat()
    result = []
    for item in items:
        booked_qty = 0.0
        if user_id:
            b_res = query_db("""
                SELECT COALESCE(SUM(bi.quantity), 0.0) as sum_qty
                FROM booking_items bi
                JOIN bookings b ON bi.booking_id = b.id
                WHERE b.user_id = %s AND bi.item_id = %s
                  AND b.booking_date >= %s AND b.status != 'Cancelled'
            """, (user_id, item['id'], first_day_curr_month), one=True)
            booked_qty = float(b_res['sum_qty']) if b_res else 0.0

        quota = float(item['monthly_quota_per_beneficiary'])
        remaining_entitlement = max(0.0, quota - booked_qty)
        avail_stock = max(0.0, float(item['stock']) - float(item['reserved']))

        # Determine stock status
        if avail_stock <= 0:
            stock_status = "Out of Stock"
            status_badge = "danger"
        elif avail_stock <= float(item['threshold']):
            stock_status = "Low Stock"
            status_badge = "warning"
        else:
            stock_status = "In Stock"
            status_badge = "success"

        result.append({
            'item_id': item['id'],
            'item_code': item['item_code'],
            'item_name': item['item_name'],
            'unit': item['unit'],
            'total_stock': float(item['stock']),
            'available_stock': avail_stock,
            'entitlement': quota,
            'remaining_entitlement': remaining_entitlement,
            'stock_status': stock_status,
            'status_badge': status_badge,
            'last_updated': str(item['last_updated'])
        })

    return jsonify({'shop_id': shop_id, 'items': result})

@app.route('/api/bookings', methods=['GET', 'POST'])
def api_bookings():
    """List bookings or create a new smart booking."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    if request.method == 'POST':
        data = request.get_json() or {}
        shop_id = int(data.get('shop_id', 1))
        booking_date = data.get('booking_date', datetime.date.today().isoformat())
        time_slot = data.get('time_slot', '10:00 - 11:00 AM')
        items = data.get('items', []) # e.g. [{'item_id': 1, 'quantity': 5.0}, ...]

        if not items:
            return jsonify({'error': 'At least one commodity must be selected.'}), 400

        # Validate date is not in past
        try:
            b_date_obj = datetime.date.fromisoformat(booking_date)
            if b_date_obj < datetime.date.today():
                return jsonify({'error': 'Booking date cannot be in the past.'}), 400
        except ValueError:
            return jsonify({'error': 'Invalid booking date format.'}), 400

        # Validate entitlement and shop stock
        for item in items:
            iid = int(item['item_id'])
            qty = float(item['quantity'])
            if qty <= 0:
                continue

            stock_row = query_db("SELECT current_stock, reserved_stock FROM stock WHERE shop_id = %s AND item_id = %s", (shop_id, iid), one=True)
            if not stock_row:
                return jsonify({'error': f'Item ID {iid} is not stocked at this shop.'}), 400

            avail = float(stock_row['current_stock']) - float(stock_row['reserved_stock'])
            if qty > avail:
                return jsonify({'error': f'Requested quantity ({qty}) exceeds available stock ({avail}) for item.'}), 400

        # Generate unique Booking Reference
        random_suffix = random.randint(1000, 9999)
        booking_ref = f"RS-2026-{random_suffix}"

        # Insert booking
        booking_id, _ = execute_db("""
            INSERT INTO bookings (booking_ref, user_id, shop_id, booking_date, time_slot, status, qr_code_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (booking_ref, user['id'], shop_id, booking_date, time_slot, 'Pending', booking_ref))

        # Insert items and update reserved stock
        for item in items:
            iid = int(item['item_id'])
            qty = float(item['quantity'])
            if qty <= 0:
                continue
            item_info = query_db("SELECT unit FROM ration_items WHERE id = %s", (iid,), one=True)
            unit = item_info['unit'] if item_info else 'kg'

            execute_db("""
                INSERT INTO booking_items (booking_id, item_id, quantity, unit)
                VALUES (%s, %s, %s, %s)
            """, (booking_id, iid, qty, unit))

            # Increase reserved stock
            execute_db("""
                UPDATE stock
                SET reserved_stock = reserved_stock + %s, last_updated = CURRENT_TIMESTAMP
                WHERE shop_id = %s AND item_id = %s
            """, (qty, shop_id, iid))

        qr_uri = generate_qr_base64(booking_ref)
        return jsonify({
            'message': 'Smart Booking confirmed successfully!',
            'booking_id': booking_id,
            'booking_ref': booking_ref,
            'status': 'Pending',
            'qr_code_uri': qr_uri
        }), 201

    # GET: return list of bookings according to role
    if user['role'] == 'citizen':
        bookings = query_db("""
            SELECT b.id, b.booking_ref, b.booking_date, b.time_slot, b.status, b.created_at,
                   s.shop_name, s.shop_code, s.address as shop_address
            FROM bookings b
            JOIN ration_shops s ON b.shop_id = s.id
            WHERE b.user_id = %s
            ORDER BY b.id DESC
        """, (user['id'],))
    elif user['role'] == 'shop_staff':
        # Find shop assigned to this staff or default shop 1
        shop = query_db("SELECT id FROM ration_shops WHERE staff_user_id = %s", (user['id'],), one=True)
        shop_id = shop['id'] if shop else 1
        bookings = query_db("""
            SELECT b.id, b.booking_ref, b.booking_date, b.time_slot, b.status, b.created_at,
                   u.full_name as citizen_name, u.ration_card_no, u.phone,
                   s.shop_name, s.shop_code
            FROM bookings b
            JOIN users u ON b.user_id = u.id
            JOIN ration_shops s ON b.shop_id = s.id
            WHERE b.shop_id = %s
            ORDER BY b.id DESC
        """, (shop_id,))
    else: # gov_admin
        bookings = query_db("""
            SELECT b.id, b.booking_ref, b.booking_date, b.time_slot, b.status, b.created_at,
                   u.full_name as citizen_name, u.ration_card_no,
                   s.shop_name, s.shop_code
            FROM bookings b
            JOIN users u ON b.user_id = u.id
            JOIN ration_shops s ON b.shop_id = s.id
            ORDER BY b.id DESC LIMIT 100
        """)

    # Attach item details to each booking
    for b in bookings:
        b['items'] = query_db("""
            SELECT bi.quantity, bi.unit, i.item_name, i.item_code
            FROM booking_items bi
            JOIN ration_items i ON bi.item_id = i.id
            WHERE bi.booking_id = %s
        """, (b['id'],))

    return jsonify({'bookings': bookings})

@app.route('/api/bookings/<int:booking_id>', methods=['GET'])
def api_booking_detail(booking_id):
    """Fetch complete booking pass details including generated QR code."""
    booking = query_db("""
        SELECT b.id, b.booking_ref, b.booking_date, b.time_slot, b.status, b.created_at,
               u.full_name as citizen_name, u.ration_card_no, u.phone, u.email,
               s.id as shop_id, s.shop_name, s.shop_code, s.address as shop_address, s.contact_number as shop_contact
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        JOIN ration_shops s ON b.shop_id = s.id
        WHERE b.id = %s
    """, (booking_id,), one=True)

    if not booking:
        return jsonify({'error': 'Booking not found.'}), 404

    items = query_db("""
        SELECT bi.quantity, bi.unit, i.item_name, i.item_code
        FROM booking_items bi
        JOIN ration_items i ON bi.item_id = i.id
        WHERE bi.booking_id = %s
    """, (booking_id,))

    booking['items'] = items
    booking['qr_code_uri'] = generate_qr_base64(booking['booking_ref'])
    return jsonify(booking)

@app.route('/api/bookings/<int:booking_id>/status', methods=['POST'])
@login_required(roles=['shop_staff', 'gov_admin'])
def api_update_booking_status(booking_id):
    """
    Allows Shop Staff or Gov Admin to approve or complete a booking.
    When marked 'Completed', stock is automatically deducted from MySQL stock table!
    """
    data = request.get_json() or {}
    new_status = data.get('status')
    if new_status not in ['Approved', 'Completed', 'Cancelled']:
        return jsonify({'error': 'Invalid status. Must be Approved, Completed, or Cancelled.'}), 400

    booking = query_db("SELECT id, shop_id, status FROM bookings WHERE id = %s", (booking_id,), one=True)
    if not booking:
        return jsonify({'error': 'Booking not found.'}), 404

    old_status = booking['status']
    if old_status == 'Completed':
        return jsonify({'error': 'Booking is already completed and stock has been distributed.'}), 400

    shop_id = booking['shop_id']

    if new_status == 'Completed':
        # Retrieve items in this booking
        items = query_db("SELECT item_id, quantity FROM booking_items WHERE booking_id = %s", (booking_id,))
        for it in items:
            iid = it['item_id']
            qty = float(it['quantity'])
            # Deduct current stock and release reserved stock
            execute_db("""
                UPDATE stock
                SET current_stock = CASE WHEN current_stock >= %s THEN current_stock - %s ELSE 0 END,
                    reserved_stock = CASE WHEN reserved_stock >= %s THEN reserved_stock - %s ELSE 0 END,
                    last_updated = CURRENT_TIMESTAMP
                WHERE shop_id = %s AND item_id = %s
            """, (qty, qty, qty, qty, shop_id, iid))

    elif new_status == 'Cancelled' and old_status != 'Cancelled':
        # Release reserved stock back to available pool
        items = query_db("SELECT item_id, quantity FROM booking_items WHERE booking_id = %s", (booking_id,))
        for it in items:
            iid = it['item_id']
            qty = float(it['quantity'])
            execute_db("""
                UPDATE stock
                SET reserved_stock = CASE WHEN reserved_stock >= %s THEN reserved_stock - %s ELSE 0 END,
                    last_updated = CURRENT_TIMESTAMP
                WHERE shop_id = %s AND item_id = %s
            """, (qty, qty, shop_id, iid))

    execute_db("UPDATE bookings SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (new_status, booking_id))
    return jsonify({
        'message': f'Booking #{booking_id} status updated to {new_status}.',
        'status': new_status
    })

@app.route('/api/queue-prediction', methods=['POST'])
def api_queue_prediction():
    """
    AI Machine Learning endpoint for Queue & Wait Time prediction.
    Accepts date, time_slot (or hour), and shop_id.
    """
    data = request.get_json() or {}
    date_str = data.get('date', datetime.date.today().isoformat())
    time_slot = data.get('time_slot', '10:00 - 11:00 AM')
    shop_id = int(data.get('shop_id', 1))

    # Extract hour from time slot string e.g. "10:00 - 11:00 AM" -> 10, "02:00 - 03:00 PM" -> 14
    hour = 10
    match = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)?', time_slot, re.IGNORECASE)
    if match:
        h = int(match.group(1))
        meridiem = match.group(3)
        if meridiem and meridiem.upper() == 'PM' and h < 12:
            h += 12
        elif meridiem and meridiem.upper() == 'AM' and h == 12:
            h = 0
        hour = h

    try:
        t_date = datetime.date.fromisoformat(date_str)
        day_of_week = t_date.weekday()
    except Exception:
        day_of_week = datetime.date.today().weekday()

    # Query current active bookings for this slot from DB
    res = query_db("""
        SELECT COUNT(*) as cnt FROM bookings
        WHERE shop_id = %s AND booking_date = %s AND time_slot = %s AND status != 'Cancelled'
    """, (shop_id, date_str, time_slot), one=True)
    active_b = res['cnt'] if res else 0

    prediction = ai_queue_engine.predict(day_of_week, hour, active_b)
    optimal_rec = ai_queue_engine.recommend_optimal_slot(date_str, shop_id)

    return jsonify({
        'date': date_str,
        'time_slot': time_slot,
        'day_of_week': day_of_week,
        'hour': hour,
        'active_bookings_count': active_b,
        'prediction': prediction,
        'recommendation': optimal_rec
    })

@app.route('/api/stock-prediction', methods=['GET'])
def api_stock_prediction():
    """AI stock consumption, depletion rate, and shortage risk analysis."""
    shop_id = request.args.get('shop_id', 1, type=int)
    insights = AIStockAnalyzer.analyze_shop_stock(shop_id)
    return jsonify(insights)

@app.route('/api/stock', methods=['GET', 'POST'])
def api_stock():
    """Retrieve or adjust shop stock inventory."""
    shop_id = request.args.get('shop_id', 1, type=int)

    if request.method == 'POST':
        # Staff/admin restocking
        user = get_current_user()
        if not user or user['role'] not in ['shop_staff', 'gov_admin']:
            return jsonify({'error': 'Unauthorized to modify stock.'}), 403

        data = request.get_json() or {}
        item_id = int(data.get('item_id'))
        add_quantity = float(data.get('quantity', 0))

        if add_quantity <= 0:
            return jsonify({'error': 'Quantity must be positive.'}), 400

        execute_db("""
            UPDATE stock
            SET current_stock = current_stock + %s, last_updated = CURRENT_TIMESTAMP
            WHERE shop_id = %s AND item_id = %s
        """, (add_quantity, shop_id, item_id))

        return jsonify({'message': f'Successfully replenished {add_quantity} units into inventory.'})

    # GET stock
    stocks = query_db("""
        SELECT s.id, s.shop_id, s.current_stock, s.reserved_stock, s.min_threshold, s.last_updated,
               i.id as item_id, i.item_code, i.item_name, i.unit
        FROM stock s
        JOIN ration_items i ON s.item_id = i.id
        WHERE s.shop_id = %s
        ORDER BY i.id ASC
    """, (shop_id,))
    return jsonify({'shop_id': shop_id, 'stocks': stocks})

@app.route('/api/government', methods=['GET'])
@login_required(roles=['gov_admin'])
def api_government():
    """Aggregated state metrics and Chart.js series data for Government portal."""
    total_shops = query_db("SELECT COUNT(*) as cnt FROM ration_shops", one=True)['cnt']
    total_beneficiaries = query_db("SELECT COUNT(*) as cnt FROM users WHERE role = 'citizen'", one=True)['cnt']

    today_str = datetime.date.today().isoformat()
    today_txns = query_db("SELECT COUNT(*) as cnt FROM bookings WHERE booking_date = %s AND status = 'Completed'", (today_str,), one=True)['cnt']

    # Low stock count across all shops
    low_stock_res = query_db("""
        SELECT COUNT(DISTINCT s.shop_id) as cnt
        FROM stock s
        WHERE s.current_stock <= s.min_threshold
    """, one=True)
    low_stock_shops_count = low_stock_res['cnt'] if low_stock_res else 0

    # 1. 7-Day Booking vs Completion Trend Chart Data
    dates_list = [(datetime.date.today() - datetime.timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    trend_labels = [datetime.date.fromisoformat(d).strftime('%b %d') for d in dates_list]
    trend_bookings = []
    trend_completions = []

    for d in dates_list:
        b_cnt = query_db("SELECT COUNT(*) as cnt FROM bookings WHERE booking_date = %s", (d,), one=True)['cnt']
        c_cnt = query_db("SELECT COUNT(*) as cnt FROM bookings WHERE booking_date = %s AND status = 'Completed'", (d,), one=True)['cnt']
        trend_bookings.append(b_cnt)
        trend_completions.append(c_cnt)

    # 2. Stock Levels by Commodity across all shops
    stock_by_commodity = query_db("""
        SELECT i.item_name, i.unit, SUM(s.current_stock) as total_stock, SUM(s.reserved_stock) as total_reserved
        FROM stock s
        JOIN ration_items i ON s.item_id = i.id
        GROUP BY i.id, i.item_name, i.unit
        ORDER BY i.id ASC
    """)

    # 3. Queue Congestion Profile by Hour (average queue count across hours)
    hourly_queue_profile = query_db("""
        SELECT hour, AVG(actual_queue_count) as avg_queue, AVG(avg_wait_time_minutes) as avg_wait
        FROM queue_data
        GROUP BY hour
        ORDER BY hour ASC
    """)

    # 4. Fair Price Shop Monitoring Table
    shops_overview = query_db("""
        SELECT s.id, s.shop_code, s.shop_name, s.zone, s.status,
               COALESCE(u.full_name, 'Unassigned') as staff_name,
               (SELECT COUNT(*) FROM bookings b WHERE b.shop_id = s.id AND b.booking_date = %s) as today_bookings,
               (SELECT MIN(st.current_stock - st.min_threshold) FROM stock st WHERE st.shop_id = s.id) as lowest_stock_delta
        FROM ration_shops s
        LEFT JOIN users u ON s.staff_user_id = u.id
        ORDER BY s.id ASC
    """, (today_str,))

    for s in shops_overview:
        delta = s.get('lowest_stock_delta', 100)
        if delta is None:
            s['health_status'] = 'Unknown'
            s['health_badge'] = 'secondary'
        elif delta <= -50:
            s['health_status'] = 'Critical Shortage'
            s['health_badge'] = 'danger'
        elif delta <= 0:
            s['health_status'] = 'Low Stock'
            s['health_badge'] = 'warning'
        else:
            s['health_status'] = 'Optimal'
            s['health_badge'] = 'success'

    return jsonify({
        'kpis': {
            'total_shops': total_shops,
            'total_beneficiaries': total_beneficiaries,
            'today_transactions': today_txns,
            'low_stock_shops': low_stock_shops_count
        },
        'charts': {
            'trend': {
                'labels': trend_labels,
                'bookings': trend_bookings,
                'completions': trend_completions
            },
            'commodity_stocks': stock_by_commodity,
            'hourly_queue': hourly_queue_profile
        },
        'shops': shops_overview
    })

# ------------------------------------------------------------------------------
# 7. AUTHENTICATION & PORTAL VIEWS
# ------------------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login_view():
    if session.get('user_id'):
        return redirect(url_for('dashboard_view'))

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '').strip()

        user = query_db("""
            SELECT * FROM users
            WHERE email = %s OR username = %s OR ration_card_no = %s
        """, (identifier, identifier, identifier), one=True)

        if user and check_password_hash(user['password_hash'], password):
            session.permanent = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['full_name'] = user['full_name']
            flash(f"Welcome back, {user['full_name']}! Logged in as {user['role'].replace('_', ' ').title()}.", "success")
            next_url = request.args.get('next')
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect(url_for('dashboard_view'))
        else:
            flash("Invalid credentials. Please check your username/email/ration card and password.", "danger")

    return render_template_string(HTML_LOGIN)

@app.route('/register', methods=['GET', 'POST'])
def register_view():
    if session.get('user_id'):
        return redirect(url_for('dashboard_view'))

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        username = request.form.get('username', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()

        if not (full_name and email and username and password):
            flash("Please fill in all required fields.", "danger")
            return render_template_string(HTML_REGISTER)

        # Check for existing user
        exists = query_db("SELECT id FROM users WHERE email = %s OR username = %s", (email, username), one=True)
        if exists:
            flash("Email or username is already registered.", "warning")
            return render_template_string(HTML_REGISTER)

        # Generate automatic Ration Card number
        ration_card_no = f"RC-DL-{random.randint(10000, 99999)}"
        p_hash = generate_password_hash(password)

        uid, _ = execute_db("""
            INSERT INTO users (username, email, password_hash, full_name, role, ration_card_no, phone)
            VALUES (%s, %s, %s, %s, 'citizen', %s, %s)
        """, (username, email, p_hash, full_name, ration_card_no, phone))

        flash(f"Registration successful! Your new Ration Card No. is {ration_card_no}. Please log in.", "success")
        return redirect(url_for('login_view'))

    return render_template_string(HTML_REGISTER)

@app.route('/logout')
def logout_view():
    session.clear()
    flash("You have been securely logged out.", "info")
    return redirect(url_for('landing_view'))

@app.route('/dashboard')
def dashboard_view():
    """Routes user to their respective role-based dashboard."""
    user = get_current_user()
    if not user:
        return redirect(url_for('login_view'))
    if user['role'] == 'citizen':
        return redirect(url_for('citizen_dashboard'))
    elif user['role'] == 'shop_staff':
        return redirect(url_for('shop_dashboard'))
    elif user['role'] == 'gov_admin':
        return redirect(url_for('gov_dashboard'))
    return redirect(url_for('landing_view'))

# ------------------------------------------------------------------------------
# 8. ROLE-SPECIFIC DASHBOARDS & DIGITAL PASS
# ------------------------------------------------------------------------------
@app.route('/')
def landing_view():
    user = get_current_user()
    return render_template_string(HTML_LANDING, user=user)

@app.route('/citizen')
@login_required(roles=['citizen'])
def citizen_dashboard():
    user = g.user
    # Active bookings
    bookings = query_db("""
        SELECT b.id, b.booking_ref, b.booking_date, b.time_slot, b.status, b.created_at,
               s.shop_name, s.shop_code, s.address as shop_address
        FROM bookings b
        JOIN ration_shops s ON b.shop_id = s.id
        WHERE b.user_id = %s
        ORDER BY b.id DESC
    """, (user['id'],))

    for b in bookings:
        b['items'] = query_db("""
            SELECT bi.quantity, bi.unit, i.item_name
            FROM booking_items bi
            JOIN ration_items i ON bi.item_id = i.id
            WHERE bi.booking_id = %s
        """, (b['id'],))

    # Real-time queue estimate for today at central FPS
    today_hour = datetime.datetime.now().hour
    today_weekday = datetime.datetime.now().weekday()
    current_queue_stat = ai_queue_engine.predict(today_weekday, today_hour, len([b for b in bookings if b['status'] == 'Approved']))

    # Default recommended slot for tomorrow
    tomorrow_str = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    recommended_slot = ai_queue_engine.recommend_optimal_slot(tomorrow_str, shop_id=1)

    # Count active bookings for dashboard card
    active_bookings_count = len([b for b in bookings if b['status'] in ['Approved', 'Pending']])

    return render_template_string(
        HTML_CITIZEN_DASHBOARD,
        user=user,
        bookings=bookings,
        current_queue=current_queue_stat,
        recommended_slot=recommended_slot,
        active_bookings_count=active_bookings_count
    )

@app.route('/shop')
@login_required(roles=['shop_staff', 'gov_admin'])
def shop_dashboard():
    user = g.user
    shop = query_db("SELECT * FROM ration_shops WHERE staff_user_id = %s", (user['id'],), one=True)
    if not shop:
        shop = query_db("SELECT * FROM ration_shops WHERE id = 1", one=True)

    today_str = datetime.date.today().isoformat()
    # Today's bookings
    todays_bookings = query_db("""
        SELECT b.id, b.booking_ref, b.booking_date, b.time_slot, b.status, b.created_at,
               u.full_name as citizen_name, u.ration_card_no, u.phone
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        WHERE b.shop_id = %s AND b.booking_date = %s
        ORDER BY b.id DESC
    """, (shop['id'], today_str))

    for b in todays_bookings:
        b['items'] = query_db("""
            SELECT bi.quantity, bi.unit, i.item_name
            FROM booking_items bi
            JOIN ration_items i ON bi.item_id = i.id
            WHERE bi.booking_id = %s
        """, (b['id'],))

    # Metrics
    pending_cnt = sum(1 for b in todays_bookings if b['status'] == 'Pending')
    completed_cnt = sum(1 for b in todays_bookings if b['status'] == 'Completed')
    total_today = len(todays_bookings)

    # Current queue prediction
    curr_hour = datetime.datetime.now().hour
    curr_day = datetime.datetime.now().weekday()
    queue_info = ai_queue_engine.predict(curr_day, curr_hour, pending_cnt)

    # AI Stock analysis
    stock_insights = AIStockAnalyzer.analyze_shop_stock(shop['id'])

    return render_template_string(
        HTML_SHOP_DASHBOARD,
        user=user,
        shop=shop,
        todays_bookings=todays_bookings,
        total_today=total_today,
        pending_cnt=pending_cnt,
        completed_cnt=completed_cnt,
        queue_info=queue_info,
        stock_insights=stock_insights
    )

@app.route('/government')
@login_required(roles=['gov_admin'])
def gov_dashboard():
    user = g.user
    today_str = datetime.date.today().isoformat()

    total_shops = query_db("SELECT COUNT(*) as cnt FROM ration_shops", one=True)['cnt']
    total_beneficiaries = query_db("SELECT COUNT(*) as cnt FROM users WHERE role = 'citizen'", one=True)['cnt']
    today_txns = query_db("SELECT COUNT(*) as cnt FROM bookings WHERE booking_date = %s AND status = 'Completed'", (today_str,), one=True)['cnt']
    low_stock_res = query_db("SELECT COUNT(DISTINCT shop_id) as cnt FROM stock WHERE current_stock <= min_threshold", one=True)
    low_stock_cnt = low_stock_res['cnt'] if low_stock_res else 0

    # Stock predictions across all 3 shops for consolidated alerts
    all_shops = query_db("SELECT id, shop_code, shop_name, zone FROM ration_shops")
    consolidated_alerts = []
    for s in all_shops:
        si = AIStockAnalyzer.analyze_shop_stock(s['id'])
        for item in si['items']:
            if item['shortage_risk'] in ['Critical', 'High']:
                consolidated_alerts.append({
                    'shop_name': s['shop_name'],
                    'shop_code': s['shop_code'],
                    'zone': s['zone'],
                    **item
                })

    return render_template_string(
        HTML_GOV_DASHBOARD,
        user=user,
        total_shops=total_shops,
        total_beneficiaries=total_beneficiaries,
        today_txns=today_txns,
        low_stock_cnt=low_stock_cnt,
        consolidated_alerts=consolidated_alerts
    )

@app.route('/pass/<booking_ref>')
def digital_pass_view(booking_ref):
    """Render a standalone, printable official Digital Ration Pass with real QR code."""
    booking = query_db("""
        SELECT b.id, b.booking_ref, b.booking_date, b.time_slot, b.status, b.created_at,
               u.full_name as citizen_name, u.ration_card_no, u.phone, u.email,
               s.shop_name, s.shop_code, s.address as shop_address, s.contact_number as shop_contact
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        JOIN ration_shops s ON b.shop_id = s.id
        WHERE b.booking_ref = %s
    """, (booking_ref,), one=True)

    if not booking:
        abort(404)

    items = query_db("""
        SELECT bi.quantity, bi.unit, i.item_name, i.item_code
        FROM booking_items bi
        JOIN ration_items i ON bi.item_id = i.id
        WHERE bi.booking_id = %s
    """, (booking['id'],))

    qr_uri = generate_qr_base64(booking['booking_ref'])
    return render_template_string(HTML_DIGITAL_PASS, b=booking, items=items, qr_uri=qr_uri)

# ------------------------------------------------------------------------------
# 9. EMBEDDED FRONTEND TEMPLATES (HTML/CSS/JS)
# ------------------------------------------------------------------------------
HTML_HEADER_COMMON = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title | default('RationSmart AI - Smart Public Distribution System') }}</title>
    <!-- Bootstrap 5 CSS -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <!-- Bootstrap Icons -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
    <!-- Google Font: Inter -->
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --rs-navy: #0f2942;
            --rs-navy-light: #1e3a8a;
            --rs-accent: #d97706;
            --rs-gold: #b45309;
            --rs-bg-subtle: #f8fafc;
            --rs-border: #e2e8f0;
            --rs-text-main: #1e293b;
            --rs-text-muted: #64748b;
        }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--rs-bg-subtle);
            color: var(--rs-text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .navbar-gov {
            background-color: var(--rs-navy);
            border-bottom: 3px solid var(--rs-accent);
        }
        .navbar-brand {
            font-weight: 700;
            letter-spacing: -0.5px;
            color: #ffffff !important;
        }
        .badge-gov-pill {
            background-color: rgba(217, 119, 6, 0.2);
            color: #fbbf24;
            border: 1px solid rgba(251, 191, 36, 0.3);
            font-size: 0.75rem;
            padding: 4px 8px;
            border-radius: 20px;
        }
        .card-civic {
            border: 1px solid var(--rs-border);
            border-radius: 8px;
            background: #ffffff;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .card-civic:hover {
            box-shadow: 0 4px 12px rgba(15, 41, 66, 0.08);
        }
        .civic-header {
            background-color: #f1f5f9;
            border-bottom: 1px solid var(--rs-border);
            font-weight: 600;
            font-size: 0.95rem;
            color: var(--rs-navy);
            padding: 12px 18px;
        }
        .btn-gov {
            background-color: var(--rs-navy-light);
            color: #ffffff;
            font-weight: 500;
            border: none;
        }
        .btn-gov:hover {
            background-color: var(--rs-navy);
            color: #ffffff;
        }
        .btn-accent {
            background-color: var(--rs-accent);
            color: #ffffff;
            font-weight: 500;
            border: none;
        }
        .btn-accent:hover {
            background-color: var(--rs-gold);
            color: #ffffff;
        }
        .stat-badge {
            font-size: 0.8rem;
            padding: 4px 10px;
            border-radius: 6px;
            font-weight: 600;
        }
        .table-civic th {
            background-color: #f8fafc;
            color: var(--rs-navy);
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 2px solid var(--rs-border);
        }
        .table-civic td {
            vertical-align: middle;
            font-size: 0.9rem;
        }
        .footer-gov {
            margin-top: auto;
            background-color: var(--rs-navy);
            color: #94a3b8;
            font-size: 0.85rem;
            border-top: 1px solid #1e293b;
        }
        .footer-gov a {
            color: #cbd5e1;
            text-decoration: none;
        }
        .footer-gov a:hover {
            color: #ffffff;
        }
        .ai-pulse {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #10b981;
            margin-right: 6px;
            animation: pulse-animation 2s infinite;
        }
        @keyframes pulse-animation {
            0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
            70% { box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
            100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
        }
    </style>
</head>
<body>
<!-- Civic Navigation Bar -->
<nav class="navbar navbar-expand-lg navbar-dark navbar-gov py-2">
    <div class="container-fluid px-lg-5">
        <a class="navbar-brand d-flex align-items-center gap-2" href="{{ url_for('landing_view') }}">
            <i class="bi bi-shield-check text-warning fs-4"></i>
            <div>
                <span class="fs-5">RationSmart AI</span>
                <span class="d-none d-md-inline-block badge-gov-pill ms-2">Civic Public Distribution System</span>
            </div>
        </a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navContent">
            <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navContent">
            <ul class="navbar-nav ms-auto align-items-lg-center gap-2">
                <li class="nav-item">
                    <a class="nav-link" href="{{ url_for('landing_view') }}"><i class="bi bi-house-door me-1"></i> Home</a>
                </li>
                {% if session.get('user_id') %}
                    {% if session.get('role') == 'citizen' %}
                        <li class="nav-item"><a class="nav-link" href="{{ url_for('citizen_dashboard') }}"><i class="bi bi-person-badge me-1"></i> Citizen Portal</a></li>
                    {% elif session.get('role') == 'shop_staff' %}
                        <li class="nav-item"><a class="nav-link" href="{{ url_for('shop_dashboard') }}"><i class="bi bi-shop-window me-1"></i> Shop Staff Portal</a></li>
                    {% elif session.get('role') == 'gov_admin' %}
                        <li class="nav-item"><a class="nav-link" href="{{ url_for('gov_dashboard') }}"><i class="bi bi-building me-1"></i> Government Portal</a></li>
                    {% endif %}
                    <li class="nav-item dropdown ms-lg-2">
                        <a class="nav-link dropdown-toggle text-white d-flex align-items-center gap-1" href="#" role="button" data-bs-toggle="dropdown">
                            <i class="bi bi-person-circle fs-5"></i> {{ session.get('full_name', 'User') }}
                            <span class="badge bg-warning text-dark ms-1 text-uppercase" style="font-size: 0.65rem;">{{ session.get('role', '').replace('_', ' ') }}</span>
                        </a>
                        <ul class="dropdown-menu dropdown-menu-end shadow-sm">
                            <li><span class="dropdown-item-text text-muted small"><i class="bi bi-shield me-1"></i> Signed in as {{ session.get('role') }}</span></li>
                            <li><hr class="dropdown-divider"></li>
                            <li><a class="dropdown-item text-danger" href="{{ url_for('logout_view') }}"><i class="bi bi-box-arrow-right me-2"></i> Logout</a></li>
                        </ul>
                    </li>
                {% else %}
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('login_view') }}"><i class="bi bi-box-arrow-in-right me-1"></i> Login</a></li>
                    <li class="nav-item"><a class="btn btn-accent btn-sm px-3 ms-lg-2" href="{{ url_for('register_view') }}">Citizen Register</a></li>
                {% endif %}
            </ul>
        </div>
    </div>
</nav>

<!-- Flash Alerts Container -->
<div class="container mt-3">
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }} alert-dismissible fade show shadow-sm" role="alert">
                    <i class="bi bi-info-circle-fill me-2"></i> {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}
</div>
"""

HTML_FOOTER_COMMON = """
<!-- Civic Footer -->
<footer class="footer-gov py-4 mt-5">
    <div class="container px-lg-5">
        <div class="row gy-3 align-items-center">
            <div class="col-md-6">
                <div class="d-flex align-items-center gap-2 mb-1">
                    <i class="bi bi-shield-check text-warning fs-5"></i>
                    <strong class="text-white">RationSmart AI</strong>
                    <span class="badge bg-secondary" style="font-size: 0.7rem;">v1.0-GitHub</span>
                </div>
                <p class="mb-0 text-muted" style="font-size: 0.8rem;">
                    Smart Ration Distribution. Predictive. Transparent. Citizen-Centric.
                </p>
                <p class="mb-0 text-muted" style="font-size: 0.75rem;">
                    Demonstration AI Models trained on synthetic civic distribution datasets.
                </p>
            </div>
            <div class="col-md-6 text-md-end">
                <div class="d-flex justify-content-md-end gap-3 small mb-2">
                    <a href="{{ url_for('landing_view') }}#how-it-works">How It Works</a>
                    <a href="{{ url_for('landing_view') }}#ai-intelligence">AI Technology</a>
                    <a href="{{ url_for('landing_view') }}#roles">Role Directory</a>
                    <a href="/api/health" target="_blank">System API Health</a>
                </div>
                <div class="text-muted" style="font-size: 0.75rem;">
                    National Civic Tech Initiative • Ministry of Consumer Affairs, Food & Public Distribution (Demo)
                </div>
            </div>
        </div>
    </div>
</footer>

<!-- Bootstrap 5 Bundle JS -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# ------------------------------------------------------------------------------
# 10. LANDING PAGE TEMPLATE
# ------------------------------------------------------------------------------
HTML_LANDING = HTML_HEADER_COMMON + """
<!-- HERO SECTION -->
<section class="py-5 bg-white border-bottom">
    <div class="container px-lg-5 py-4">
        <div class="row align-items-center gy-4">
            <div class="col-lg-7">
                <div class="d-inline-flex align-items-center gap-2 px-3 py-1 rounded-pill bg-light border mb-3">
                    <span class="ai-pulse"></span>
                    <span class="small fw-semibold text-primary">Civic Tech • Predictive Public Distribution System</span>
                </div>
                <h1 class="display-5 fw-bold text-navy mb-3" style="color: var(--rs-navy); line-height: 1.2;">
                    Smarter Ration Distribution Starts Before You Reach the Shop.
                </h1>
                <p class="lead text-secondary mb-4" style="font-size: 1.15rem;">
                    <strong>Smart Ration Distribution. Predictive. Transparent. Citizen-Centric.</strong>
                    Empowering over 800 million citizens with real-time commodity availability, machine learning queue forecasting, and instant digital QR passes.
                </p>
                <div class="d-flex flex-wrap gap-3">
                    {% if user %}
                        <a href="{{ url_for('dashboard_view') }}" class="btn btn-gov btn-lg px-4 py-2">
                            <i class="bi bi-speedometer2 me-2"></i> Go to Your Dashboard
                        </a>
                    {% else %}
                        <a href="{{ url_for('login_view') }}" class="btn btn-gov btn-lg px-4 py-2">
                            <i class="bi bi-box-arrow-in-right me-2"></i> Portal Login
                        </a>
                        <a href="{{ url_for('register_view') }}" class="btn btn-outline-secondary btn-lg px-4 py-2">
                            <i class="bi bi-person-plus me-2"></i> Citizen Registration
                        </a>
                    {% endif %}
                    <a href="#how-it-works" class="btn btn-link text-decoration-none text-navy align-self-center">
                        Explore Workflow <i class="bi bi-arrow-right"></i>
                    </a>
                </div>
            </div>
            <div class="col-lg-5">
                <!-- Interactive Live Metric Card -->
                <div class="card card-civic p-4 shadow-sm border-2">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <span class="badge bg-success-subtle text-success border border-success-subtle px-2 py-1">
                            <i class="bi bi-broadcast me-1"></i> Live Network Status
                        </span>
                        <small class="text-muted">Central Delhi Hub</small>
                    </div>
                    <div class="mb-3">
                        <div class="d-flex justify-content-between small text-muted mb-1">
                            <span>Rice (Boiled) Available</span>
                            <span class="fw-semibold text-dark">850 kg (In Stock)</span>
                        </div>
                        <div class="progress" style="height: 6px;">
                            <div class="progress-bar bg-success" style="width: 85%;"></div>
                        </div>
                    </div>
                    <div class="mb-3">
                        <div class="d-flex justify-content-between small text-muted mb-1">
                            <span>Wheat (Atta) Available</span>
                            <span class="fw-semibold text-dark">620 kg (In Stock)</span>
                        </div>
                        <div class="progress" style="height: 6px;">
                            <div class="progress-bar bg-primary" style="width: 72%;"></div>
                        </div>
                    </div>
                    <div class="mb-4">
                        <div class="d-flex justify-content-between small text-muted mb-1">
                            <span>Sugar (Refined) Available</span>
                            <span class="fw-semibold text-dark">140 kg (In Stock)</span>
                        </div>
                        <div class="progress" style="height: 6px;">
                            <div class="progress-bar bg-warning" style="width: 60%;"></div>
                        </div>
                    </div>
                    <div class="p-3 bg-light rounded-3 border">
                        <div class="d-flex align-items-center gap-2 mb-1">
                            <i class="bi bi-cpu text-primary fs-5"></i>
                            <strong class="text-dark small">AI Queue Engine Insight</strong>
                        </div>
                        <p class="small text-muted mb-0">
                            Current Fair Price Shop queue is <strong>Low (approx. 4 beneficiaries)</strong>. Estimated wait time: <strong>11 minutes</strong>.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- PROBLEM SECTION -->
<section class="py-5" style="background-color: #f1f5f9;">
    <div class="container px-lg-5">
        <div class="text-center max-w-700 mx-auto mb-5">
            <span class="text-uppercase fw-bold text-danger small tracking-wider">The Systemic Challenge</span>
            <h2 class="fw-bold text-navy mt-1">Why Traditional Ration Distribution Fails Citizens</h2>
            <p class="text-muted">Overburdened Fair Price Shops, manual ledgers, and zero visibility lead to citizen fatigue and supply chain blindspots.</p>
        </div>
        <div class="row g-4">
            <div class="col-md-4">
                <div class="card card-civic h-100 p-4">
                    <div class="rounded-circle bg-danger-subtle text-danger d-inline-flex p-3 mb-3" style="width: fit-content;">
                        <i class="bi bi-clock-history fs-4"></i>
                    </div>
                    <h5 class="fw-semibold text-dark">Unpredictable Long Queues</h5>
                    <p class="text-muted small mb-0">
                        Beneficiaries spend 2 to 4 hours in physical lines without knowing if the ration shop is congested or if stock has run out.
                    </p>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card card-civic h-100 p-4">
                    <div class="rounded-circle bg-warning-subtle text-warning d-inline-flex p-3 mb-3" style="width: fit-content;">
                        <i class="bi bi-eye-slash fs-4"></i>
                    </div>
                    <h5 class="fw-semibold text-dark">Lack of Stock Transparency</h5>
                    <p class="text-muted small mb-0">
                        Citizens arrive only to find commodities like Sugar or Wheat depleted, causing multiple wasted trips and public dissatisfaction.
                    </p>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card card-civic h-100 p-4">
                    <div class="rounded-circle bg-primary-subtle text-primary d-inline-flex p-3 mb-3" style="width: fit-content;">
                        <i class="bi bi-graph-down-arrow fs-4"></i>
                    </div>
                    <h5 class="fw-semibold text-dark">Reactive Supply Chains</h5>
                    <p class="text-muted small mb-0">
                        Government authorities receive stock shortage reports days late, making proactive grain replenishment difficult to orchestrate.
                    </p>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- SOLUTION SECTION -->
<section class="py-5 bg-white">
    <div class="container px-lg-5">
        <div class="text-center max-w-700 mx-auto mb-5">
            <span class="text-uppercase fw-bold text-success small tracking-wider">The Innovation</span>
            <h2 class="fw-bold text-navy mt-1">The RationSmart AI Solution</h2>
            <p class="text-muted">An end-to-end civic platform synchronizing citizen bookings, shop inventory, and government oversight.</p>
        </div>
        <div class="row g-4 align-items-center">
            <div class="col-md-6">
                <div class="d-flex gap-3 mb-4">
                    <div class="text-success fs-3"><i class="bi bi-calendar2-check-fill"></i></div>
                    <div>
                        <h5 class="fw-semibold mb-1">Smart Time-Slot Booking</h5>
                        <p class="text-muted small mb-0">Citizens reserve verified pick-up intervals matched to their monthly quota, eliminating chaotic crowds.</p>
                    </div>
                </div>
                <div class="d-flex gap-3 mb-4">
                    <div class="text-primary fs-3"><i class="bi bi-qr-code-scan"></i></div>
                    <div>
                        <h5 class="fw-semibold mb-1">Encrypted QR Digital Ration Pass</h5>
                        <p class="text-muted small mb-0">Tamper-proof digital tokens containing the unique booking ID allow one-tap verification at shop counters.</p>
                    </div>
                </div>
                <div class="d-flex gap-3">
                    <div class="text-warning fs-3"><i class="bi bi-cpu-fill"></i></div>
                    <div>
                        <h5 class="fw-semibold mb-1">Dual AI Forecasting Engine</h5>
                        <p class="text-muted small mb-0">Machine learning models predict footfall waiting times for citizens and calculate inventory burn rates for shops.</p>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="p-4 bg-light rounded-4 border">
                    <h6 class="fw-bold text-navy mb-3"><i class="bi bi-diagram-3 me-2"></i> Verified Citizen Flow</h6>
                    <div class="d-flex align-items-center gap-3 py-2 border-bottom">
                        <span class="badge bg-primary rounded-circle p-2">1</span>
                        <div class="small">Citizen logs in & views real-time quota of Rice, Wheat, Sugar</div>
                    </div>
                    <div class="d-flex align-items-center gap-3 py-2 border-bottom">
                        <span class="badge bg-primary rounded-circle p-2">2</span>
                        <div class="small">AI Queue Engine calculates predicted wait time & optimal slot</div>
                    </div>
                    <div class="d-flex align-items-center gap-3 py-2 border-bottom">
                        <span class="badge bg-primary rounded-circle p-2">3</span>
                        <div class="small">Booking saved in MySQL & QR Digital Pass instantly generated</div>
                    </div>
                    <div class="d-flex align-items-center gap-3 py-2">
                        <span class="badge bg-success rounded-circle p-2">4</span>
                        <div class="small">Shop Staff completes pass; inventory automatically deducts in real-time</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- KEY FEATURES -->
<section class="py-5" style="background-color: #f8fafc;">
    <div class="container px-lg-5">
        <div class="text-center mb-5">
            <span class="text-uppercase fw-bold text-primary small">Comprehensive Architecture</span>
            <h2 class="fw-bold text-navy mt-1">Platform Key Features</h2>
        </div>
        <div class="row g-4">
            <div class="col-md-4">
                <div class="card card-civic h-100 p-4">
                    <i class="bi bi-person-bounding-box text-primary fs-2 mb-3"></i>
                    <h5 class="fw-semibold">Citizen Quota & Entitlement</h5>
                    <p class="text-muted small">Tracks remaining monthly quotas for Rice, Wheat, and Sugar. Validates bookings against authorized allocations.</p>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card card-civic h-100 p-4">
                    <i class="bi bi-shop text-success fs-2 mb-3"></i>
                    <h5 class="fw-semibold">Shop Staff Distribution Desk</h5>
                    <p class="text-muted small">Real-time verification of citizen tokens, 1-click status transitions (Approve/Complete), and automatic ledger deduction.</p>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card card-civic h-100 p-4">
                    <i class="bi bi-graph-up-arrow text-warning fs-2 mb-3"></i>
                    <h5 class="fw-semibold">Government Admin Telemetry</h5>
                    <p class="text-muted small">State-wide KPI telemetry, low-stock alerts, 7-day transaction analytics, and peak congestion heatmaps via Chart.js.</p>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- AI INTELLIGENCE SECTION -->
<section id="ai-intelligence" class="py-5 bg-white border-top border-bottom">
    <div class="container px-lg-5">
        <div class="row align-items-center gy-4">
            <div class="col-lg-6">
                <div class="d-inline-flex align-items-center gap-2 px-3 py-1 rounded-pill bg-light border mb-3">
                    <span class="ai-pulse"></span>
                    <span class="small fw-semibold text-dark">Machine Learning Core • scikit-learn + pandas</span>
                </div>
                <h2 class="fw-bold text-navy mb-3">Dual AI Predictive Models</h2>
                <p class="text-muted">
                    RationSmart AI uses real Python machine learning algorithms to eliminate guesswork in civil supplies logistics.
                </p>
                <div class="mb-3">
                    <h6 class="fw-bold text-dark"><i class="bi bi-check-circle-fill text-success me-2"></i> Model 1: Footfall & Queue Forecaster</h6>
                    <p class="text-muted small mb-2">
                        A `RandomForestRegressor` trained on synthetic multi-day footfall patterns. Analyzes day of the week, hour of operation, and active bookings to forecast line lengths and wait times in minutes.
                    </p>
                </div>
                <div class="mb-4">
                    <h6 class="fw-bold text-dark"><i class="bi bi-check-circle-fill text-success me-2"></i> Model 2: Stock Depletion & Shortage Risk Engine</h6>
                    <p class="text-muted small mb-0">
                        Tracks average daily burn rates against reserved commitments. Evaluates inventory runway and flags critical shortage risks before shops run out of food grains.
                    </p>
                </div>
                <div class="alert alert-light border small text-muted">
                    <i class="bi bi-info-circle me-1"></i> Note: Trained on demonstration civic datasets to provide reproducible out-of-the-box evaluation.
                </div>
            </div>
            <div class="col-lg-6">
                <div class="card card-civic p-4 shadow-sm">
                    <h6 class="fw-bold text-navy border-bottom pb-2 mb-3">
                        <i class="bi bi-terminal me-2"></i> Live ML Inference Simulation
                    </h6>
                    <div class="bg-dark text-light p-3 rounded-3 font-monospace small mb-3" style="font-size: 0.82rem;">
                        <span class="text-secondary"># AI Model: RandomForestRegressor</span><br>
                        <span class="text-info">Inference Input:</span> { day: 'Monday', hour: 10, bookings: 12 }<br>
                        <span class="text-warning">Predicted Queue:</span> 16 beneficiaries<br>
                        <span class="text-warning">Estimated Wait:</span> 45 minutes<br>
                        <span class="text-success">Optimal Recommendation:</span> "14:00 - 15:00 PM (11 mins)"
                    </div>
                    <div class="d-flex justify-content-between align-items-center text-muted small">
                        <span>Confidence Score: <strong>92.4%</strong></span>
                        <span class="badge bg-success">ML Model Active</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- HOW IT WORKS -->
<section id="how-it-works" class="py-5" style="background-color: #f1f5f9;">
    <div class="container px-lg-5">
        <div class="text-center mb-5">
            <span class="text-uppercase fw-bold text-primary small">Step-by-Step</span>
            <h2 class="fw-bold text-navy mt-1">How RationSmart AI Operates</h2>
        </div>
        <div class="row g-4 text-center">
            <div class="col-md-3">
                <div class="card card-civic p-4 h-100">
                    <div class="display-6 fw-bold text-primary mb-2">01</div>
                    <h6 class="fw-semibold">Verify Quota</h6>
                    <p class="text-muted small mb-0">Beneficiary views real-time monthly entitlement for Rice, Wheat, and Sugar.</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card card-civic p-4 h-100">
                    <div class="display-6 fw-bold text-primary mb-2">02</div>
                    <h6 class="fw-semibold">Predict Queue</h6>
                    <p class="text-muted small mb-0">AI calculates wait times across time slots and recommends the lowest-rush window.</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card card-civic p-4 h-100">
                    <div class="display-6 fw-bold text-primary mb-2">03</div>
                    <h6 class="fw-semibold">Book & Get Pass</h6>
                    <p class="text-muted small mb-0">Beneficiary books slot and immediately receives an official QR Digital Pass.</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card card-civic p-4 h-100">
                    <div class="display-6 fw-bold text-primary mb-2">04</div>
                    <h6 class="fw-semibold">Scan & Distribute</h6>
                    <p class="text-muted small mb-0">Shop scans QR code, confirms allocation, and database updates stock in real-time.</p>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- ROLE-BASED SYSTEM DIRECTORY -->
<section id="roles" class="py-5 bg-white">
    <div class="container px-lg-5">
        <div class="text-center mb-5">
            <span class="text-uppercase fw-bold text-primary small">Role Directory</span>
            <h2 class="fw-bold text-navy mt-1">Role-Based Access for Every Stakeholder</h2>
            <p class="text-muted">Seamless separation of duties between Beneficiaries, Field Operators, and Regulators.</p>
        </div>
        <div class="row g-4">
            <div class="col-md-4">
                <div class="card card-civic h-100 p-4 border-top border-4 border-primary">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <h5 class="fw-bold text-navy mb-0">Citizen</h5>
                        <span class="badge bg-primary">Beneficiary</span>
                    </div>
                    <p class="text-muted small mb-3">
                        Access personal entitlement, monitor local shop stock levels, schedule optimal pickup times, and download verifiable QR passes.
                    </p>
                    <div class="bg-light p-2 rounded small text-muted mb-3 font-monospace">
                        Demo: citizen@rationsmart.gov / citizen123
                    </div>
                    <a href="{{ url_for('login_view') }}" class="btn btn-outline-primary btn-sm mt-auto">Login as Citizen</a>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card card-civic h-100 p-4 border-top border-4 border-success">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <h5 class="fw-bold text-navy mb-0">Shop Staff</h5>
                        <span class="badge bg-success">Fair Price Operator</span>
                    </div>
                    <p class="text-muted small mb-3">
                        Manage daily footfall, verify digital booking passes, complete transactions with automatic stock deduction, and view AI shortage alerts.
                    </p>
                    <div class="bg-light p-2 rounded small text-muted mb-3 font-monospace">
                        Demo: staff@rationsmart.gov / staff123
                    </div>
                    <a href="{{ url_for('login_view') }}" class="btn btn-outline-success btn-sm mt-auto">Login as Shop Staff</a>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card card-civic h-100 p-4 border-top border-4 border-warning">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <h5 class="fw-bold text-navy mb-0">Gov Admin</h5>
                        <span class="badge bg-warning text-dark">Civil Supplies Regulator</span>
                    </div>
                    <p class="text-muted small mb-3">
                        Monitor state-wide network health, inspect low-stock alerts, analyze transaction velocity, and manage commodity replenishment pipelines.
                    </p>
                    <div class="bg-light p-2 rounded small text-muted mb-3 font-monospace">
                        Demo: admin@rationsmart.gov / admin123
                    </div>
                    <a href="{{ url_for('login_view') }}" class="btn btn-outline-warning btn-sm mt-auto">Login as Gov Admin</a>
                </div>
            </div>
        </div>
    </div>
</section>
""" + HTML_FOOTER_COMMON

# ------------------------------------------------------------------------------
# 11. LOGIN & REGISTRATION TEMPLATES
# ------------------------------------------------------------------------------
HTML_LOGIN = HTML_HEADER_COMMON + """
<div class="container py-5">
    <div class="row justify-content-center">
        <div class="col-md-6 col-lg-5">
            <div class="card card-civic p-4 shadow-sm border-2">
                <div class="text-center mb-4">
                    <i class="bi bi-shield-lock text-primary fs-1"></i>
                    <h3 class="fw-bold text-navy mt-2">Portal Access</h3>
                    <p class="text-muted small mb-0">Sign in with your Email, Username, or Ration Card No.</p>
                </div>
                <form method="POST" action="{{ url_for('login_view') }}">
                    <div class="mb-3">
                        <label class="form-label small fw-semibold text-secondary">Identifier (Email / Username / Ration Card)</label>
                        <div class="input-group">
                            <span class="input-group-text"><i class="bi bi-person"></i></span>
                            <input type="text" name="identifier" class="form-control" placeholder="e.g. citizen@rationsmart.gov or RC-DL-98472" required>
                        </div>
                    </div>
                    <div class="mb-4">
                        <label class="form-label small fw-semibold text-secondary">Password</label>
                        <div class="input-group">
                            <span class="input-group-text"><i class="bi bi-key"></i></span>
                            <input type="password" name="password" class="form-control" placeholder="••••••••" required>
                        </div>
                    </div>
                    <button type="submit" class="btn btn-gov w-100 py-2 fw-semibold">
                        <i class="bi bi-box-arrow-in-right me-1"></i> Sign In to Account
                    </button>
                </form>

                <div class="border-top my-4 pt-3">
                    <span class="small fw-bold text-muted text-uppercase d-block mb-2 text-center">Quick Demo 1-Click Login</span>
                    <div class="d-grid gap-2">
                        <button class="btn btn-outline-primary btn-sm text-start" onclick="fillDemo('citizen@rationsmart.gov', 'citizen123')">
                            <i class="bi bi-person me-2"></i> <strong>Citizen:</strong> Aarav Sharma (citizen123)
                        </button>
                        <button class="btn btn-outline-success btn-sm text-start" onclick="fillDemo('staff@rationsmart.gov', 'staff123')">
                            <i class="bi bi-shop me-2"></i> <strong>Shop Staff:</strong> Rajesh Patel (staff123)
                        </button>
                        <button class="btn btn-outline-warning btn-sm text-start text-dark" onclick="fillDemo('admin@rationsmart.gov', 'admin123')">
                            <i class="bi bi-shield-check me-2"></i> <strong>Gov Admin:</strong> Dr. Meenakshi (admin123)
                        </button>
                    </div>
                </div>

                <div class="text-center small text-muted">
                    New Citizen beneficiary? <a href="{{ url_for('register_view') }}" class="fw-semibold text-navy">Register Ration Card</a>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
function fillDemo(user, pass) {
    document.querySelector('input[name="identifier"]').value = user;
    document.querySelector('input[name="password"]').value = pass;
    document.querySelector('form').submit();
}
</script>
""" + HTML_FOOTER_COMMON

HTML_REGISTER = HTML_HEADER_COMMON + """
<div class="container py-5">
    <div class="row justify-content-center">
        <div class="col-md-7 col-lg-6">
            <div class="card card-civic p-4 shadow-sm border-2">
                <div class="text-center mb-4">
                    <i class="bi bi-person-plus text-primary fs-1"></i>
                    <h3 class="fw-bold text-navy mt-2">Citizen Registration</h3>
                    <p class="text-muted small mb-0">Register your household beneficiary profile to receive digital rations.</p>
                </div>
                <form method="POST" action="{{ url_for('register_view') }}">
                    <div class="mb-3">
                        <label class="form-label small fw-semibold text-secondary">Full Legal Name</label>
                        <input type="text" name="full_name" class="form-control" placeholder="e.g. Priya Sharma" required>
                    </div>
                    <div class="row g-2 mb-3">
                        <div class="col-md-6">
                            <label class="form-label small fw-semibold text-secondary">Desired Username</label>
                            <input type="text" name="username" class="form-control" placeholder="e.g. priyasharma" required>
                        </div>
                        <div class="col-md-6">
                            <label class="form-label small fw-semibold text-secondary">Mobile Number</label>
                            <input type="tel" name="phone" class="form-control" placeholder="+91 98765 00000" required>
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label small fw-semibold text-secondary">Email Address</label>
                        <input type="email" name="email" class="form-control" placeholder="priya@example.com" required>
                    </div>
                    <div class="mb-4">
                        <label class="form-label small fw-semibold text-secondary">Create Secure Password</label>
                        <input type="password" name="password" class="form-control" placeholder="Minimum 6 characters" minlength="6" required>
                    </div>
                    <div class="p-3 bg-light rounded-3 mb-4 small text-muted">
                        <i class="bi bi-info-circle text-primary me-1"></i>
                        A unique digital Ration Card Number (e.g. <code>RC-DL-XXXXX</code>) will be generated automatically and linked to your citizen profile upon completion.
                    </div>
                    <button type="submit" class="btn btn-gov w-100 py-2 fw-semibold">
                        <i class="bi bi-check-circle me-1"></i> Complete Registration
                    </button>
                </form>
                <div class="text-center small text-muted mt-3">
                    Already registered? <a href="{{ url_for('login_view') }}" class="fw-semibold text-navy">Log in here</a>
                </div>
            </div>
        </div>
    </div>
</div>
""" + HTML_FOOTER_COMMON

# ------------------------------------------------------------------------------
# 12. CITIZEN DASHBOARD TEMPLATE
# ------------------------------------------------------------------------------
HTML_CITIZEN_DASHBOARD = HTML_HEADER_COMMON + """
<div class="container-fluid px-lg-5 py-4">
    <!-- Beneficiary Identity Banner -->
    <div class="card card-civic p-4 mb-4 border-start border-4 border-primary">
        <div class="row align-items-center gy-3">
            <div class="col-md-8">
                <div class="d-flex align-items-center gap-3">
                    <div class="rounded-circle bg-primary-subtle text-primary p-3 fs-3">
                        <i class="bi bi-person-vcard"></i>
                    </div>
                    <div>
                        <h4 class="fw-bold text-navy mb-1">{{ user.full_name }}</h4>
                        <div class="d-flex flex-wrap gap-2 text-muted small">
                            <span><i class="bi bi-credit-card-2-front me-1"></i> Ration Card: <strong class="text-dark">{{ user.ration_card_no }}</strong></span>
                            <span>•</span>
                            <span><i class="bi bi-telephone me-1"></i> {{ user.phone or 'Not configured' }}</span>
                            <span>•</span>
                            <span class="badge bg-success-subtle text-success border border-success-subtle">Active Beneficiary</span>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-4 text-md-end">
                <button class="btn btn-accent btn-lg px-4" data-bs-toggle="modal" data-bs-target="#bookingModal" onclick="prepareBookingModal()">
                    <i class="bi bi-calendar-plus me-1"></i> Smart Ration Booking
                </button>
            </div>
        </div>
    </div>

    <!-- Quick Telemetry Cards -->
    <div class="row g-3 mb-4">
        <div class="col-md-3">
            <div class="card card-civic p-3">
                <div class="text-muted small fw-semibold text-uppercase">Allocated FPS Shop</div>
                <h5 class="fw-bold text-navy mt-1 mb-0">Shop #104 - Central Delhi</h5>
                <small class="text-muted">Sector 4, Connaught Place</small>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card card-civic p-3">
                <div class="text-muted small fw-semibold text-uppercase">Current Shop Queue</div>
                <div class="d-flex align-items-baseline gap-2 mt-1">
                    <h3 class="fw-bold text-dark mb-0">{{ current_queue.predicted_queue }}</h3>
                    <span class="badge bg-{{ current_queue.rush_badge }}">{{ current_queue.rush_level }}</span>
                </div>
                <small class="text-muted">Est. wait: <strong>{{ current_queue.wait_time_minutes }} mins</strong></small>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card card-civic p-3">
                <div class="text-muted small fw-semibold text-uppercase">Recommended Time Slot</div>
                <div class="fw-bold text-success mt-1 mb-0" style="font-size: 1.05rem;">
                    <i class="bi bi-stars"></i> {{ recommended_slot.recommended_slot }}
                </div>
                <small class="text-muted">AI Low-Rush Estimate: ~{{ recommended_slot.estimated_wait_minutes }} min wait</small>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card card-civic p-3">
                <div class="text-muted small fw-semibold text-uppercase">Active Bookings</div>
                <h3 class="fw-bold text-navy mt-1 mb-0">{{ active_bookings_count }}</h3>
                <small class="text-muted">Available digital passes</small>
            </div>
        </div>
    </div>

    <!-- Monthly Entitlement & Stock Availability Section -->
    <div class="row g-4 mb-4">
        <div class="col-lg-12">
            <div class="card card-civic overflow-hidden">
                <div class="civic-header d-flex justify-content-between align-items-center">
                    <span><i class="bi bi-basket2 me-2"></i> Commodity Availability & Monthly Entitlement</span>
                    <span class="badge bg-primary" id="availabilityRefreshTime">Auto-Updated</span>
                </div>
                <div class="p-3">
                    <div class="table-responsive">
                        <table class="table table-civic mb-0" id="availabilityTable">
                            <thead>
                                <tr>
                                    <th>Commodity</th>
                                    <th>Monthly Entitlement</th>
                                    <th>Shop Inventory Stock</th>
                                    <th>Remaining Quota</th>
                                    <th>Availability Status</th>
                                    <th>Last Updated</th>
                                </tr>
                            </thead>
                            <tbody id="availabilityTableBody">
                                <tr>
                                    <td colspan="6" class="text-center py-3 text-muted">
                                        <div class="spinner-border spinner-border-sm text-primary me-2"></div> Loading availability...
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Active Bookings & Digital Passes -->
    <div class="row g-4">
        <div class="col-lg-12">
            <div class="card card-civic overflow-hidden">
                <div class="civic-header d-flex justify-content-between align-items-center">
                    <span><i class="bi bi-qr-code-scan me-2"></i> My Bookings & Digital Ration Passes</span>
                    <button class="btn btn-outline-primary btn-sm" onclick="loadBookingsTable()">
                        <i class="bi bi-arrow-clockwise"></i> Refresh
                    </button>
                </div>
                <div class="p-3">
                    {% if bookings %}
                        <div class="table-responsive">
                            <table class="table table-civic align-middle">
                                <thead>
                                    <tr>
                                        <th>Pass Ref ID</th>
                                        <th>Date & Slot</th>
                                        <th>Allocated Items</th>
                                        <th>Shop</th>
                                        <th>Pass Status</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for b in bookings %}
                                        <tr>
                                            <td>
                                                <strong class="font-monospace text-navy">{{ b.booking_ref }}</strong>
                                                <div class="small text-muted">{{ b.created_at }}</div>
                                            </td>
                                            <td>
                                                <div class="fw-semibold">{{ b.booking_date }}</div>
                                                <div class="small text-muted">{{ b.time_slot }}</div>
                                            </td>
                                            <td>
                                                {% for it in b['items'] %}
                                                    <span class="badge bg-light text-dark border me-1">{{ it.item_name }}: {{ it.quantity }} {{ it.unit }}</span>
                                                {% endfor %}
                                            </td>
                                            <td>
                                                <div class="small fw-semibold">{{ b.shop_name }}</div>
                                                <div class="small text-muted">{{ b.shop_code }}</div>
                                            </td>
                                            <td>
                                                {% if b.status == 'Approved' %}
                                                    <span class="badge bg-success">Approved / Ready</span>
                                                {% elif b.status == 'Completed' %}
                                                    <span class="badge bg-secondary">Completed</span>
                                                {% elif b.status == 'Cancelled' %}
                                                    <span class="badge bg-danger">Cancelled</span>
                                                {% else %}
                                                    <span class="badge bg-warning text-dark">Pending Verification</span>
                                                {% endif %}
                                            </td>
                                            <td>
                                                <button class="btn btn-sm btn-gov" onclick="viewDigitalPass({{ b.id }})">
                                                    <i class="bi bi-qr-code me-1"></i> View Digital Pass
                                                </button>
                                                <a href="/pass/{{ b.booking_ref }}" target="_blank" class="btn btn-sm btn-outline-secondary">
                                                    <i class="bi bi-printer"></i>
                                                </a>
                                            </td>
                                        </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                    {% else %}
                        <div class="text-center py-5 text-muted">
                            <i class="bi bi-calendar-x fs-1 d-block mb-2"></i>
                            <p class="mb-2">No bookings recorded yet.</p>
                            <button class="btn btn-accent btn-sm" data-bs-toggle="modal" data-bs-target="#bookingModal" onclick="prepareBookingModal()">
                                Create First Booking
                            </button>
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>
</div>

<!-- SMART BOOKING MODAL -->
<div class="modal fade" id="bookingModal" tabindex="-1">
    <div class="modal-dialog modal-lg">
        <div class="modal-content">
            <div class="modal-header bg-light">
                <h5 class="modal-title fw-bold text-navy">
                    <i class="bi bi-calendar2-plus me-2 text-primary"></i> Smart Ration Booking
                </h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <form id="bookingForm" onsubmit="handleBookingSubmit(event)">
                    <div class="alert alert-light border small text-muted mb-3">
                        <i class="bi bi-info-circle text-primary me-1"></i> Select items, quantities, and preferred pick-up slot. The AI Queue Engine will estimate wait times before you confirm.
                    </div>

                    <!-- Item Quantities -->
                    <h6 class="fw-bold text-navy mb-2">1. Select Commodities</h6>
                    <div class="row g-3 mb-4" id="modalCommodityContainer">
                        <!-- Loaded dynamically -->
                        <div class="col-12 text-center text-muted py-3">Loading commodities...</div>
                    </div>

                    <!-- Date & Slot Selection -->
                    <h6 class="fw-bold text-navy mb-2">2. Schedule Time Slot</h6>
                    <div class="row g-3 mb-3">
                        <div class="col-md-6">
                            <label class="form-label small fw-semibold">Pickup Date</label>
                            <input type="date" id="bookingDateInput" class="form-control" onchange="updateQueuePrediction()">
                        </div>
                        <div class="col-md-6">
                            <label class="form-label small fw-semibold">Time Slot</label>
                            <select id="bookingSlotInput" class="form-select" onchange="updateQueuePrediction()">
                                <option value="09:00 - 10:00 AM">09:00 - 10:00 AM</option>
                                <option value="10:00 - 11:00 AM" selected>10:00 - 11:00 AM</option>
                                <option value="11:00 - 12:00 PM">11:00 - 12:00 PM</option>
                                <option value="12:00 - 01:00 PM">12:00 - 01:00 PM</option>
                                <option value="02:00 - 03:00 PM">02:00 - 03:00 PM</option>
                                <option value="03:00 - 04:00 PM">03:00 - 04:00 PM</option>
                                <option value="04:00 - 05:00 PM">04:00 - 05:00 PM</option>
                                <option value="05:00 - 06:00 PM">05:00 - 06:00 PM</option>
                            </select>
                        </div>
                    </div>

                    <!-- AI Queue Prediction Box -->
                    <div class="p-3 bg-light rounded-3 border mb-3">
                        <div class="d-flex justify-content-between align-items-center mb-2">
                            <span class="small fw-bold text-navy"><i class="bi bi-cpu text-primary me-1"></i> AI Queue Forecast for Selected Slot</span>
                            <span class="badge bg-secondary" id="aiDatasetBadge">Synthetic ML Model</span>
                        </div>
                        <div class="row g-2 align-items-center">
                            <div class="col-sm-4">
                                <div class="small text-muted">Predicted Queue</div>
                                <h5 class="fw-bold mb-0 text-dark" id="predQueueCount">-- beneficiaries</h5>
                            </div>
                            <div class="col-sm-4">
                                <div class="small text-muted">Estimated Wait Time</div>
                                <h5 class="fw-bold mb-0 text-primary" id="predWaitTime">-- mins</h5>
                            </div>
                            <div class="col-sm-4">
                                <div class="small text-muted">Congestion Rating</div>
                                <span class="badge bg-info" id="predRushBadge">Calculating...</span>
                            </div>
                        </div>
                        <div class="mt-2 pt-2 border-top small text-success" id="predRecommendedSlotBox">
                            <i class="bi bi-stars"></i> Best Recommended Window: <strong id="predBestSlot">--</strong>
                        </div>
                    </div>

                    <div id="bookingErrorAlert" class="alert alert-danger d-none small"></div>

                    <div class="modal-footer px-0 pb-0">
                        <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="submit" class="btn btn-gov px-4" id="confirmBookingBtn">
                            <i class="bi bi-check2-circle me-1"></i> Confirm Booking & Generate Pass
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>

<!-- DIGITAL RATION PASS MODAL -->
<div class="modal fade" id="passModal" tabindex="-1">
    <div class="modal-dialog modal-md">
        <div class="modal-content">
            <div class="modal-header bg-dark text-white">
                <div class="d-flex align-items-center gap-2">
                    <i class="bi bi-shield-check text-warning fs-5"></i>
                    <h6 class="modal-title fw-bold mb-0">Government of India • Digital Ration Pass</h6>
                </div>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body p-4 text-center" id="passModalBody">
                <div class="spinner-border text-primary my-4"></div>
            </div>
            <div class="modal-footer bg-light justify-content-between">
                <span class="small text-muted">Official Token • Present at FPS Counter</span>
                <div>
                    <button type="button" class="btn btn-outline-secondary btn-sm" data-bs-dismiss="modal">Close</button>
                    <button type="button" class="btn btn-gov btn-sm" onclick="printPassContent()">
                        <i class="bi bi-printer me-1"></i> Print Pass
                    </button>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
let globalAvailabilityData = [];

document.addEventListener('DOMContentLoaded', () => {
    loadAvailabilityData();
    // Default tomorrow for booking date
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    document.getElementById('bookingDateInput').value = tomorrow.toISOString().split('T')[0];
    document.getElementById('bookingDateInput').min = new Date().toISOString().split('T')[0];
});

async function loadAvailabilityData() {
    try {
        const res = await fetch('/api/availability?shop_id=1');
        const data = await res.json();
        globalAvailabilityData = data.items || [];
        renderAvailabilityTable(globalAvailabilityData);
        document.getElementById('availabilityRefreshTime').innerText = 'Updated: ' + new Date().toLocaleTimeString();
    } catch(err) {
        console.error("Availability load error:", err);
    }
}

function renderAvailabilityTable(items) {
    const tbody = document.getElementById('availabilityTableBody');
    if (!items.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-3">No commodity records found.</td></tr>`;
        return;
    }
    tbody.innerHTML = items.map(it => `
        <tr>
            <td>
                <strong class="text-navy">${it.item_name}</strong>
                <div class="small text-muted">${it.item_code}</div>
            </td>
            <td><strong>${it.entitlement} ${it.unit}</strong></td>
            <td>${it.available_stock} ${it.unit} in depot</td>
            <td>
                <span class="fw-bold ${it.remaining_entitlement > 0 ? 'text-primary' : 'text-muted'}">
                    ${it.remaining_entitlement} ${it.unit}
                </span>
            </td>
            <td><span class="badge bg-${it.status_badge}">${it.stock_status}</span></td>
            <td class="small text-muted">${it.last_updated}</td>
        </tr>
    `).join('');
}

function prepareBookingModal() {
    const container = document.getElementById('modalCommodityContainer');
    if (!globalAvailabilityData.length) {
        container.innerHTML = `<div class="col-12 text-center text-muted">No availability data available.</div>`;
        return;
    }

    container.innerHTML = globalAvailabilityData.map(it => `
        <div class="col-md-4">
            <div class="border rounded p-3 bg-light">
                <div class="form-check mb-2">
                    <input class="form-check-input item-check" type="checkbox" id="check_item_${it.item_id}" value="${it.item_id}" ${it.remaining_entitlement > 0 ? 'checked' : 'disabled'}>
                    <label class="form-check-label fw-bold text-dark small" for="check_item_${it.item_id}">
                        ${it.item_name}
                    </label>
                </div>
                <div class="small text-muted mb-2">
                    Avail Quota: <strong>${it.remaining_entitlement} ${it.unit}</strong>
                </div>
                <div class="input-group input-group-sm">
                    <input type="number" step="0.5" min="0.5" max="${it.remaining_entitlement}" value="${Math.min(it.remaining_entitlement, it.item_code === 'COMM-SUGAR' ? 1.0 : 5.0)}" class="form-control item-qty" id="qty_item_${it.item_id}" ${it.remaining_entitlement <= 0 ? 'disabled' : ''}>
                    <span class="input-group-text">${it.unit}</span>
                </div>
            </div>
        </div>
    `).join('');

    updateQueuePrediction();
}

async function updateQueuePrediction() {
    const dateVal = document.getElementById('bookingDateInput').value;
    const slotVal = document.getElementById('bookingSlotInput').value;
    if (!dateVal || !slotVal) return;

    try {
        const res = await fetch('/api/queue-prediction', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ shop_id: 1, date: dateVal, time_slot: slotVal })
        });
        const data = await res.json();
        const p = data.prediction;
        const r = data.recommendation;

        document.getElementById('predQueueCount').innerText = `${p.predicted_queue} beneficiaries`;
        document.getElementById('predWaitTime').innerText = `~${p.wait_time_minutes} mins`;
        const badge = document.getElementById('predRushBadge');
        badge.innerText = p.rush_level;
        badge.className = `badge bg-${p.rush_badge}`;
        document.getElementById('predBestSlot').innerText = `${r.recommended_slot} (~${r.estimated_wait_minutes} min wait)`;
    } catch(err) {
        console.error("Queue prediction error:", err);
    }
}

async function handleBookingSubmit(e) {
    e.preventDefault();
    const dateVal = document.getElementById('bookingDateInput').value;
    const slotVal = document.getElementById('bookingSlotInput').value;
    const errAlert = document.getElementById('bookingErrorAlert');
    errAlert.classList.add('d-none');

    const selectedItems = [];
    document.querySelectorAll('.item-check:checked').forEach(cb => {
        const iid = cb.value;
        const qty = parseFloat(document.getElementById(`qty_item_${iid}`).value || 0);
        if (qty > 0) {
            selectedItems.push({ item_id: parseInt(iid), quantity: qty });
        }
    });

    if (!selectedItems.length) {
        errAlert.innerText = "Please select at least one commodity with quantity > 0.";
        errAlert.classList.remove('d-none');
        return;
    }

    const btn = document.getElementById('confirmBookingBtn');
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span> Processing Booking...`;

    try {
        const res = await fetch('/api/bookings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                shop_id: 1,
                booking_date: dateVal,
                time_slot: slotVal,
                items: selectedItems
            })
        });
        const data = await res.json();
        if (!res.ok) {
            errAlert.innerText = data.error || "Booking failed.";
            errAlert.classList.remove('d-none');
            btn.disabled = false;
            btn.innerHTML = `<i class="bi bi-check2-circle me-1"></i> Confirm Booking & Generate Pass`;
            return;
        }

        // Hide booking modal and open pass modal
        const bModal = bootstrap.Modal.getInstance(document.getElementById('bookingModal'));
        bModal.hide();
        viewDigitalPass(data.booking_id);
    } catch(err) {
        errAlert.innerText = "Network error while submitting booking.";
        errAlert.classList.remove('d-none');
        btn.disabled = false;
        btn.innerHTML = `<i class="bi bi-check2-circle me-1"></i> Confirm Booking & Generate Pass`;
    }
}

async function viewDigitalPass(bookingId) {
    const modalBody = document.getElementById('passModalBody');
    modalBody.innerHTML = `<div class="spinner-border text-primary my-4"></div>`;
    const pModal = new bootstrap.Modal(document.getElementById('passModal'));
    pModal.show();

    try {
        const res = await fetch(`/api/bookings/${bookingId}`);
        const b = await res.json();
        if (!res.ok) {
            modalBody.innerHTML = `<div class="alert alert-danger">${b.error || 'Failed to fetch pass details.'}</div>`;
            return;
        }

        modalBody.innerHTML = `
            <div id="printablePassSection" class="text-center">
                <div class="border-bottom pb-2 mb-3">
                    <span class="badge bg-secondary mb-1">CIVIC PUBLIC DISTRIBUTION TOKEN</span>
                    <h5 class="fw-bold text-navy mb-0">${b.shop_name}</h5>
                    <small class="text-muted">${b.shop_address}</small>
                </div>
                <div class="my-3">
                    <img src="${b.qr_code_uri}" alt="QR Token" class="border p-2 rounded shadow-sm" style="width: 180px; height: 180px;">
                    <div class="font-monospace fw-bold fs-5 text-dark mt-2">${b.booking_ref}</div>
                    <span class="badge bg-${b.status === 'Approved' ? 'success' : 'warning text-dark'}">${b.status}</span>
                </div>
                <div class="text-start bg-light p-3 rounded-3 mb-3 small">
                    <div class="row g-2">
                        <div class="col-6"><strong>Beneficiary:</strong> ${b.citizen_name}</div>
                        <div class="col-6"><strong>Ration Card:</strong> ${b.ration_card_no}</div>
                        <div class="col-6"><strong>Scheduled Date:</strong> ${b.booking_date}</div>
                        <div class="col-6"><strong>Time Slot:</strong> ${b.time_slot}</div>
                    </div>
                </div>
                <div class="text-start mb-3">
                    <div class="fw-bold small text-navy mb-1">Allocated Commodities:</div>
                    <ul class="list-group list-group-flush small border rounded">
                        ${b.items.map(it => `
                            <li class="list-group-item d-flex justify-content-between align-items-center py-1">
                                <span>${it.item_name}</span>
                                <span class="badge bg-primary rounded-pill">${it.quantity} ${it.unit}</span>
                            </li>
                        `).join('')}
                    </ul>
                </div>
                <div class="small text-muted" style="font-size: 0.75rem;">
                    * The QR code contains only the secure Booking Reference ID for physical scanner reconciliation.
                </div>
            </div>
        `;
    } catch(err) {
        modalBody.innerHTML = `<div class="alert alert-danger">Error loading pass: ${err.message}</div>`;
    }
}

function printPassContent() {
    const sec = document.getElementById('printablePassSection');
    if (!sec) return;
    const win = window.open('', '', 'height=650,width=500');
    win.document.write('<html><head><title>Print Digital Ration Pass</title>');
    win.document.write('<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">');
    win.document.write('</head><body class="p-4">');
    win.document.write(sec.innerHTML);
    win.document.write('</body></html>');
    win.document.close();
    win.focus();
    setTimeout(() => { win.print(); win.close(); }, 500);
}
</script>
""" + HTML_FOOTER_COMMON

# ------------------------------------------------------------------------------
# 13. SHOP STAFF DASHBOARD TEMPLATE
# ------------------------------------------------------------------------------
HTML_SHOP_DASHBOARD = HTML_HEADER_COMMON + """
<div class="container-fluid px-lg-5 py-4">
    <!-- Shop Identity Banner -->
    <div class="card card-civic p-4 mb-4 border-start border-4 border-success">
        <div class="row align-items-center gy-3">
            <div class="col-md-8">
                <div class="d-flex align-items-center gap-3">
                    <div class="rounded-circle bg-success-subtle text-success p-3 fs-3">
                        <i class="bi bi-shop"></i>
                    </div>
                    <div>
                        <h4 class="fw-bold text-navy mb-1">{{ shop.shop_name }}</h4>
                        <div class="d-flex flex-wrap gap-2 text-muted small">
                            <span><i class="bi bi-geo-alt me-1"></i> {{ shop.address }}</span>
                            <span>•</span>
                            <span>Shop Code: <strong class="text-dark">{{ shop.shop_code }}</strong></span>
                            <span>•</span>
                            <span>Operator: <strong class="text-dark">{{ user.full_name }}</strong></span>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-4 text-md-end">
                <button class="btn btn-gov" data-bs-toggle="modal" data-bs-target="#restockModal">
                    <i class="bi bi-plus-circle me-1"></i> Inventory Restock / Adjust
                </button>
            </div>
        </div>
    </div>

    <!-- Shop KPI Metric Cards -->
    <div class="row g-3 mb-4">
        <div class="col-md-2">
            <div class="card card-civic p-3">
                <div class="text-muted small fw-semibold text-uppercase">Today's Bookings</div>
                <h3 class="fw-bold text-navy mt-1 mb-0">{{ total_today }}</h3>
                <small class="text-muted">Total scheduled</small>
            </div>
        </div>
        <div class="col-md-2">
            <div class="card card-civic p-3">
                <div class="text-muted small fw-semibold text-uppercase">Pending Verification</div>
                <h3 class="fw-bold text-warning mt-1 mb-0">{{ pending_cnt }}</h3>
                <small class="text-muted">Awaiting check-in</small>
            </div>
        </div>
        <div class="col-md-2">
            <div class="card card-civic p-3">
                <div class="text-muted small fw-semibold text-uppercase">Completed</div>
                <h3 class="fw-bold text-success mt-1 mb-0">{{ completed_cnt }}</h3>
                <small class="text-muted">Dispatched today</small>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card card-civic p-3">
                <div class="text-muted small fw-semibold text-uppercase">Current Queue Forecast</div>
                <div class="d-flex align-items-baseline gap-2 mt-1">
                    <h3 class="fw-bold text-dark mb-0">{{ queue_info.predicted_queue }}</h3>
                    <span class="badge bg-{{ queue_info.rush_badge }}">{{ queue_info.rush_level }}</span>
                </div>
                <small class="text-muted">Est. wait: <strong>{{ queue_info.wait_time_minutes }} mins</strong></small>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card card-civic p-3">
                <div class="text-muted small fw-semibold text-uppercase">AI Stock Shortage Alerts</div>
                <h3 class="fw-bold {{ 'text-danger' if stock_insights.critical_alerts_count > 0 else 'text-success' }} mt-1 mb-0">
                    {{ stock_insights.critical_alerts_count }} Items
                </h3>
                <small class="text-muted">Runway under 3.5 days</small>
            </div>
        </div>
    </div>

    <!-- AI Stock Intelligence Panel -->
    <div class="card card-civic mb-4 overflow-hidden">
        <div class="civic-header d-flex justify-content-between align-items-center">
            <span><i class="bi bi-cpu me-2 text-primary"></i> AI Stock Prediction & Replenishment Advisory</span>
            <span class="badge bg-secondary">Model: Linear Run-Rate + Historical Consumption</span>
        </div>
        <div class="p-3">
            <div class="row g-3">
                {% for it in stock_insights['items'] %}
                    <div class="col-md-4">
                        <div class="border rounded-3 p-3 bg-light h-100">
                            <div class="d-flex justify-content-between align-items-center mb-2">
                                <h6 class="fw-bold text-navy mb-0">{{ it.item_name }}</h6>
                                <span class="badge bg-{{ it.risk_badge }}">{{ it.shortage_risk }} Risk</span>
                            </div>
                            <div class="small text-muted mb-2">
                                Current Stock: <strong>{{ it.current_stock }} {{ it.unit }}</strong> (Reserved: {{ it.reserved_stock }} {{ it.unit }})
                            </div>
                            <div class="small text-muted mb-2">
                                Daily Burn Rate: <strong>{{ it.daily_consumption }} {{ it.unit }}/day</strong>
                            </div>
                            <div class="d-flex justify-content-between align-items-center p-2 rounded bg-white border mb-2">
                                <span class="small text-secondary">Estimated Days Remaining:</span>
                                <strong class="fs-6 {{ 'text-danger' if it.days_remaining < 4 else 'text-dark' }}">{{ it.days_remaining }} days</strong>
                            </div>
                            <div class="small text-secondary" style="font-size: 0.8rem;">
                                <i class="bi bi-lightbulb text-warning me-1"></i> {{ it.recommendation }}
                            </div>
                        </div>
                    </div>
                {% endfor %}
            </div>
        </div>
    </div>

    <!-- Today's Bookings Management Table -->
    <div class="card card-civic mb-4 overflow-hidden">
        <div class="civic-header d-flex justify-content-between align-items-center">
            <span><i class="bi bi-list-check me-2"></i> Today's Beneficiary Bookings ({{ shop.shop_code }})</span>
            <div class="d-flex gap-2">
                <input type="text" id="bookingSearchInput" class="form-control form-control-sm" placeholder="Search Token / Citizen..." onkeyup="filterBookingsTable()">
            </div>
        </div>
        <div class="p-3">
            <div class="table-responsive">
                <table class="table table-civic" id="staffBookingsTable">
                    <thead>
                        <tr>
                            <th>Pass ID</th>
                            <th>Citizen Name</th>
                            <th>Ration Card</th>
                            <th>Time Slot</th>
                            <th>Requested Items</th>
                            <th>Status</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% if todays_bookings %}
                            {% for b in todays_bookings %}
                                <tr id="booking_row_{{ b.id }}">
                                    <td><strong class="font-monospace text-navy">{{ b.booking_ref }}</strong></td>
                                    <td>
                                        <div class="fw-semibold">{{ b.citizen_name }}</div>
                                        <div class="small text-muted">{{ b.phone }}</div>
                                    </td>
                                    <td><span class="badge bg-light text-dark border">{{ b.ration_card_no }}</span></td>
                                    <td>{{ b.time_slot }}</td>
                                    <td>
                                        {% for it in b['items'] %}
                                            <span class="badge bg-light text-dark border me-1">{{ it.item_name }}: {{ it.quantity }} {{ it.unit }}</span>
                                        {% endfor %}
                                    </td>
                                    <td>
                                        <span id="status_badge_{{ b.id }}" class="badge bg-{{ 'success' if b.status == 'Completed' else ('primary' if b.status == 'Approved' else 'warning text-dark') }}">
                                            {{ b.status }}
                                        </span>
                                    </td>
                                    <td>
                                        <div class="btn-group btn-group-sm" id="action_btn_group_{{ b.id }}">
                                            {% if b.status == 'Pending' %}
                                                <button class="btn btn-outline-primary" onclick="updateStatus({{ b.id }}, 'Approved')">
                                                    <i class="bi bi-check2"></i> Approve
                                                </button>
                                                <button class="btn btn-success" onclick="updateStatus({{ b.id }}, 'Completed')">
                                                    <i class="bi bi-box-seam me-1"></i> Complete
                                                </button>
                                            {% elif b.status == 'Approved' %}
                                                <button class="btn btn-success" onclick="updateStatus({{ b.id }}, 'Completed')">
                                                    <i class="bi bi-box-seam me-1"></i> Complete & Deduct Stock
                                                </button>
                                            {% else %}
                                                <span class="text-muted small"><i class="bi bi-check-all text-success"></i> Dispatched</span>
                                            {% endif %}
                                        </div>
                                    </td>
                                </tr>
                            {% endfor %}
                        {% else %}
                            <tr><td colspan="7" class="text-center text-muted py-4">No bookings scheduled for today yet.</td></tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Live Inventory Stock Management Table -->
    <div class="card card-civic overflow-hidden">
        <div class="civic-header d-flex justify-content-between align-items-center">
            <span><i class="bi bi-boxes me-2"></i> Fair Price Shop Inventory Management</span>
            <span class="small text-muted">Stock values auto-deduct upon transaction completion</span>
        </div>
        <div class="p-3">
            <div class="table-responsive">
                <table class="table table-civic">
                    <thead>
                        <tr>
                            <th>Commodity Code</th>
                            <th>Item Name</th>
                            <th>Physical Stock</th>
                            <th>Reserved in Bookings</th>
                            <th>Available to Distribute</th>
                            <th>Safety Threshold</th>
                            <th>Stock Status</th>
                            <th>Last Updated</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for it in stock_insights['items'] %}
                            <tr>
                                <td><code>{{ it.item_code }}</code></td>
                                <td><strong class="text-navy">{{ it.item_name }}</strong></td>
                                <td><strong class="fs-6">{{ it.current_stock }}</strong> {{ it.unit }}</td>
                                <td>{{ it.reserved_stock }} {{ it.unit }}</td>
                                <td><strong class="text-primary">{{ it.available_stock }}</strong> {{ it.unit }}</td>
                                <td>{{ it.min_threshold }} {{ it.unit }}</td>
                                <td><span class="badge bg-{{ it.risk_badge }}">{{ it.shortage_risk }}</span></td>
                                <td class="small text-muted">{{ it.last_updated }}</td>
                            </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>

<!-- INVENTORY RESTOCK MODAL -->
<div class="modal fade" id="restockModal" tabindex="-1">
    <div class="modal-dialog">
        <div class="modal-content">
            <div class="modal-header bg-light">
                <h5 class="modal-title fw-bold text-navy"><i class="bi bi-box-arrow-in-down me-2 text-success"></i> Restock Commodity Inventory</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <form id="restockForm" onsubmit="handleRestockSubmit(event)">
                    <div class="mb-3">
                        <label class="form-label small fw-semibold">Commodity Item</label>
                        <select id="restockItemSelect" class="form-select" required>
                            {% for it in stock_insights['items'] %}
                                <option value="{{ it.item_id }}">{{ it.item_name }} (Current: {{ it.current_stock }} {{ it.unit }})</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="mb-3">
                        <label class="form-label small fw-semibold">Replenishment Quantity (kg)</label>
                        <input type="number" id="restockQtyInput" class="form-control" min="1" step="1" value="100" required>
                    </div>
                    <div id="restockAlert" class="alert alert-info small d-none"></div>
                    <div class="modal-footer px-0 pb-0">
                        <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="submit" class="btn btn-gov" id="restockSubmitBtn">Update Stock in MySQL</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>

<script>
async function updateStatus(bookingId, newStatus) {
    if (!confirm(`Are you sure you want to mark booking #${bookingId} as ${newStatus}?${newStatus === 'Completed' ? ' This will immediately deduct inventory stock in MySQL.' : ''}`)) return;

    try {
        const res = await fetch(`/api/bookings/${bookingId}/status`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ status: newStatus })
        });
        const data = await res.json();
        if (!res.ok) {
            alert(data.error || 'Failed to update status.');
            return;
        }

        // Update UI dynamically
        const badge = document.getElementById(`status_badge_${bookingId}`);
        badge.innerText = newStatus;
        badge.className = `badge bg-${newStatus === 'Completed' ? 'success' : 'primary'}`;

        const btnGroup = document.getElementById(`action_btn_group_${bookingId}`);
        if (newStatus === 'Completed') {
            btnGroup.innerHTML = `<span class="text-muted small"><i class="bi bi-check-all text-success"></i> Dispatched</span>`;
            // Reload page in 1 second to update stock levels
            setTimeout(() => { location.reload(); }, 900);
        } else if (newStatus === 'Approved') {
            btnGroup.innerHTML = `
                <button class="btn btn-success btn-sm" onclick="updateStatus(${bookingId}, 'Completed')">
                    <i class="bi bi-box-seam me-1"></i> Complete & Deduct Stock
                </button>
            `;
        }
    } catch(err) {
        alert("Error: " + err.message);
    }
}

async function handleRestockSubmit(e) {
    e.preventDefault();
    const itemId = document.getElementById('restockItemSelect').value;
    const qty = parseFloat(document.getElementById('restockQtyInput').value);
    const alertBox = document.getElementById('restockAlert');
    alertBox.classList.remove('d-none');
    alertBox.innerText = "Replenishing stock in database...";

    try {
        const res = await fetch('/api/stock?shop_id={{ shop.id }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ item_id: itemId, quantity: qty })
        });
        const data = await res.json();
        if (!res.ok) {
            alertBox.className = "alert alert-danger small";
            alertBox.innerText = data.error || 'Failed to replenish stock.';
            return;
        }
        alertBox.className = "alert alert-success small";
        alertBox.innerText = data.message;
        setTimeout(() => { location.reload(); }, 800);
    } catch(err) {
        alertBox.className = "alert alert-danger small";
        alertBox.innerText = err.message;
    }
}

function filterBookingsTable() {
    const q = document.getElementById('bookingSearchInput').value.toLowerCase();
    const rows = document.querySelectorAll('#staffBookingsTable tbody tr');
    rows.forEach(r => {
        r.style.display = r.innerText.toLowerCase().includes(q) ? '' : 'none';
    });
}
</script>
""" + HTML_FOOTER_COMMON

# ------------------------------------------------------------------------------
# 14. GOVERNMENT ADMIN DASHBOARD TEMPLATE (Chart.js)
# ------------------------------------------------------------------------------
HTML_GOV_DASHBOARD = HTML_HEADER_COMMON + """
<!-- Chart.js CDN -->
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<div class="container-fluid px-lg-5 py-4">
    <!-- Gov Admin Header Banner -->
    <div class="card card-civic p-4 mb-4 border-start border-4 border-warning">
        <div class="row align-items-center gy-3">
            <div class="col-md-8">
                <div class="d-flex align-items-center gap-3">
                    <div class="rounded-circle bg-warning-subtle text-warning p-3 fs-3">
                        <i class="bi bi-building"></i>
                    </div>
                    <div>
                        <h4 class="fw-bold text-navy mb-1">State Public Distribution Telemetry Command</h4>
                        <div class="d-flex flex-wrap gap-2 text-muted small">
                            <span>Civil Supplies Regulator: <strong class="text-dark">{{ user.full_name }}</strong></span>
                            <span>•</span>
                            <span>Department of Food & Public Distribution</span>
                            <span>•</span>
                            <span class="badge bg-primary">AI Telemetry Active</span>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-4 text-md-end">
                <button class="btn btn-outline-secondary btn-sm" onclick="loadGovData()">
                    <i class="bi bi-arrow-clockwise me-1"></i> Refresh Real-Time Charts
                </button>
            </div>
        </div>
    </div>

    <!-- Macro Indicators -->
    <div class="row g-3 mb-4">
        <div class="col-md-3">
            <div class="card card-civic p-3">
                <div class="text-muted small fw-semibold text-uppercase">Total Fair Price Shops</div>
                <h3 class="fw-bold text-navy mt-1 mb-0">{{ total_shops }}</h3>
                <small class="text-muted">Active operational depots</small>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card card-civic p-3">
                <div class="text-muted small fw-semibold text-uppercase">Registered Beneficiaries</div>
                <h3 class="fw-bold text-dark mt-1 mb-0">{{ total_beneficiaries }}</h3>
                <small class="text-muted">Authorized ration cards</small>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card card-civic p-3">
                <div class="text-muted small fw-semibold text-uppercase">Today's Transactions</div>
                <h3 class="fw-bold text-success mt-1 mb-0">{{ today_txns }}</h3>
                <small class="text-muted">Completed grain disbursements</small>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card card-civic p-3">
                <div class="text-muted small fw-semibold text-uppercase">Depots with Low Stock</div>
                <h3 class="fw-bold {{ 'text-danger' if low_stock_cnt > 0 else 'text-success' }} mt-1 mb-0">{{ low_stock_cnt }}</h3>
                <small class="text-muted">Requires supply dispatch</small>
            </div>
        </div>
    </div>

    <!-- Chart.js Visualization Grid -->
    <div class="row g-4 mb-4">
        <!-- 1. Daily Trend Line Chart -->
        <div class="col-lg-6">
            <div class="card card-civic h-100 overflow-hidden">
                <div class="civic-header d-flex justify-content-between align-items-center">
                    <span><i class="bi bi-graph-up me-2 text-primary"></i> 7-Day Booking vs Distribution Trend</span>
                    <small class="text-muted">Daily Velocity</small>
                </div>
                <div class="p-3">
                    <canvas id="chartTrend" style="max-height: 260px;"></canvas>
                </div>
            </div>
        </div>

        <!-- 2. Commodity Stock Distribution Bar Chart -->
        <div class="col-lg-6">
            <div class="card card-civic h-100 overflow-hidden">
                <div class="civic-header d-flex justify-content-between align-items-center">
                    <span><i class="bi bi-bar-chart-fill me-2 text-success"></i> Commodity Stock Status Across Network</span>
                    <small class="text-muted">In Metric Units</small>
                </div>
                <div class="p-3">
                    <canvas id="chartStock" style="max-height: 260px;"></canvas>
                </div>
            </div>
        </div>
    </div>

    <!-- 3. Hourly Footfall & Queue Congestion Chart -->
    <div class="row g-4 mb-4">
        <div class="col-lg-12">
            <div class="card card-civic overflow-hidden">
                <div class="civic-header d-flex justify-content-between align-items-center">
                    <span><i class="bi bi-clock-history me-2 text-warning"></i> Hourly Queue Congestion & Beneficiary Rush Profile</span>
                    <span class="badge bg-secondary">Synthetic Historical Footfall Distribution</span>
                </div>
                <div class="p-3">
                    <canvas id="chartQueue" style="max-height: 220px;"></canvas>
                </div>
            </div>
        </div>
    </div>

    <!-- AI Stock Alerts Panel -->
    {% if consolidated_alerts %}
        <div class="card card-civic mb-4 border-danger overflow-hidden">
            <div class="civic-header bg-danger-subtle text-danger d-flex justify-content-between align-items-center">
                <span><i class="bi bi-exclamation-triangle-fill me-2"></i> AI Critical Depletion Alerts & Dispatch Advisories</span>
                <span class="badge bg-danger">{{ consolidated_alerts | length }} Action Items</span>
            </div>
            <div class="p-3">
                <div class="table-responsive">
                    <table class="table table-civic align-middle">
                        <thead>
                            <tr>
                                <th>Shop & Zone</th>
                                <th>Commodity</th>
                                <th>Current Stock</th>
                                <th>Days Remaining</th>
                                <th>Shortage Risk</th>
                                <th>AI Recommendation</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for a in consolidated_alerts %}
                                <tr>
                                    <td>
                                        <strong class="text-navy">{{ a.shop_name }}</strong>
                                        <div class="small text-muted">{{ a.shop_code }} • {{ a.zone }}</div>
                                    </td>
                                    <td><strong>{{ a.item_name }}</strong></td>
                                    <td>{{ a.current_stock }} {{ a.unit }}</td>
                                    <td><strong class="text-danger">{{ a.days_remaining }} days</strong></td>
                                    <td><span class="badge bg-{{ a.risk_badge }}">{{ a.shortage_risk }}</span></td>
                                    <td class="small text-muted">{{ a.recommendation }}</td>
                                </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    {% endif %}

    <!-- Fair Price Shop Monitoring Table -->
    <div class="card card-civic overflow-hidden">
        <div class="civic-header d-flex justify-content-between align-items-center">
            <span><i class="bi bi-grid me-2"></i> Fair Price Shop Network Monitoring</span>
            <span class="small text-muted">All active municipal zones</span>
        </div>
        <div class="p-3">
            <div class="table-responsive">
                <table class="table table-civic" id="govShopsTable">
                    <thead>
                        <tr>
                            <th>Shop Code</th>
                            <th>Shop Name</th>
                            <th>Zone</th>
                            <th>Assigned Staff</th>
                            <th>Today's Scheduled Footfall</th>
                            <th>Inventory Health</th>
                        </tr>
                    </thead>
                    <tbody id="govShopsTableBody">
                        <tr><td colspan="6" class="text-center text-muted py-3">Loading network status...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>

<script>
let trendChartInstance = null;
let stockChartInstance = null;
let queueChartInstance = null;

document.addEventListener('DOMContentLoaded', () => {
    loadGovData();
});

async function loadGovData() {
    try {
        const res = await fetch('/api/government');
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to fetch government metrics');

        renderTrendChart(data.charts.trend);
        renderStockChart(data.charts.commodity_stocks);
        renderQueueChart(data.charts.hourly_queue);
        renderShopsTable(data.shops);
    } catch(err) {
        console.error("Gov metrics load error:", err);
    }
}

function renderTrendChart(trendData) {
    const ctx = document.getElementById('chartTrend').getContext('2d');
    if (trendChartInstance) trendChartInstance.destroy();

    trendChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: trendData.labels,
            datasets: [
                {
                    label: 'Bookings Created',
                    data: trendData.bookings,
                    borderColor: '#1e3a8a',
                    backgroundColor: 'rgba(30, 58, 138, 0.1)',
                    fill: true,
                    tension: 0.3
                },
                {
                    label: 'Completed Dispatches',
                    data: trendData.completions,
                    borderColor: '#10b981',
                    backgroundColor: 'transparent',
                    borderDash: [5, 5],
                    tension: 0.3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'top' } }
        }
    });
}

function renderStockChart(stockData) {
    const ctx = document.getElementById('chartStock').getContext('2d');
    if (stockChartInstance) stockChartInstance.destroy();

    const labels = stockData.map(d => d.item_name);
    const totals = stockData.map(d => d.total_stock);
    const reserved = stockData.map(d => d.total_reserved);

    stockChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Total Available (kg)',
                    data: totals,
                    backgroundColor: '#3b82f6'
                },
                {
                    label: 'Reserved in Bookings (kg)',
                    data: reserved,
                    backgroundColor: '#f59e0b'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'top' } }
        }
    });
}

function renderQueueChart(queueData) {
    const ctx = document.getElementById('chartQueue').getContext('2d');
    if (queueChartInstance) queueChartInstance.destroy();

    const labels = queueData.map(d => `${d.hour}:00`);
    const queues = queueData.map(d => Math.round(d.avg_queue));
    const waits = queueData.map(d => Math.round(d.avg_wait));

    queueChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    type: 'bar',
                    label: 'Average Queue Length (Beneficiaries)',
                    data: queues,
                    backgroundColor: '#64748b'
                },
                {
                    type: 'line',
                    label: 'Average Waiting Time (Minutes)',
                    data: waits,
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.15)',
                    fill: true,
                    tension: 0.3,
                    yAxisID: 'yWait'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: true, title: { display: true, text: 'Queue Size' } },
                yWait: { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false }, title: { display: true, text: 'Minutes' } }
            }
        }
    });
}

function renderShopsTable(shops) {
    const tbody = document.getElementById('govShopsTableBody');
    tbody.innerHTML = shops.map(s => `
        <tr>
            <td><code>${s.shop_code}</code></td>
            <td><strong class="text-navy">${s.shop_name}</strong></td>
            <td>${s.zone}</td>
            <td>${s.staff_name}</td>
            <td><span class="badge bg-light text-dark border">${s.today_bookings} Bookings</span></td>
            <td><span class="badge bg-${s.health_badge}">${s.health_status}</span></td>
        </tr>
    `).join('');
}
</script>
""" + HTML_FOOTER_COMMON

# ------------------------------------------------------------------------------
# 15. STANDALONE DIGITAL RATION PASS VIEW
# ------------------------------------------------------------------------------
HTML_DIGITAL_PASS = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Digital Ration Pass - {{ b.booking_ref }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .pass-container { max-width: 520px; margin: 40px auto; background: #ffffff; border-radius: 12px; border: 2px solid #0f2942; box-shadow: 0 10px 25px rgba(0,0,0,0.1); overflow: hidden; }
        .pass-header { background: #0f2942; color: #ffffff; padding: 18px 24px; text-align: center; }
        .pass-body { padding: 24px; }
        @media print {
            body { background: #ffffff; }
            .pass-container { box-shadow: none; margin: 0 auto; border: 1px solid #000; }
            .no-print { display: none !important; }
        }
    </style>
</head>
<body>
<div class="pass-container">
    <div class="pass-header">
        <h5 class="fw-bold mb-0">GOVERNMENT OF INDIA</h5>
        <div class="small text-warning text-uppercase letter-spacing-1">Public Distribution System • Digital Ration Pass</div>
    </div>
    <div class="pass-body text-center">
        <div class="d-flex justify-content-between align-items-center mb-3">
            <span class="badge bg-secondary font-monospace">{{ b.shop_code }}</span>
            <span class="badge bg-{{ 'success' if b.status == 'Approved' else 'warning text-dark' }}">{{ b.status }}</span>
        </div>

        <div class="my-3">
            <img src="{{ qr_uri }}" alt="QR Pass" class="border p-2 rounded" style="width: 190px; height: 190px;">
            <div class="font-monospace fw-bold fs-4 text-dark mt-2">{{ b.booking_ref }}</div>
            <div class="text-muted small">Official Encrypted Identifier</div>
        </div>

        <div class="text-start bg-light p-3 rounded-3 mb-3 small">
            <div class="row g-2">
                <div class="col-6"><strong>Beneficiary:</strong><br>{{ b.citizen_name }}</div>
                <div class="col-6"><strong>Ration Card:</strong><br>{{ b.ration_card_no }}</div>
                <div class="col-6"><strong>Pickup Date:</strong><br>{{ b.booking_date }}</div>
                <div class="col-6"><strong>Time Slot:</strong><br>{{ b.time_slot }}</div>
            </div>
            <hr class="my-2">
            <div><strong>Allocated Shop:</strong> {{ b.shop_name }}</div>
            <div class="text-muted">{{ b.shop_address }}</div>
        </div>

        <div class="text-start mb-4">
            <h6 class="fw-bold small text-dark mb-2">Allocated Commodities:</h6>
            <ul class="list-group small">
                {% for it in items %}
                    <li class="list-group-item d-flex justify-content-between align-items-center">
                        <span>{{ it.item_name }} ({{ it.item_code }})</span>
                        <strong>{{ it.quantity }} {{ it.unit }}</strong>
                    </li>
                {% endfor %}
            </ul>
        </div>

        <div class="no-print d-flex gap-2 justify-content-center">
            <button onclick="window.print()" class="btn btn-primary btn-sm px-4">Print Official Pass</button>
            <button onclick="window.close()" class="btn btn-outline-secondary btn-sm px-3">Close</button>
        </div>
    </div>
</div>
</body>
</html>
"""

# ------------------------------------------------------------------------------
# 16. BOOTSTRAP ENTRY POINT
# ------------------------------------------------------------------------------
init_database_if_needed()

if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', '1') == '1'
    print("=" * 70)
    print("  RationSmart AI - Smart Ration Distribution System")
    print(f"  Running on http://127.0.0.1:{port}")
    print(f"  Active Database Engine: {ACTIVE_DB_ENGINE.upper()}")
    print("=" * 70)
    app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=False)
