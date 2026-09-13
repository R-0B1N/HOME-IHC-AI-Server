import os
import fitz

for path in [
    "docs/Property Acknowledgement Document.pdf",
    "docs/Customer Property Acknowledgement & Viewing Form.pdf",
    "backend/app/templates/Property Acknowledgement Document.pdf"
]:
    if os.path.exists(path):
        pdf = fitz.open(path)
        print(f"\n================ {path} ================")
        print(f"Pages: {len(pdf)}")
        for page_idx in range(len(pdf)):
            page = pdf[page_idx]
            blocks = page.get_text("blocks")
            print(f"  Page {page_idx+1}: {len(blocks)} blocks. First 3 blocks:")
            for b in blocks[:3]:
                print(f"    ({b[0]:.1f}, {b[1]:.1f}, {b[2]:.1f}, {b[3]:.1f}): {b[4].strip()[:60]!r}")
            print(f"  Page {page_idx+1} Last 2 blocks:")
            for b in blocks[-2:]:
                print(f"    ({b[0]:.1f}, {b[1]:.1f}, {b[2]:.1f}, {b[3]:.1f}): {b[4].strip()[:60]!r}")
