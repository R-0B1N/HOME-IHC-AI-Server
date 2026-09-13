import docx

doc_c = docx.Document("docs/Property Acknowledgement Document Correct Format.docx")
for p_idx in [14, 15, 16, 17, 18, 19, 22, 26]:
    p = doc_c.paragraphs[p_idx]
    print(f"\n=== P{p_idx} ({p.text!r}) ===")
    for r_i, r in enumerate(p.runs):
        print(f"  Run {r_i}: text={r.text!r}, bold={r.bold}, size={r.font.size.pt if r.font.size else None}, font={r.font.name}")
