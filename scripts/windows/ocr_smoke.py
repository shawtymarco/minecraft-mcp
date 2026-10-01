"""Check persistent Windows OCR against a generated image; no desktop/game capture."""
import base64
import json
import time
import cv2
import numpy as np
from local_loop import WindowsOCR

image = np.full((160, 700, 3), 255, dtype=np.uint8)
cv2.putText(image, "Play Settings", (25, 95), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 0, 0), 3)
ok, png = cv2.imencode(".png", image)
assert ok
payload = base64.b64encode(png).decode("ascii")
worker = WindowsOCR()
try:
    rows = []
    for _ in range(3):
        started = time.perf_counter()
        text = worker.read_png(payload)
        assert "play" in text.lower() and "settings" in text.lower(), text
        rows.append({"text": text, "ms": round((time.perf_counter() - started) * 1000, 1)})
    print(json.dumps({"status": "passed", "samples": rows}))
finally:
    worker.close()
