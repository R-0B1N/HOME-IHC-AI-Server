import fitz

pdf = fitz.open("docs/Viewing_Acknowledgement_0190_Nick.pdf")
print(f"Total pages: {len(pdf)}")

for page_idx in range(len(pdf)):
    page = pdf[page_idx]
    print(f"\n================ PAGE {page_idx + 1} ================")
    # Extract blocks
    blocks = page.get_text("blocks")
    print(f"Total blocks on page {page_idx+1}: {len(blocks)}")
    for b in blocks:
        # b: (x0, y0, x1, y1, text, block_no, block_type)
        print(f"  Block ({b[0]:.1f}, {b[1]:.1f}, {b[2]:.1f}, {b[3]:.1f}):\n{b[4].strip()}")
