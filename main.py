from flask import Flask, request, render_template, redirect, url_for, jsonify, session, flash
from markupsafe import escape
import math
import mysql.connector
from werkzeug.security import check_password_hash, generate_password_hash
import time
from threading import Thread
import atexit
import serial
from datetime import datetime, timedelta


now = datetime.now()  # ✅ Ini akan berhasil


app = Flask(__name__)
app.secret_key = "supersecretkey"  # Use a strong secret key in production


# Configure your MySQL connection
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'parking_system'
}
arduino = None
arduino_connected = False
def inject_now():
    return {'current_year': datetime.now().year}
def connect_arduino():
    global arduino, arduino_connected
    try:
        # Tutup koneksi yang mungkin masih terbuka
        if arduino is not None:
            try:
                arduino.close()
                time.sleep(1)  # Beri waktu untuk melepaskan port
            except:
                pass

        arduino = serial.Serial('/dev/tty.usbserial-10', 9600, timeout=1, write_timeout=1)
        arduino_connected = True
        print("Arduino terhubung!")
        # Beri waktu Arduino untuk reset setelah koneksi serial
        time.sleep(2)
    except Exception as e:
        arduino_connected = False
        print(f"PERINGATAN: Arduino tidak terhubung! Error: {str(e)}")

        # Coba solusi untuk error izin akses
        if "Access is denied" in str(e):
            print("Solusi yang disarankan:")
            print("1. Pastikan tidak ada program lain yang menggunakan port COM4")
            print("2. Coba cabut dan colok kembali Arduino")
            print("3. Periksa Device Manager untuk memastikan COM4 adalah port Arduino yang benar")
            print("4. Restart komputer jika masalah berlanjut")

# Fungsi untuk membersihkan koneksi Arduino saat program berakhir
def cleanup_arduino():
    global arduino, arduino_connected
    if arduino_connected and arduino:
        try:
            arduino.close()
            print("Koneksi Arduino ditutup dengan bersih")
        except:
            pass

# Register cleanup function to be called on exit
atexit.register(cleanup_arduino)

# Coba koneksi Arduino di awal
connect_arduino()


def open_gate_with_timer():
    global gate_status, arduino, arduino_connected

    if not arduino_connected:
        print("Mencoba untuk menghubungkan ke Arduino...")
        connect_arduino()

    if arduino_connected:
        try:
            # Kirim perintah ke Arduino untuk membuka gerbang
            arduino.write(b'OPEN\n')
            gate_status = "TERBUKA"
            print("Gerbang dibuka")

            # Tunggu 10 detik sebelum menutup kembali
            time.sleep(10)

            # Kirim perintah untuk menutup gerbang
            arduino.write(b'CLOSE\n')
            gate_status = "TERTUTUP"
            print("Gerbang ditutup")
        except Exception as e:
            gate_status = "TERTUTUP"
            print(f"Error saat mengirim perintah ke Arduino: {e}")
            arduino_connected = False



def get_connection():
    return mysql.connector.connect(**db_config)


@app.route('/arduino_status')
def arduino_status():
    global arduino_connected
    return "connected" if arduino_connected else "disconnected"

@app.route('/database_status')
def database_status():
    try:
        conn = get_connection()
        if conn is not None:
            conn.close()
            return "connected"
        return "disconnected"
    except:
        return "disconnected"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, password FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and password == user[1]:  # Pastikan hash password jika diperlukan
            session['user_id'] = user[0]
            session['username'] = username
            session['user_logged_in'] = True  # Menandakan bahwa pengguna sudah login
            return redirect(url_for('index'))  # Pastikan redirect ke halaman yang sesuai
        else:
            flash('Invalid username or password', 'danger')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    session.pop('user_logged_in', None)  # Menghapus status login
    return redirect(url_for('login'))





def get_data():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vehicle")
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return data


