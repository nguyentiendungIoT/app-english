"""
Module 1: Document Parsing — Trích xuất Dữ liệu
=================================================
Converts binary/structured document formats into plain UTF-8 strings
in memory.

Supported formats:
  .txt  — built-in open()
  .docx — python-docx (XML tree → text nodes)
  .pdf  — PyMuPDF / fitz (XREF table → character coordinates → linear string)
"""

from __future__ import annotations

import os
from typing import Optional


class DocumentParser:
    """
    Stateless helper that reads a file and returns its full text content.

    Usage
    -----
        parser = DocumentParser()
        text = parser.parse("/path/to/document.pdf")
    """

    # Registered file extensions (lower-case, with dot)
    SUPPORTED_EXTENSIONS = {".txt", ".docx", ".pdf"}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, file_path: str) -> str:
        """
        Dispatch to the appropriate reader based on file extension.

        Returns
        -------
        str
            The full text content of the document, UTF-8.

        Raises
        ------
        FileNotFoundError
            If *file_path* does not exist.
        ValueError
            If the extension is not supported.
        """
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".txt":
            return self._parse_txt(file_path)
        elif ext == ".docx":
            return self._parse_docx(file_path)
        elif ext == ".pdf":
            return self._parse_pdf(file_path)
        else:
            raise ValueError(
                f"Unsupported file type '{ext}'. "
                f"Supported: {', '.join(sorted(self.SUPPORTED_EXTENSIONS))}"
            )

    # ------------------------------------------------------------------
    # TXT
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_txt(path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()

    # ------------------------------------------------------------------
    # DOCX  (python-docx → XML tree traversal)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_docx(path: str) -> str:
        from docx import Document  # lazy import — only pay if needed

        doc = Document(path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)

    # ------------------------------------------------------------------
    # PDF  (PyMuPDF / fitz — XREF + character coordinates)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_pdf(path: str) -> str:
        import fitz  # PyMuPDF — lazy import

        text_parts: list[str] = []
        with fitz.open(path) as pdf:
            for page in pdf:
                page_text = page.get_text("text")
                if page_text.strip():
                    text_parts.append(page_text)
        return "\n".join(text_parts)


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python document_parser.py <file_path>")
        sys.exit(1)

    parser = DocumentParser()
    content = parser.parse(sys.argv[1])
    print(f"--- Extracted {len(content)} characters ---")
    print(content[:2000])
