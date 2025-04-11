from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_mysqldb import MySQL
from flask_cors import CORS
import hashlib
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

# MySQL Configuration (Update with your credentials)
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'rescue_admi'
app.config['MYSQL_PASSWORD'] = 'SecurePass1234!'
app.config['MYSQL_DB'] = 'rescue_db'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
app.config['MYSQL_CONNECT_TIMEOUT'] = 10

mysql = MySQL(app)

# Database Connection Test
try:
    with app.app_context():
        cur = mysql.connection.cursor()
        cur.execute("SELECT 1")
        print("✅ Database connection successful!")
        cur.close()
except Exception as e:
    print(f"❌ Database connection failed: {str(e)}")
    print("Troubleshooting steps:")
    print("1. Verify MySQL service is running")
    print("2. Check username/password")
    print("3. Confirm database exists")
    print("4. Check firewall settings")
    exit(1)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Temporary debug route (remove in production)
@app.route('/debug/emergencies')
def debug_emergencies():
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM emergencies")
        emergencies = cur.fetchall()
        return jsonify({
            'count': len(emergencies),
            'emergencies': emergencies
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = hash_password(request.form['password'])
        
        try:
            cur = mysql.connection.cursor()
            cur.execute("SELECT * FROM agencies WHERE email = %s", (email,))
            agency = cur.fetchone()
            
            if agency and agency['password'] == password:
                session['agency_id'] = agency['id']
                session['role'] = agency['role']
                return redirect(url_for('dashboard'))
            
            return render_template('login.html', error="Invalid credentials")
        except Exception as e:
            return render_template('login.html', error="Database error")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form
        try:
            cur = mysql.connection.cursor()
            
            cur.execute("SELECT email FROM agencies WHERE email = %s", (data['email'],))
            if cur.fetchone():
                return render_template('register.html', error="Email already registered")
            
            cur.execute("""
                INSERT INTO agencies (name, email, password, expertise)
                VALUES (%s, %s, %s, %s)
            """, (
                data['name'],
                data['email'],
                hash_password(data['password']),
                data['expertise']
            ))
            mysql.connection.commit()
            
            cur.execute("SELECT id FROM agencies WHERE email = %s", (data['email'],))
            new_agency = cur.fetchone()
            
            session['agency_id'] = new_agency['id']
            session['role'] = 'agency'
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            mysql.connection.rollback()
            return render_template('register.html', error=str(e))
    return render_template('register.html')
@app.route('/emergency_map')
def emergency_map():
    if 'agency_id' not in session:
        return redirect(url_for('login'))
    return render_template('emergency_map.html')

@app.route('/api/report_emergency', methods=['POST'])
def report_emergency():
    data = request.get_json()
    lat = data.get('lat')
    lng = data.get('lng')
    description = data.get('description')
    tag = data.get('tag')  # 👈 must match front-end 'tag'

    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO emergencies (latitude, longitude, description, tag, status, reported_by)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (lat, lng, description, tag, 'pending', 'public'))
        mysql.connection.commit()
        return jsonify({'message': 'Emergency reported successfully'}), 200
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Failed to report emergency'}), 500




@app.route('/client')
def client_portal():
    return render_template('client.html')

@app.route('/api/update_location', methods=['POST'])
def update_location():
    if 'agency_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    data = request.json
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            UPDATE agencies 
            SET latitude = %s, longitude = %s, last_updated = %s 
            WHERE id = %s
        """, (data['lat'], data['lng'], datetime.now(), session['agency_id']))
        mysql.connection.commit()
        
        # Store in session for distance calculations
        session['latitude'] = data['lat']
        session['longitude'] = data['lng']
        
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"[API ERROR] Location Update: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/emergencies')
def get_emergencies():
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT *, 
                CASE severity
                    WHEN 'high' THEN '🔴 High'
                    WHEN 'medium' THEN '🟡 Medium' 
                    ELSE '🟢 Low'
                END as severity_display
            FROM emergencies
            WHERE status = 'pending'
            ORDER BY created_at DESC
        """)
        results = cur.fetchall()
        print(f"[DEBUG] Found {len(results)} emergencies")
        return jsonify(results)
    except Exception as e:
        print(f"[API ERROR] Emergencies: {str(e)}")
        return jsonify({'error': 'Database error'}), 500
# No filtering by severity or role anymore
@app.route('/api/emergency_details')
def get_all_emergency_details():
    if 'agency_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        lat = session.get('latitude', 20.5937)
        lng = session.get('longitude', 78.9629)

        cur = mysql.connection.cursor()

        query = """
            SELECT *, 
                CAST(latitude AS DECIMAL(10,8)) AS latitude,
                CAST(longitude AS DECIMAL(11,8)) AS longitude,
                ROUND(6371000 * acos(
                    cos(radians(%s)) * cos(radians(latitude)) * 
                    cos(radians(longitude) - radians(%s)) + 
                    sin(radians(%s)) * sin(radians(latitude))
                )) AS distance
            FROM emergencies
            WHERE status = 'pending'
            ORDER BY created_at DESC
        """

        cur.execute(query, (lat, lng, lat))
        emergencies = cur.fetchall()
        return jsonify(emergencies)

    except Exception as e:
        print(f"[ERROR] Emergency details: {str(e)}")
        return jsonify({'error': str(e)}), 500



@app.route('/dashboard')
def dashboard():
    if 'agency_id' not in session:
        return redirect(url_for('login'))

    role = session.get('role', 'agency')

    if role == 'ndrf':
        return redirect(url_for('ndrf_dashboard'))
    else:
        return render_template('dashboard.html')


@app.route('/api/agencies')
def get_agencies():
    if 'agency_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, name, latitude, longitude, expertise FROM agencies")
        return jsonify(cur.fetchall())
    except Exception as e:
        print(f"[API ERROR] Agencies: {str(e)}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/api/delete_emergencies', methods=['POST'])
def delete_all_emergencies():
    if 'agency_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        cur = mysql.connection.cursor()
        cur.execute("DELETE FROM emergencies")
        mysql.connection.commit()
        return jsonify({'status': 'All emergencies deleted'})
    except Exception as e:
        mysql.connection.rollback()
        print(f"[DELETE ERROR] Failed to delete emergencies: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/ndrf_dashboard')
def ndrf_dashboard():
    if 'agency_id' not in session or session.get('role') != 'ndrf':
        return redirect(url_for('login'))
    return render_template('ndrf_dashboard.html')


if __name__ == '__main__':
    app.run(debug=True)