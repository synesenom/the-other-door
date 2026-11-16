"""tests/pdf_utils.raw_pdf: the hand-written PDFs the style tests read."""

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from pdf_utils import raw_pdf


def test_a_hand_written_pdf_opens_with_its_text_and_pages(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(raw_pdf(["BT /F1 12 Tf 50 700 Td (Hello) Tj ET", "BT /F2 12 Tf 50 700 Td (Page two) Tj ET"],
                             size=(300, 400)))
    doc = pdfium.PdfDocument(str(path))
    assert len(doc) == 2 and doc[0].get_size() == (300, 400)
    assert "Hello" in doc[0].get_textpage().get_text_range()
    objs = list(doc[1].get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT]))
    assert "Bold" in objs[0].get_font().get_base_name()


def test_an_image_is_a_page_object(tmp_path):
    path = tmp_path / "i.pdf"
    path.write_bytes(raw_pdf("q 40 0 0 30 10 10 cm /Im1 Do Q", images={"Im1": (2, 1, bytes([255, 0, 0, 0, 0, 255]))}))
    objs = list(pdfium.PdfDocument(str(path))[0].get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]))
    assert len(objs) == 1
