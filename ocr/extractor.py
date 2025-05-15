import pytesseract

def ekstrak_teks_dari_gambar(frame):
    teks = pytesseract.image_to_string(frame)
    return teks
