/*
 * Sistem Gerbang Parkir Otomatis - Kode Arduino (Diperbaiki)
 * 
 * Kode ini untuk mengontrol servo motor yang akan membuka dan menutup gerbang parkir
 * berdasarkan perintah dari Python melalui komunikasi serial.
 * 
 * Koneksi:
 * - Servo terhubung ke pin 9
 * - LED Hijau ke pin 7 (opsional)
 * - LED Merah ke pin 6 (opsional)
 */

#include <Servo.h>

// Pin konfigurasi
const int servoPin = 3;  // Pin untuk servo motor
const int ledGreen = 7;  // LED hijau untuk indikasi gerbang terbuka
const int ledRed = 6;    // LED merah untuk indikasi gerbang tertutup

// Nilai sudut servo
const int GATE_CLOSED = 0;   // Sudut saat gerbang tertutup
const int GATE_OPEN = 90;    // Sudut saat gerbang terbuka

// Variabel status
String inputString = "";     // String untuk menyimpan data yang diterima
boolean stringComplete = false;  // Flag untuk indikasi string lengkap diterima
boolean gateOpen = false;    // Status gerbang

// Variabel untuk anti-bounce
unsigned long lastCommandTime = 0;
const unsigned long commandDelay = 500; // Delay 500ms antara perintah

// Variabel untuk heartbeat
unsigned long lastHeartbeatTime = 0;
const unsigned long heartbeatInterval = 2000; // 2 detik interval untuk heartbeat

// Deklarasi objek servo
Servo gateServo;

void setup() {
  // Inisialisasi komunikasi serial
  Serial.begin(9600);
  while (!Serial) {
    ; // Tunggu port serial terhubung (khusus untuk Arduino Leonardo/Micro)
  }
  
  // Reservasi memori untuk inputString
  inputString.reserve(50);
  
  // Inisialisasi servo
  gateServo.attach(servoPin);
  
  // Set posisi awal gerbang (tertutup)
  gateServo.write(GATE_CLOSED);
  
  // Inisialisasi LED
  pinMode(ledGreen, OUTPUT);
  pinMode(ledRed, OUTPUT);
  
  // Set indikator awal (gerbang tertutup - LED merah menyala)
  digitalWrite(ledGreen, LOW);
  digitalWrite(ledRed, HIGH);
  
  // Tampilkan pesan inisialisasi
  Serial.println("Sistem Gerbang Parkir Siap!");
}

void loop() {
  // Cek jika ada perintah serial lengkap
  if (stringComplete) {
    // Trim string untuk menghilangkan whitespace
    inputString.trim();
    
    // Proses perintah dengan anti-bounce
    unsigned long currentTime = millis();
    if (currentTime - lastCommandTime > commandDelay) {
      lastCommandTime = currentTime;
      
      if (inputString.equalsIgnoreCase("OPEN")) {
        openGate();
      } 
      else if (inputString.equalsIgnoreCase("CLOSE")) {
        closeGate();
      }
      else if (inputString.equalsIgnoreCase("TEST")) {
        Serial.println("OK");
      }
    }
    
    // Reset string dan flag
    inputString = "";
    stringComplete = false;
  }
  
  // Kirim heartbeat setiap interval tertentu
  unsigned long currentMillis = millis();
  if (currentMillis - lastHeartbeatTime > heartbeatInterval) {
    lastHeartbeatTime = currentMillis;
    Serial.println("HEARTBEAT");
  }
  
  // Cek buffer serial setiap loop
  checkSerial();
}

// Fungsi untuk membuka gerbang
void openGate() {
  if (!gateOpen) {
    Serial.println("Membuka gerbang...");
    
    // Buka gerbang dengan gerakan halus
    for (int angle = GATE_CLOSED; angle <= GATE_OPEN; angle += 5) {
      gateServo.write(angle);
      delay(20);  // Delay kecil untuk gerakan halus
    }
    
    // Pastikan posisi akhir tepat
    gateServo.write(GATE_OPEN);
    
    // Ubah indikator LED
    digitalWrite(ledGreen, HIGH);
    digitalWrite(ledRed, LOW);
    
    // Update status
    gateOpen = true;
    
    Serial.println("Gerbang terbuka!");
  } else {
    Serial.println("Gerbang sudah terbuka!");
  }
}

// Fungsi untuk menutup gerbang
void closeGate() {
  if (gateOpen) {
    Serial.println("Menutup gerbang...");
    
    // Tutup gerbang dengan gerakan halus
    for (int angle = GATE_OPEN; angle >= GATE_CLOSED; angle -= 5) {
      gateServo.write(angle);
      delay(20);  // Delay kecil untuk gerakan halus
    }
    
    // Pastikan posisi akhir tepat
    gateServo.write(GATE_CLOSED);
    
    // Ubah indikator LED
    digitalWrite(ledGreen, LOW);
    digitalWrite(ledRed, HIGH);
    
    // Update status
    gateOpen = false;
    
    Serial.println("Gerbang tertutup!");
  } else {
    Serial.println("Gerbang sudah tertutup!");
  }
}

// Fungsi untuk memeriksa data serial tersedia
void checkSerial() {
  while (Serial.available()) {
    // Baca satu byte dari serial
    char inChar = (char)Serial.read();
    
    // Jika newline atau carriage return, set flag complete
    if (inChar == '\n' || inChar == '\r') {
      if (inputString.length() > 0) {
        stringComplete = true;
      }
    } else {
      // Tambahkan karakter ke string
      inputString += inChar;
    }
    
    // Jika buffer terlalu besar, reset
    if (inputString.length() > 40) {
      inputString = "";
    }
  }
}