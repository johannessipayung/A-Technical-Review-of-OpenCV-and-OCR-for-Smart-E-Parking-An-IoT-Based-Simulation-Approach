import sqlite3

conn = sqlite3.connect('data.db')
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS vehicle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    NoPol TEXT NOT NULL,
    Image TEXT,
    PaymentStat TEXT,
    CreatedAt TEXT,
    UpdatedAt TEXT
)
''')

# Add sample data
cursor.execute("INSERT INTO vehicle (NoPol, Image, PaymentStat, CreatedAt, UpdatedAt) VALUES (?, ?, ?, ?, ?)", 
               ("B1234XYZ", "car1.jpg", "Unpaid", "2023-01-01", "2023-01-02"))

conn.commit()
conn.close()
