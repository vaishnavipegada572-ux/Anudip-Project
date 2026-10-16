import os
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from mysql.connector import Error

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'local-development-only-change-before-deploy')
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', '0') == '1')

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'campus_asset_booking'),
    'port': int(os.getenv('DB_PORT', '3306')),
}


def connect_db(with_database=True):
    config = DB_CONFIG.copy()
    if not with_database:
        config.pop('database', None)
    return mysql.connector.connect(**config)


def init_db():
    # The database itself must already exist on hosted providers such as TiDB.
    # This function creates tables and starter data inside DB_NAME.
    conn = connect_db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        email VARCHAR(150) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        role ENUM('student','admin') NOT NULL DEFAULT 'student',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS equipment (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(150) NOT NULL,
        category VARCHAR(100) NOT NULL,
        asset_code VARCHAR(60) NOT NULL UNIQUE,
        location VARCHAR(150) NOT NULL,
        value_inr DECIMAL(12,2) NOT NULL DEFAULT 0,
        status ENUM('Available','Maintenance','Retired') NOT NULL DEFAULT 'Available',
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS bookings (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        equipment_id INT NOT NULL,
        purpose VARCHAR(255) NOT NULL,
        booking_date DATE NOT NULL,
        start_time TIME NOT NULL,
        end_time TIME NOT NULL,
        status ENUM('Pending','Approved','Rejected','Cancelled') NOT NULL DEFAULT 'Pending',
        admin_note VARCHAR(255),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_booking_user FOREIGN KEY (user_id) REFERENCES users(id),
        CONSTRAINT fk_booking_equipment FOREIGN KEY (equipment_id) REFERENCES equipment(id)
    )''')
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@college.edu').strip().lower()
    admin_password = os.getenv('ADMIN_PASSWORD', 'Admin@123')
    cur.execute('SELECT id FROM users WHERE email=%s', (admin_email,))
    if not cur.fetchone():
        cur.execute('INSERT INTO users (name,email,password_hash,role) VALUES (%s,%s,%s,%s)',
                    ('Lab Administrator', admin_email, generate_password_hash(admin_password), 'admin'))
    cur.execute('SELECT COUNT(*) FROM equipment')
    if cur.fetchone()[0] == 0:
        starter = [
            ('Digital Oscilloscope', 'Electronics', 'ELEC-001', 'Electronics Lab', 85000, 'Available', 'Two-channel digital oscilloscope for circuit analysis.'),
            ('3D Printer', 'Mechanical', 'MECH-002', 'Innovation Lab', 125000, 'Available', 'FDM 3D printer; high-value asset requiring administrator approval.'),
            ('Thermal Camera', 'Research', 'RES-003', 'Research Lab', 175000, 'Available', 'Thermal imaging camera for approved laboratory projects.'),
            ('Arduino Starter Kit', 'Electronics', 'ELEC-004', 'IoT Lab', 4500, 'Available', 'Microcontroller kit with common sensors and cables.'),
            ('Laptop Workstation', 'Computing', 'COMP-005', 'Computer Lab 2', 72000, 'Available', 'Portable workstation for lab and project use.'),
        ]
        cur.executemany('INSERT INTO equipment (name,category,asset_code,location,value_inr,status,description) VALUES (%s,%s,%s,%s,%s,%s,%s)', starter)
    conn.commit()
    cur.close()
    conn.close()


def query_db(sql, params=(), fetch='all'):
    conn = connect_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    result = cur.fetchall() if fetch == 'all' else cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return result


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            flash('Please sign in to continue.', 'warning')
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            flash('Please sign in first.', 'warning')
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Administrator access is required for that action.', 'danger')
            return redirect(url_for('dashboard'))
        return fn(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_globals():
    return {'current_year': datetime.now().year}


@app.route('/')
def index():
    try:
        equipment = query_db("SELECT * FROM equipment WHERE status <> 'Retired' ORDER BY name")
        return render_template('index.html', equipment=equipment)
    except Error as exc:
        return render_template('setup_error.html', error=str(exc)), 500


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not name or not email or len(password) < 8:
            flash('Enter your name and email, and use a password with at least 8 characters.', 'danger')
            return render_template('register.html')
        try:
            query_db('INSERT INTO users (name,email,password_hash,role) VALUES (%s,%s,%s,%s)',
                     (name, email, generate_password_hash(password), 'student'))
            flash('Account created. You can now sign in.', 'success')
            return redirect(url_for('login'))
        except Error as exc:
            if getattr(exc, 'errno', None) == 1062:
                flash('That email is already registered.', 'danger')
            else:
                flash('Could not create your account. Check the database configuration.', 'danger')
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = query_db('SELECT * FROM users WHERE email=%s', (email,), fetch='one')
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']
            session['name'] = user['name']
            session['email'] = user['email']
            session['role'] = user['role']
            flash(f"Welcome, {user['name']}!", 'success')
            return redirect(url_for('admin_dashboard' if user['role'] == 'admin' else 'dashboard'))
        flash('Incorrect email or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been signed out.', 'info')
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    bookings = query_db('''SELECT b.*, e.name AS equipment_name, e.asset_code, e.location AS equipment_location
        FROM bookings b JOIN equipment e ON e.id=b.equipment_id WHERE b.user_id=%s ORDER BY b.created_at DESC''', (session['user_id'],))
    equipment = query_db("SELECT * FROM equipment WHERE status='Available' ORDER BY name")
    return render_template('dashboard.html', bookings=bookings, equipment=equipment)


@app.route('/book', methods=['POST'])
@login_required
def book():
    try:
        equipment_id = int(request.form.get('equipment_id', '0'))
        booking_date = request.form.get('booking_date', '')
        start_time = request.form.get('start_time', '')
        end_time = request.form.get('end_time', '')
        purpose = request.form.get('purpose', '').strip()
        if not all([equipment_id, booking_date, start_time, end_time, purpose]):
            flash('Please complete every booking field.', 'danger')
            return redirect(url_for('dashboard'))
        if start_time >= end_time:
            flash('End time must be later than start time.', 'danger')
            return redirect(url_for('dashboard'))
        if datetime.strptime(booking_date, '%Y-%m-%d').date() < datetime.now().date():
            flash('Choose today or a future date.', 'danger')
            return redirect(url_for('dashboard'))
        equipment = query_db('SELECT * FROM equipment WHERE id=%s AND status=%s', (equipment_id, 'Available'), fetch='one')
        if not equipment:
            flash('That asset is not currently available for booking.', 'danger')
            return redirect(url_for('dashboard'))
        # Prevent overlapping active bookings for the same asset and date.
        overlap = query_db('''SELECT id FROM bookings WHERE equipment_id=%s AND booking_date=%s
            AND status IN ('Pending','Approved') AND NOT (end_time <= %s OR start_time >= %s)''',
            (equipment_id, booking_date, start_time, end_time), fetch='one')
        if overlap:
            flash('This asset already has a pending or approved booking during that time.', 'danger')
            return redirect(url_for('dashboard'))
        status = 'Pending' if float(equipment['value_inr']) >= 50000 else 'Approved'
        query_db('''INSERT INTO bookings (user_id,equipment_id,purpose,booking_date,start_time,end_time,status)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''',
            (session['user_id'], equipment_id, purpose, booking_date, start_time, end_time, status))
        flash('Booking submitted for administrator approval.' if status == 'Pending' else 'Booking confirmed.', 'success')
    except (ValueError, Error):
        flash('Booking could not be saved. Check your details and database connection.', 'danger')
    return redirect(url_for('dashboard'))


@app.route('/cancel/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    booking = query_db('SELECT id,status FROM bookings WHERE id=%s AND user_id=%s', (booking_id, session['user_id']), fetch='one')
    if not booking:
        flash('Booking not found.', 'danger')
    elif booking['status'] not in ('Pending', 'Approved'):
        flash('This booking can no longer be cancelled.', 'warning')
    else:
        query_db("UPDATE bookings SET status='Cancelled' WHERE id=%s", (booking_id,))
        flash('Booking cancelled.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    bookings = query_db('''SELECT b.*, u.name AS student_name, u.email AS student_email,
        e.name AS equipment_name, e.asset_code, e.value_inr, e.location AS equipment_location
        FROM bookings b JOIN users u ON u.id=b.user_id JOIN equipment e ON e.id=b.equipment_id
        ORDER BY CASE b.status WHEN 'Pending' THEN 0 ELSE 1 END, b.created_at DESC''')
    equipment = query_db('SELECT * FROM equipment ORDER BY created_at DESC')
    stats = query_db('''SELECT COUNT(*) AS total_bookings,
        SUM(status='Pending') AS pending_bookings,
        (SELECT COUNT(*) FROM equipment WHERE status='Available') AS available_assets,
        (SELECT COUNT(*) FROM users WHERE role='student') AS students FROM bookings''', fetch='one')
    return render_template('admin.html', bookings=bookings, equipment=equipment, stats=stats)


@app.route('/admin/booking/<int:booking_id>/<action>', methods=['POST'])
@admin_required
def update_booking(booking_id, action):
    if action not in ('approve', 'reject'):
        flash('Invalid booking action.', 'danger')
        return redirect(url_for('admin_dashboard'))
    status = 'Approved' if action == 'approve' else 'Rejected'
    booking = query_db('SELECT id,status FROM bookings WHERE id=%s', (booking_id,), fetch='one')
    if not booking or booking['status'] != 'Pending':
        flash('Only pending bookings can be reviewed.', 'warning')
    else:
        query_db('UPDATE bookings SET status=%s, admin_note=%s WHERE id=%s',
                 (status, 'Reviewed by administrator', booking_id))
        flash(f'Booking #{booking_id} {status.lower()}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/equipment', methods=['POST'])
@admin_required
def add_equipment():
    name = request.form.get('name', '').strip()
    category = request.form.get('category', '').strip()
    asset_code = request.form.get('asset_code', '').strip().upper()
    location = request.form.get('location', '').strip()
    description = request.form.get('description', '').strip()
    try:
        value = float(request.form.get('value_inr', '0'))
        if not all([name, category, asset_code, location]) or value < 0:
            raise ValueError
        query_db('INSERT INTO equipment (name,category,asset_code,location,value_inr,description) VALUES (%s,%s,%s,%s,%s,%s)',
                 (name, category, asset_code, location, value, description))
        flash('Equipment added to the shared inventory.', 'success')
    except ValueError:
        flash('Enter valid equipment details and a non-negative value.', 'danger')
    except Error as exc:
        flash('Could not add equipment. Check that the asset code is unique.', 'danger')
    return redirect(url_for('admin_dashboard') + '#equipment')


@app.route('/admin/equipment/<int:equipment_id>/status', methods=['POST'])
@admin_required
def update_equipment_status(equipment_id):
    status = request.form.get('status')
    if status not in ('Available', 'Maintenance', 'Retired'):
        flash('Invalid asset status.', 'danger')
    else:
        query_db('UPDATE equipment SET status=%s WHERE id=%s', (status, equipment_id))
        flash('Equipment status updated.', 'success')
    return redirect(url_for('admin_dashboard') + '#equipment')


if __name__ == '__main__':
    try:
        init_db()
        print('Database and tables are ready.')
    except Error as exc:
        print('\nDATABASE SETUP ERROR:', exc)
        print('Check MySQL is running and DB_HOST, DB_USER, DB_PASSWORD are correct.\n')
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=os.getenv('FLASK_DEBUG', '0') == '1')
