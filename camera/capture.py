import cv2

def buka_kamera():
    return cv2.VideoCapture(0)

def ambil_gambar(cam):
    ret, frame = cam.read()
    if ret:
        return frame
    return None

def tutup_kamera(cam):
    cam.release()
