from flask import Flask, Response, render_template_string, request, redirect, url_for
import cv2
import pytesseract
import os
import serial
import time
from datetime import datetime
from threading import Thread
import atexit
import mysql.connector
import qrcode
import io
import base64
import time
from threading import Thread
import re
import numpy as np # <-- Tambahkan import numpy di atas agar bisa diakses global

# ==============================================================================
# KONFIGURASI AWAL
# ==============================================================================

# Konfigurasi path tesseract untuk sistem Anda (sesuaikan jika perlu)
# Untuk macOS (Homebrew)
pytesseract.pytesseract.tesseract_cmd = '/opt/homebrew/bin/tesseract'
# Untuk Windows (jika diinstal di lokasi default)
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe' 
# Untuk Linux (jika diinstal melalui apt)
# pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

# Konfigurasi koneksi MySQL
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'parking_system'
}

# Membuat direktori untuk menyimpan gambar jika belum ada # <--- PENAMBAHAN
os.makedirs('static/photo', exist_ok=True)
os.makedirs('static/processed_scans', exist_ok=True)

# Variabel Global
arduino = None
arduino_connected = False
camera = None
last_frame = None
ocr_result = "Arahkan plat nomor ke kamera"
gate_status = "TERTUTUP"

# ==============================================================================
# KONEKSI HARDWARE & DATABASE
# ==============================================================================

def get_connection():
    """Membuat dan mengembalikan koneksi ke database."""
    try:
        conn = mysql.connector.connect(**db_config)
        return conn
    except mysql.connector.Error as err:
        print(f"Database connection error: {err}")
        return None

def connect_arduino():
    """Menghubungkan ke Arduino melalui port serial."""
    global arduino, arduino_connected
    try:
        if arduino and arduino.is_open:
            arduino.close()
            time.sleep(1)
        # Port serial mungkin berbeda, sesuaikan '/dev/tty.usbserial-10' atau 'COM4' untuk Windows
        arduino = serial.Serial('/dev/tty.usbserial-10', 9600, timeout=1, write_timeout=1)
        arduino_connected = True
        time.sleep(2) # Beri waktu untuk Arduino reset
        print("Arduino terhubung!")
    except Exception as e:
        arduino_connected = False
        print(f"PERINGATAN: Arduino tidak terhubung! Error: {str(e)}")

def init_camera():
    """Menginisialisasi kamera."""
    global camera
    try:
        camera = cv2.VideoCapture(0) # Coba kamera utama (index 0)
        if not camera.isOpened():
            print("Kamera (index 0) tidak terdeteksi, mencoba index 1...")
            camera = cv2.VideoCapture(1) # Coba kamera kedua
        
        if not camera.isOpened():
            print("PERINGATAN: Tidak ada kamera yang terdeteksi!")
        else:
            print(f"Kamera berhasil diinisialisasi.")
    except Exception as e:
        print(f"Error saat menginisialisasi kamera: {str(e)}")

def cleanup_connections():
    """Membersihkan koneksi saat aplikasi ditutup."""
    global arduino, camera
    if arduino and arduino.is_open:
        arduino.close()
        print("Koneksi Arduino ditutup.")
    if camera:
        camera.release()
        print("Kamera dilepaskan.")

# Menjalankan koneksi di awal dan mendaftarkan cleanup
connect_arduino()
init_camera()
atexit.register(cleanup_connections)

app = Flask(__name__)

# ==============================================================================
# FUNGSI UTAMA & LOGIKA APLIKASI
# ==============================================================================

def open_gate_with_timer():
    """Mengirim sinyal buka dan tutup gerbang ke Arduino dengan jeda waktu."""
    global gate_status, arduino, arduino_connected
    if not arduino_connected:
        print("Mencoba menghubungkan ulang ke Arduino...")
        connect_arduino()
    
    if arduino_connected:
        try:
            print("Mengirim perintah BUKA ke Arduino...")
            arduino.write(b'OPEN\n')
            gate_status = "TERBUKA"
            time.sleep(10) # Gerbang terbuka selama 10 detik
            print("Mengirim perintah TUTUP ke Arduino...")
            arduino.write(b'CLOSE\n')
            gate_status = "TERTUTUP"
            print("Gerbang ditutup setelah jeda.")
        except Exception as e:
            print(f"Error saat mengoperasikan gerbang: {str(e)}")
            arduino_connected = False
            gate_status = "TERTUTUP"
    else:
        print("Operasi gerbang gagal: Arduino tidak terhubung.")

