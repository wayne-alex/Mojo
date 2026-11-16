"""
Extract plain text from uploaded delivery files so AI detection can run.
Supports: .txt, .pdf, .docx, .doc (best effort)
"""
import io
import logging

logger = logging.getLogger(__name__)


def extract_text(django_file, max_chars: int = 20000) -> str:
    """
    Given a Django FileField, return plain text for AI analysis.
    Falls back to empty string if extraction fails.
    """
    if not django_file:
        return ""

    name = (django_file.name or "").lower()

    try:
        django_file.open()
        raw = django_file.read()
    except Exception as exc:
        logger.warning("Could not read file: %s", exc)
        return ""
    finally:
        try:
            django_file.close()
        except Exception:
            pass

    # Plain text
    if name.endswith(".txt"):
        return raw.decode("utf-8", errors="ignore")[:max_chars]

    # PDF
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            text = "\n".join(
                (page.extract_text() or "") for page in reader.pages
            )
            return text[:max_chars]
        except Exception as exc:
            logger.warning("PDF extraction failed: %s", exc)
            return ""

    # DOCX
    if name.endswith(".docx"):
        try:
            import docx
            doc = docx.Document(io.BytesIO(raw))
            text = "\n".join(p.text for p in doc.paragraphs)
            return text[:max_chars]
        except Exception as exc:
            logger.warning("DOCX extraction failed: %s", exc)
            return ""

    # DOC (legacy) — best effort, may be binary
    if name.endswith(".doc"):
        try:
            return raw.decode("utf-8", errors="ignore")[:max_chars]
        except Exception:
            return ""

    # Unknown type — try to decode as text
    return raw.decode("utf-8", errors="ignore")[:max_chars]