@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    rows = get_data()
    return render_template('index.html', rows=rows,active_page="vehicle")

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login', active_page="dashboard"))

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    # Ambil semua data dari tabel vehicles
    cursor.execute("SELECT * FROM vehicle")
    rows = cursor.fetchall()

    # Jumlah tiket unpaid
    cursor.execute("SELECT COUNT(*) AS total_unpaid FROM vehicle WHERE PaymentStat = 'Unpaid'")
    total_unpaid = cursor.fetchone()['total_unpaid']

    # Pendapatan: per jam, hari, minggu, bulan
    now = datetime.now()
    filters = {
        "hour": now - timedelta(hours=1),
        "day": now - timedelta(days=1),
        "week": now - timedelta(weeks=1),
        "month": now - timedelta(days=30),
    }

    income = {}
    for label, dt in filters.items():
        cursor.execute("SELECT SUM(Fee) AS total FROM vehicle WHERE PaymentStat = 'Paid' AND UpdatedAt >= %s", (dt,))
        result = cursor.fetchone()
        income[label] = float(result['total'] or 0)

    # Kendaraan masuk per hari selama 7 hari terakhir
    cursor.execute("""
        SELECT DATE(CreatedAt) AS day, COUNT(*) AS count
        FROM vehicle
        WHERE CreatedAt >= CURDATE() - INTERVAL 7 DAY
        GROUP BY day
    """)
    entries_per_day = cursor.fetchall()

    cursor.close()
    conn.close()

    # Format data for Chart.js
    days = [entry['day'] for entry in entries_per_day]
    counts = [entry['count'] for entry in entries_per_day]

    return render_template('dashboard.html',
                           rows=rows,
                           unpaid=total_unpaid,
                           income=income,
                           entries=entries_per_day,
                           days=days,
                           counts=counts)



@app.route('/open_gate')
def open_gate():
    Thread(target=open_gate_with_timer).start()
    return redirect(url_for('index'))




# @app.route('/')
# def index():
#     rows = get_data()
#     return render_template('index.html', rows=rows)


@app.route('/mark_paid/<int:id>')
def mark_paid(id):
    conn = get_connection()
    cursor = conn.cursor()

    # Update status pembayaran menjadi 'Paid'
    cursor.execute("UPDATE vehicle SET PaymentStat = 'Paid' WHERE id = %s", (id,))
    conn.commit()

    # Tutup koneksi
    cursor.close()
    conn.close()

    Thread(target=open_gate_with_timer).start()

    return redirect(url_for('index'))


@app.route("/ticket-scan")
def ticket_scan():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template("ticket_scan.html",active_page="ticket")

# @app.route("/ticket-scan")
# def ticket_scan():
#     return render_template("ticket_scan.html")

