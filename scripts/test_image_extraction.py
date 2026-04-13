#!/usr/bin/env python3
"""Test image extraction approaches on a PDF.

Downloads a PDF and tries multiple extraction strategies, saving results
to /tmp/image_test/ for visual inspection.

Usage:
    python scripts/test_image_extraction.py https://arxiv.org/pdf/2604.08401
    python scripts/test_image_extraction.py /path/to/local.pdf
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import fitz


def extract_embedded_images(doc: fitz.Document, output_dir: Path) -> int:
    """Strategy 1: pymupdf get_images() — extracts raw embedded XREFs."""
    out = output_dir / "strategy1_embedded"
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            try:
                img_data = doc.extract_image(xref)
            except Exception:
                continue
            if not img_data or not img_data.get("image"):
                continue
            w, h = img_data.get("width", 0), img_data.get("height", 0)
            ext = img_data.get("ext", "png")
            filename = f"p{page_idx}_i{count}_{w}x{h}.{ext}"
            (out / filename).write_bytes(img_data["image"])
            print(f"  [embedded] {filename}")
            count += 1
    return count


def render_figure_pages(doc: fitz.Document, output_dir: Path, dpi: int = 150) -> int:
    """Strategy 2: Render full pages that contain 'Figure N:' captions."""
    out = output_dir / "strategy2_figure_pages"
    out.mkdir(parents=True, exist_ok=True)
    figure_pages: list[int] = []
    for page_idx in range(doc.page_count):
        text = doc[page_idx].get_text()
        if re.search(r"Figure\s+\d+[.:]\s", text) or "<!-- image -->" in text:
            figure_pages.append(page_idx)

    print(f"  Pages with figures: {figure_pages}")
    count = 0
    for page_idx in figure_pages:
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=dpi)
        filename = f"page_{page_idx}_full.png"
        (out / filename).write_bytes(pix.tobytes("png"))
        print(f"  [full page] {filename} ({pix.width}x{pix.height})")
        count += 1
    return count


def render_figure_regions(doc: fitz.Document, output_dir: Path, dpi: int = 200) -> int:
    """Strategy 3: Detect figure regions via text layout and render cropped areas."""
    out = output_dir / "strategy3_figure_regions"
    out.mkdir(parents=True, exist_ok=True)
    count = 0

    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        text_dict = page.get_text("dict")
        page_height = page.rect.height
        page_width = page.rect.width

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_text = "".join(span["text"] for span in line.get("spans", []))
                match = re.match(r"Figure\s+(\d+)[.:]\s*(.+)", line_text)
                if not match:
                    continue

                fig_num = match.group(1)
                caption_y = line["bbox"][1]
                fig_top = max(0, caption_y - page_height * 0.4)
                fig_bottom = min(page_height, line["bbox"][3] + 10)

                clip = fitz.Rect(0, fig_top, page_width, fig_bottom)
                pix = page.get_pixmap(dpi=dpi, clip=clip)

                if pix.width > 50 and pix.height > 50:
                    filename = f"fig{fig_num}_p{page_idx}_{pix.width}x{pix.height}.png"
                    (out / filename).write_bytes(pix.tobytes("png"))
                    print(f"  [region] {filename}")
                    count += 1
    return count


def extract_via_docling(pdf_path: Path, output_dir: Path) -> int:
    """Strategy 4: Docling native figure extraction via PictureItem."""
    out = output_dir / "strategy4_docling"
    out.mkdir(parents=True, exist_ok=True)

    try:
        from docling.datamodel.base_models import InputFormat  # noqa: PLC0415
        from docling.datamodel.pipeline_options import PdfPipelineOptions  # noqa: PLC0415
        from docling.document_converter import DocumentConverter, PdfFormatOption  # noqa: PLC0415
        from docling_core.types.doc import PictureItem, TableItem  # noqa: PLC0415
    except ImportError:
        print("  Docling not installed, skipping.")
        return 0

    pipeline_options = PdfPipelineOptions()
    pipeline_options.images_scale = 2.0
    pipeline_options.generate_page_images = True
    pipeline_options.generate_picture_images = True

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )

    start = time.time()
    conv_res = converter.convert(str(pdf_path))
    elapsed = time.time() - start
    print(f"  Docling conversion: {elapsed:.1f}s")

    picture_count = 0
    table_count = 0
    doc_name = pdf_path.stem

    for element, _level in conv_res.document.iterate_items():
        if isinstance(element, PictureItem):
            picture_count += 1
            img = element.get_image(conv_res.document)
            if img:
                filename = f"{doc_name}-picture-{picture_count}.png"
                img.save(out / filename, "PNG")
                print(f"  [docling picture] {filename} ({img.width}x{img.height})")

        if isinstance(element, TableItem):
            table_count += 1
            img = element.get_image(conv_res.document)
            if img:
                filename = f"{doc_name}-table-{table_count}.png"
                img.save(out / filename, "PNG")
                print(f"  [docling table] {filename} ({img.width}x{img.height})")

    return picture_count + table_count


def main() -> None:
    """Run all extraction strategies on a PDF."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_image_extraction.py <pdf_url_or_path>")
        sys.exit(1)

    source = sys.argv[1]
    output_dir = Path("/tmp/image_test")
    # Clean previous results
    import shutil  # noqa: PLC0415

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Download if URL
    if source.startswith("http"):
        import httpx  # noqa: PLC0415

        print(f"Downloading {source}...")
        resp = httpx.get(source, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        pdf_path = output_dir / "test.pdf"
        pdf_path.write_bytes(resp.content)
    else:
        pdf_path = Path(source)

    doc = fitz.open(str(pdf_path))
    print(f"PDF: {pdf_path.name}, {doc.page_count} pages\n")

    print("=== Strategy 1: Embedded images (get_images) ===")
    n1 = extract_embedded_images(doc, output_dir)
    print(f"  Total: {n1}\n")

    print("=== Strategy 2: Full figure pages (render) ===")
    n2 = render_figure_pages(doc, output_dir)
    print(f"  Total: {n2}\n")

    print("=== Strategy 3: Cropped figure regions ===")
    n3 = render_figure_regions(doc, output_dir)
    print(f"  Total: {n3}\n")

    print("=== Strategy 4: Docling native (PictureItem + TableItem) ===")
    n4 = extract_via_docling(pdf_path, output_dir)
    print(f"  Total: {n4}\n")

    doc.close()

    print(f"Results saved to {output_dir}/")
    print(f"  strategy1_embedded/       — {n1} raw embedded images")
    print(f"  strategy2_figure_pages/   — {n2} full page renders")
    print(f"  strategy3_figure_regions/ — {n3} cropped figure regions")
    print(f"  strategy4_docling/        — {n4} docling pictures + tables")
    print(f"\nOpen: open {output_dir}")


if __name__ == "__main__":
    main()