def save_vehicle_to_database(plate_number, image_path):
    """Menyimpan data kendaraan ke database."""
    conn = get_connection()
    if conn is None:
        return False, "Koneksi database gagal."
    
    try:
        cursor = conn.cursor()
        now = datetime.now()
        created_at = now.strftime('%Y-%m-%d %H:%M:%S')
        query = "INSERT INTO vehicle (NoPol, Image, PaymentStat, CreatedAt) VALUES (%s, %s, 'Unpaid', %s)"
        cursor.execute(query, (plate_number, image_path, created_at))
        vehicle_id = cursor.lastrowid
        conn.commit()
        return True, f"Data berhasil disimpan dengan ID: {vehicle_id}"
    except mysql.connector.Error as e:
        print(f"Database error: {e}")
        return False, f"Gagal menyimpan data: {str(e)}"
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

def generate_frames():
    """Generator untuk streaming frame kamera ke halaman web."""
    global last_frame, camera
    if not camera or not camera.isOpened():
        # Buat frame hitam jika kamera tidak tersedia
        black_frame = np.zeros((480, 640, 3), np.uint8)
        cv2.putText(black_frame, "Kamera Tidak Tersedia", (120, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        while True:
            ret, buffer = cv2.imencode('.jpg', black_frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(1)
    
    while True:
        success, frame = camera.read()
        if not success:
            time.sleep(0.1)
            continue
        
        last_frame = frame.copy()
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# ==============================================================================
# ROUTE FLASK (ENDPOINT)
# ==============================================================================

HTML_PAGE = '''
<!doctype html>
<html lang="id">
<head>
    <title>Sistem E-Parking</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8f9fa; }
        .ocr-result-box { font-size: 2rem; font-weight: bold; color: #2c3e50; background-color: #ecf0f1; border: 2px dashed #7f8c8d; padding: 20px; min-height: 120px; border-radius: 10px; text-align: center; display: flex; align-items: center; justify-content: center; }
        #clock { font-size: 1.5rem; font-weight: bold; margin-top: 15px; text-align: center; color: #34495e; }
        .gate-status { font-size: 1.5rem; margin-top: 15px; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold; color: white; }
        .gate-open { background-color: #2ecc71; }
        .gate-closed { background-color: #e74c3c; }
        .status-badge { margin-top: 15px; font-size: 1.1rem; padding: 8px 15px; border-radius: 5px; color: white; }
        .status-success { background-color: #2ecc71; }
        .status-error { background-color: #e74c3c; }
    </style>
</head>
<body class="bg-light">
    <div class="container py-4">
        <h1 class="text-center mb-4">🚘 Sistem E-Parking</h1>
        <div class="row g-4">
            <div class="col-md-7 text-center">
                <img src="{{ url_for('video_feed') }}" class="img-fluid rounded border mb-3" style="max-height: 480px;">
                <form method="POST" action="/scan" class="d-flex justify-content-center gap-2">
                    <button type="submit" class="btn btn-lg btn-success">Scan Plat & Pesan Tiket</button>
                    <a href="/bantuan" class="btn btn-lg btn-info">Bantuan</a>
                </form>
                <div id="gate-status" class="gate-status gate-closed mt-3">Status Gerbang: TERTUTUP</div>
            </div>
            <div class="col-md-5">
                <div class="h-100 d-flex flex-column">
                    <label class="form-label fs-4 fw-bold">Hasil Pindai Plat Nomor:</label>
                    <div class="ocr-result-box flex-grow-1">{{ text }}</div>
                    <div id="clock">Memuat waktu...</div>
                    {% if db_message %}
                        <div class="status-badge {% if db_status == 'success' %}status-success{% else %}status-error{% endif %} mt-3">
                            {{ db_message }}
                        </div>
                    {% endif %}
                    <hr>
                    <div class="system-status">
                        <strong>Status Sistem:</strong>
                        <div id="arduino-status" class="mt-2"><span class="badge bg-secondary">Memeriksa Arduino...</span></div>
                        <div id="database-status" class="mt-2"><span class="badge bg-secondary">Memeriksa Database...</span></div>
                        <div class="mt-3">
                            <a href="/test_connection" class="btn btn-sm btn-outline-primary">Tes Koneksi</a>
                            <a href="/open_gate" class="btn btn-sm btn-outline-warning">Buka Gerbang Manual</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <script>
        function updateClock() {
            const now = new Date();
            const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' };
            document.getElementById('clock').innerHTML = now.toLocaleDateString('id-ID', options);
        }
        function checkStatus(url, elementId, successClass, errorClass, successText, errorText) {
            fetch(url)
                .then(response => response.text())
                .then(status => {
                    const el = document.getElementById(elementId);
                    if (status === 'connected') {
                        el.innerHTML = `<span class="badge ${successClass}">${successText}</span>`;
                    } else {
                        el.innerHTML = `<span class="badge ${errorClass}">${errorText}</span>`;
                    }
                });
        }
        function checkGateStatus() {
            fetch('/gate_status').then(r => r.text()).then(s => {
                const el = document.getElementById('gate-status');
                el.textContent = 'Status Gerbang: ' + s;
                el.className = s === 'TERBUKA' ? 'gate-status gate-open' : 'gate-status gate-closed';
            });
        }
        setInterval(updateClock, 1000);
        setInterval(checkGateStatus, 1000);
        setInterval(() => checkStatus('/arduino_status', 'arduino-status', 'bg-success', 'bg-danger', 'Arduino Terhubung', 'Arduino Terputus'), 5000);
        setInterval(() => checkStatus('/database_status', 'database-status', 'bg-success', 'bg-danger', 'Database Terhubung', 'Database Terputus'), 5000);
        window.onload = () => { updateClock(); checkGateStatus(); };
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_PAGE, text=ocr_result, db_status=None, db_message=None)

@app.route('/scan', methods=['POST'])
def scan():
    global ocr_result, last_frame
    db_status, db_message = None, ""

    if last_frame is None:
        ocr_result = "Tidak ada gambar dari kamera."
        return render_template_string(HTML_PAGE, text=ocr_result, db_status="error", db_message="Kamera tidak memberikan gambar.")

    try:
        # --- PERBAIKAN & PENYUSUNAN ULANG PROSES GAMBAR ---

        # 1. Siapkan nama file berdasarkan waktu
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_only = f"scan_{timestamp}.jpg"
        original_path = f"static/photo/{filename_only}"
        
        # Simpan gambar asli (berwarna)
        cv2.imwrite(original_path, last_frame)

        # 2. (SESUAI PERMINTAAN) Ubah ke Grayscale sebagai langkah pertama
        gray_image = cv2.cvtColor(last_frame, cv2.COLOR_BGR2GRAY)
        
        # 3. (SESUAI PERMINTAAN) Simpan gambar grayscale ke folder terpisah
        processed_path = f"static/processed_scans/processed_{filename_only}"
        cv2.imwrite(processed_path, gray_image) # <-- Menyimpan hasil grayscale

        # 4. Lanjutkan preprocessing dari gambar grayscale untuk optimasi OCR
        # Resize untuk memperbesar detail
        resized = cv2.resize(gray_image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        # Denoising
        denoised = cv2.bilateralFilter(resized, 11, 17, 17)
        # Thresholding
        thresh = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 4)
        # Operasi morfologi untuk menyambungkan karakter yang terputus
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        morphed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        # 5. Lakukan OCR pada gambar yang sudah diproses secara optimal
        # Menggunakan PSM 7 yang mengasumsikan gambar adalah satu baris teks
        config = '--psm 7'
        text = pytesseract.image_to_string(morphed, lang='eng', config=config) # <-- Hanya satu panggilan OCR yang efisien
        
        # --- AKHIR DARI PERBAIKAN PROSES GAMBAR ---

        ocr_result = text.strip()

        if not ocr_result:
            ocr_result = "Tidak ada teks terdeteksi."
            db_status, db_message = "error", "Gagal mendeteksi plat nomor, silakan coba lagi."
        else:
            # Bersihkan dan validasi hasil OCR
            cleaned_plate = ''.join(c for c in ocr_result if c.isalnum()).upper()
            
            if re.match(r'^[A-Z0-9]+$', cleaned_plate) and len(cleaned_plate) > 3:
                # Simpan ke database jika valid
                success, message = save_vehicle_to_database(cleaned_plate, filename_only)
                db_status = "success" if success else "error"
                db_message = message

                if success:
                    # Buka gerbang hanya jika semua proses berhasil
                    gate_thread = Thread(target=open_gate_with_timer)
                    gate_thread.daemon = True
                    gate_thread.start()
                    # Arahkan ke halaman cetak tiket
                    return redirect(url_for('print_ticket', image_filename=filename_only, plate=cleaned_plate))
                else:
                    ocr_result = "Gagal menyimpan ke database."
            else:
                db_status, db_message = "error", f"Hasil deteksi '{cleaned_plate}' tidak valid."
                ocr_result = db_message
    
    except Exception as e:
        ocr_result = "Terjadi kesalahan sistem."
        db_status, db_message = "error", f"Error: {str(e)}"
        print(f"Error pada proses scan: {e}")

    return render_template_string(HTML_PAGE, text=ocr_result, db_status=db_status, db_message=db_message)

@app.route('/print_ticket')
def print_ticket():
    image_filename = request.args.get('image_filename')
    plate = request.args.get('plate')
    
    # Data untuk QR code (bisa berupa ID unik atau nama file gambar)
    qr_data = f"VehiclePlate:{plate},File:{image_filename}"
    qr = qrcode.make(qr_data)
    
    buffered = io.BytesIO()
    qr.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode()

    return render_template_string('''
    <!doctype html>
    <html>
    <head>
        <title>Cetak Tiket Parkir</title>
        <style>
            body { font-family: 'Courier New', Courier, monospace; text-align: center; margin-top: 20px; width: 300px; }
            h1 { font-size: 1.5rem; margin: 0; } p { margin: 5px 0; }
            .qr { margin: 15px; } .footer { margin-top: 20px; font-size: 0.9rem; }
            @media print { body { -webkit-print-color-adjust: exact; } }
        </style>
    </head>
    <body onload="window.print(); setTimeout(function(){ window.location.href = '/'; }, 2000);">
        <h1>TIKET PARKIR</h1>
        <p>Mall Sun Plaza</p>
        <hr>
        <p>No. Plat: <strong>{{ plate }}</strong></p>
        <p>Waktu Masuk: {{ time }}</p>
        <div class="qr"><img src="data:image/png;base64,{{ qr_base64 }}" width="180"></div>
        <div class="footer">
            <p>Terima kasih atas kunjungan Anda.</p>
            <p>Harap simpan tiket ini untuk pembayaran.</p>
        </div>
    </body>
    </html>
    ''', qr_base64=qr_base64, plate=plate, time=datetime.now().strftime('%d-%m-%Y %H:%M:%S'))

@app.route('/bantuan')
def bantuan():
    # Halaman bantuan sederhana
    return '''
        <!doctype html><html lang="id"><head><title>Bantuan</title><meta charset="utf-8">
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"></head>
        <body><div class="container py-5"><div class="card p-4"><h1 class="text-center">Panduan Penggunaan</h1>
        <ol><li>Posisikan kendaraan agar plat nomor terlihat jelas di kamera.</li>
        <li>Tekan tombol "Scan Plat & Pesan Tiket".</li>
        <li>Sistem akan memindai plat, menyimpan data, dan membuka gerbang.</li>
        <li>Ambil tiket yang tercetak. Gerbang akan terbuka selama 10 detik.</li></ol>
        <p>Jika ada kendala, hubungi petugas di lokasi.</p>
        <div class="text-center mt-4"><a href="/" class="btn btn-primary">Kembali</a></div></div></div></body></html>'''

# --- Rute untuk status dan kontrol manual ---
@app.route('/gate_status')
def get_gate_status():
    return gate_status

@app.route('/arduino_status')
def arduino_status():
    return "connected" if arduino_connected else "disconnected"

@app.route('/database_status')
def database_status():
    conn = get_connection()
    if conn:
        conn.close()
        return "connected"
    return "disconnected"

@app.route('/open_gate')
def open_gate():
    gate_thread = Thread(target=open_gate_with_timer)
    gate_thread.daemon = True
    gate_thread.start()
    return redirect(url_for('index'))

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/test_connection')
def test_connection():
    results = {}
    # Test Arduino
    connect_arduino() # Coba koneksi ulang
    results['Arduino'] = "Terhubung" if arduino_connected else "Gagal terhubung"
    # Test Database
    results['Database'] = "Terhubung" if database_status() == "connected" else "Gagal terhubung"
    return f"<h2>Hasil Tes Koneksi</h2><p>Arduino: {results['Arduino']}</p><p>Database: {results['Database']}</p><a href='/'>Kembali</a>"

if __name__ == '__main__':
    # use_reloader=False penting untuk mencegah masalah dengan koneksi serial
    app.run(debug=True, host='0.0.0.0', port=2000, threaded=True, use_reloader=False)
