#!/usr/bin/env python3
"""Extrae texto plano de un documento de dominio para el pipeline de requisitos.

Formatos soportados:
  - .txt / .md / .markdown : se leen directamente.
  - .docx                  : se extrae con la biblioteca estandar (zipfile + xml),
                             sin dependencias externas.
  - .pdf                   : usa pypdf o pdfminer.six si estan instalados.

Uso:
    python extract_document.py <ruta-entrada> [<ruta-salida>]

Si no se pasa ruta de salida, escribe a stdout.
El codigo de salida es 0 si extrajo texto, 1 si hubo un error.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def extract_docx(path: Path) -> str:
    """Extrae texto de un .docx usando solo la biblioteca estandar.

    Recorre word/document.xml y arma una linea por parrafo (w:p) y una linea
    por fila de tabla (w:tr) con las celdas separadas por ' | '.
    """
    with zipfile.ZipFile(path) as zf:
        if "word/document.xml" not in zf.namelist():
            raise ValueError("El .docx no contiene word/document.xml")
        xml_bytes = zf.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    body = root.find(f"{_W}body")
    if body is None:
        body = root

    def paragraph_text(p_el: ET.Element) -> str:
        return "".join(t.text or "" for t in p_el.iter(f"{_W}t")).strip()

    lines: list[str] = []
    for el in body.iter():
        if el.tag == f"{_W}tbl":
            for row in el.iter(f"{_W}tr"):
                cells = [paragraph_text(cell) for cell in row.iter(f"{_W}tc")]
                cells = [c for c in cells if c]
                if cells:
                    lines.append(" | ".join(cells))
        elif el.tag == f"{_W}p":
            text = paragraph_text(el)
            if text:
                lines.append(text)

    # ET.iter visita los parrafos de tabla dos veces; deduplicamos lineas
    # consecutivas identicas que vienen de ese doble recorrido.
    deduped: list[str] = []
    for line in lines:
        if deduped and deduped[-1] == line:
            continue
        deduped.append(line)
    return "\n".join(deduped)


def extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except ImportError:
        pass

    try:
        from pdfminer.high_level import extract_text  # type: ignore

        return extract_text(str(path))
    except ImportError as exc:
        raise RuntimeError(
            "Para leer PDF instala una de estas bibliotecas:\n"
            "  pip install pypdf\n"
            "  pip install pdfminer.six"
        ) from exc


def extract(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return extract_txt(path)
    if suffix == ".docx":
        return extract_docx(path)
    if suffix == ".pdf":
        return extract_pdf(path)
    raise ValueError(
        f"Formato no soportado: '{suffix}'. Usa .txt, .md, .docx o .pdf "
        "(convierte los .doc antiguos a .docx primero)."
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 1

    in_path = Path(argv[1]).expanduser()
    if not in_path.is_file():
        print(f"ERROR: no existe el archivo: {in_path}", file=sys.stderr)
        return 1

    try:
        text = extract(in_path).strip()
    except Exception as exc:  # noqa: BLE001 - reporte amigable al usuario
        print(f"ERROR extrayendo '{in_path.name}': {exc}", file=sys.stderr)
        return 1

    if not text:
        print(f"ERROR: no se extrajo texto de '{in_path.name}'.", file=sys.stderr)
        return 1

    if len(argv) >= 3:
        out_path = Path(argv[2]).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"OK: {len(text)} caracteres extraidos -> {out_path}", file=sys.stderr)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
