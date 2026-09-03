"""Build two realistic supplier COA documents:
  1. a TABLE-HEAVY text PDF (pypdf can read chars, but loses table structure)
  2. a SCANNED/IMAGE-ONLY PDF (rasterized -> pypdf gets nothing)
Both mirror the real Vouch spec vocabulary (hardness/HRC, tensile/ASTM-E8).
"""
from PIL import Image, ImageDraw, ImageFont
import io, os

OUT = os.path.dirname(os.path.abspath(__file__))

ROWS = [
    ("Characteristic", "Method",   "Condition",   "Result", "Unit", "Spec Min", "Spec Max"),
    ("Hardness",       "HRC",      "as_received", "42.1",   "HRC",  "38",       "45"),
    ("Tensile Strength","ASTM-E8", "as_received", "1120",   "MPa",  "1030",     "1250"),
    ("Yield Strength", "ASTM-E8",  "as_received", "965",    "MPa",  "900",      "1100"),
    ("Elongation",     "ASTM-E8",  "as_received", "14.2",   "%",    "10",       "-"),
    ("Grain Size",     "ASTM-E112","as_received", "7.5",    "-",    "5",        "-"),
]
HEADER = [
    "ACME SPECIALTY ALLOYS - CERTIFICATE OF ANALYSIS",
    "Supplier: SUP-ACME    Supplier Site: SITE-ACME-01",
    "Material: MAT-ALLOY-7    Lot: LOT-1001    PO: PO-88213",
    "Heat Number: H-55219    Date of Issue: 2026-03-02",
]

# ---------- 1. table-heavy TEXT pdf (hand-built, same approach as the repo test) ----------
def esc(t): return t.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

def make_text_pdf(lines_with_x):
    """lines_with_x: list of (x, y, text) absolutely positioned -> a real table layout."""
    parts = ["BT", "/F1 9 Tf"]
    for x, y, text in lines_with_x:
        parts.append(f"1 0 0 1 {x} {y} Tm")
        parts.append(f"({esc(text)}) Tj")
    parts.append("ET")
    stream = "\n".join(parts).encode()
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Count 1 /Kids [4 0 R] >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        5: b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        4: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>",
    }
    out = bytearray(b"%PDF-1.4\n"); offsets = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objects[num] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {max(objects)+1}\n".encode() + b"0000000000 65535 f \n"
    for num in range(1, max(objects)+1):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {max(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)

placed = []
y = 750
for h in HEADER:
    placed.append((50, y, h)); y -= 14
y -= 16
COLX = [50, 150, 225, 320, 380, 435, 505]
for row in ROWS:
    for x, cell in zip(COLX, row):
        placed.append((x, y, cell))
    y -= 18
placed.append((50, y-20, "Authorized by: J. Restrepo, Quality Manager"))
table_pdf = make_text_pdf(placed)
open(f"{OUT}/coa_table_text.pdf","wb").write(table_pdf)

# ---------- 2. SCANNED image-only pdf ----------
W, H = 1275, 1650  # 150dpi letter
img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)
try:
    f_big = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 30)
    f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 24)
except Exception:
    f_big = f = ImageFont.load_default()

y = 90
d.text((80, y), HEADER[0], fill="black", font=f_big); y += 60
for h in HEADER[1:]:
    d.text((80, y), h, fill="black", font=f); y += 38
y += 30
colx = [80, 330, 520, 720, 850, 960, 1090]
for ri, row in enumerate(ROWS):
    for x, cell in zip(colx, row):
        d.text((x, y), cell, fill="black", font=f)
    y += 44
    if ri == 0:
        d.line([(80, y-10), (1195, y-10)], fill="black", width=2)
d.text((80, y+40), "Authorized by: J. Restrepo, Quality Manager", fill="black", font=f)
# realistic scan artifacts: slight rotation + grayscale noise
img = img.rotate(0.6, expand=False, fillcolor="white").convert("L")
img.save(f"{OUT}/coa_scanned.pdf", "PDF", resolution=150.0)
img.save(f"{OUT}/coa_scanned.png")

print("table_text.pdf bytes:", len(table_pdf))
print("scanned.pdf bytes:", os.path.getsize(f"{OUT}/coa_scanned.pdf"))