@app.route("/api/vehicle/by-image/<image_name>")
def get_vehicle_by_image(image_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, NoPol, Image, PaymentStat, CreatedAt, UpdatedAt
        FROM vehicle WHERE Image = %s
    """, (image_name,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row:
        created_at = row[4]
        now = datetime.now()
        duration_hours = max((now - created_at).total_seconds() / 3600, 0)
        fee = round(int(duration_hours * 3000), -3)

        record = {
            "id": row[0],
            "NoPol": row[1],
            "Image": row[2],
            "PaymentStat": row[3],
            "CreatedAt": row[4].strftime("%Y-%m-%d %H:%M:%S"),
            "UpdatedAt": row[5].strftime("%Y-%m-%d %H:%M:%S") if row[5] else None,
            "DurationHours": round(duration_hours, 2),
            "Fee": fee
        }
        return jsonify({"success": True, "record": record})
    else:
        return jsonify({"success": False, "message": "Vehicle not found"}), 404



@app.route("/api/vehicle/pay-by-image/<image_name>", methods=["POST"])
def mark_as_paid_by_image(image_name):
    conn = get_connection()
    cursor = conn.cursor()

    # Cari CreatedAt berdasarkan Image
    cursor.execute("SELECT id, CreatedAt FROM vehicle WHERE Image = %s", (image_name,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "message": "Vehicle not found"}), 404

    vehicle_id = row[0]
    created_at = row[1]
    updated_at = datetime.now()
    duration_hours = max((updated_at - created_at).total_seconds() / 3600, 0)
    fee = round(int(duration_hours * 3000), -3)
    updated_str = updated_at.strftime("%Y-%m-%d %H:%M:%S")

    # Update data
    cursor.execute("""
        UPDATE vehicle
        SET UpdatedAt = %s, PaymentStat = %s, Fee = %s
        WHERE id = %s
    """, (updated_str, "Paid", fee, vehicle_id))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({
        "success": True,
        "updatedAt": updated_str,
        "durationHours": round(duration_hours, 2),
        "fee": fee
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=3000)







# from flask import Flask, request, render_template, redirect, url_for, jsonify
# from markupsafe import escape
# from datetime import datetime
# import sqlite3
# import math

# app = Flask(__name__)

# def get_data():
#     conn = sqlite3.connect('data.db')
#     cursor = conn.cursor()
#     cursor.execute("SELECT * FROM vehicle")
#     data = cursor.fetchall()
#     conn.close()
#     return data

# @app.route('/')
# def index():
#     rows = get_data()
#     return render_template('index.html', rows=rows)

# if __name__ == '__main__':
#     app.run(debug=True)

# @app.route('/mark_paid/<int:id>')
# def mark_paid(id):
#     conn = sqlite3.connect('data.db')
#     cursor = conn.cursor()
#     cursor.execute("UPDATE vehicle SET PaymentStat = 'Paid' WHERE id = ?", (id,))
#     conn.commit()
#     conn.close()
#     return redirect(url_for('index'))

# @app.route("/ticket-scan")
# def ticket_scan():
#     return render_template("ticket_scan.html")

# @app.route("/api/vehicle/<id>")
# def get_vehicle(id):
#     conn = sqlite3.connect('data.db')
#     cursor = conn.cursor()
#     cursor.execute("SELECT id, NoPol, Image, PaymentStat, CreatedAt, UpdatedAt FROM vehicle WHERE id = ?", (id,))
#     row = cursor.fetchone()
#     conn.close()

#     if row:
#         record = {
#             "id": row[0],
#             "NoPol": row[1],
#             "Image": row[2],
#             "PaymentStat": row[3],
#             "CreatedAt": row[4],
#             "UpdatedAt": row[5]
#         }
#         return jsonify({"success": True, "record": record})
#     else:
#         return jsonify({"success": False, "message": "Vehicle not found"}), 404

# @app.route("/api/vehicle/pay/<id>", methods=["POST"])
# def mark_as_paid(id):
#     conn = sqlite3.connect('data.db')
#     cursor = conn.cursor()

#     # Get the created time
#     cursor.execute("SELECT CreatedAt FROM vehicle WHERE id = ?", (id,))
#     row = cursor.fetchone()
#     if not row:
#         conn.close()
#         return jsonify({"success": False, "message": "Vehicle not found"}), 404

#     created_at = datetime.fromisoformat(row[0])
#     updated_at = datetime.now()
#     duration_hours = max((updated_at - created_at).total_seconds() / 3600, 0)
#     fee = round(int(duration_hours * 3000), -3)  # Rp3000 per hour

#     # Update UpdatedAt, PaymentStat, and Fee
#     updated_str = updated_at.strftime("%Y-%m-%d %H:%M:%S")
#     cursor.execute("""
#         UPDATE vehicle
#         SET UpdatedAt = ?, PaymentStat = ?, Fee = ?
#         WHERE id = ?
#     """, (updated_str, "Paid", fee, id))

#     conn.commit()
#     conn.close()

#     return jsonify({
#         "success": True,
#         "updatedAt": updated_str,
#         "durationHours": round(duration_hours, 2),
#         "fee": fee
#     })
