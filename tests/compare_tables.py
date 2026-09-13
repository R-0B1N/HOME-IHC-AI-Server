import docx
import fitz

correct_doc = docx.Document("docs/Property Acknowledgement Document Correct Format.docx")
old_doc = docx.Document("backend/app/templates/Property Acknowledgement Document.docx")

print("=== CORRECT DOC TABLES & CELLS ===")
for t_idx, table in enumerate(correct_doc.tables):
    print(f"\n--- TABLE {t_idx} (rows={len(table.rows)}, cols={len(table.columns)}) ---")
    for r_idx, row in enumerate(table.rows):
        for c_idx, cell in enumerate(row.cells):
            # Only print if this cell is not a duplicate from merged cells
            print(f"  Row {r_idx}, Col {c_idx} (width={cell.width.pt if cell.width else None}pt):")
            for p_idx, p in enumerate(cell.paragraphs):
                runs_info = " | ".join([f"'{r.text}'(sz={r.font.size.pt if r.font.size else None}, bold={r.bold}, font={r.font.name})" for r in p.runs])
                print(f"    P{p_idx}: {p.text!r} [Runs: {runs_info}]")

print("\n=== OLD TEMPLATE TABLES & CELLS ===")
for t_idx, table in enumerate(old_doc.tables):
    print(f"\n--- TABLE {t_idx} (rows={len(table.rows)}, cols={len(table.columns)}) ---")
    for r_idx, row in enumerate(table.rows):
        for c_idx, cell in enumerate(row.cells):
            print(f"  Row {r_idx}, Col {c_idx} (width={cell.width.pt if cell.width else None}pt):")
            for p_idx, p in enumerate(cell.paragraphs):
                runs_info = " | ".join([f"'{r.text}'(sz={r.font.size.pt if r.font.size else None}, bold={r.bold}, font={r.font.name})" for r in p.runs])
                print(f"    P{p_idx}: {p.text!r} [Runs: {runs_info}]")
