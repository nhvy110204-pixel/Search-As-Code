import os
import gc
import logging
import tempfile
import asyncio
from typing import Dict, Any, Optional, Set
from uuid import UUID

try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import torch
except ImportError:
    torch = None

from app.shared.enums import IngestionTaskStatus
from app.core.compression import decompress_data
from app.observability.metrics import track_step_duration
from app.rag.ingestion.quality_gate import (
    QualityAssessment,
    evaluate_parse_quality,
    EscalationAction,
)

try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, EasyOcrOptions
except ImportError:
    class DocumentConverter:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass
        def convert(self, *args, **kwargs):
            raise NotImplementedError("Docling is not installed in the current environment.")

    class PdfFormatOption:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

    class InputFormat:  # type: ignore
        PDF = "pdf"

    class PdfPipelineOptions:  # type: ignore
        def __init__(self, *args, **kwargs):
            self.do_ocr: bool = False
            self.ocr_options: Any = None

    class EasyOcrOptions:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass



logger = logging.getLogger(__name__)

class PdfProfile:
    """Classified profiles for PDF documents to optimize parsing strategy and resource consumption."""
    DIGITAL_BOOK = "DIGITAL_BOOK"   # Standard Portrait book, whitepaper, contract, rich digital text flow
    SLIDE_VISUAL = "SLIDE_VISUAL"   # Presentation deck (16:9, 4:3), architecture diagram, flowchart, infographic
    SCANNED = "SCANNED"             # Pure raster image scan with no digital selectable text


# Adaptive batch sizing per profile to guarantee memory safety and high throughput
BATCH_SIZE_BY_PROFILE: Dict[str, int] = {
    PdfProfile.DIGITAL_BOOK: 40,
    PdfProfile.SLIDE_VISUAL: 15,
    PdfProfile.SCANNED: 15,
}

# Keywords indicating slide/diagram-centric presentations
SLIDE_KEYWORDS: Set[str] = {
    "slide", "slides", "presentation", "deck", "infographic",
    "overview", "diagram", "flowchart", "mindmap", "cheatsheet",
    "pitch", "keynote", "architecture", "roadmap"
}

# Lazy-loaded singleton converters to avoid startup latency and idle memory footprint
_fast_docling_converter: Optional[DocumentConverter] = None
_bitmap_ocr_docling_converter: Optional[DocumentConverter] = None
_full_ocr_docling_converter: Optional[DocumentConverter] = None


def _get_fast_converter() -> DocumentConverter:
    """Fast converter: native PDF text and structure extraction without OCR overhead."""
    global _fast_docling_converter
    if _fast_docling_converter is None:
        opts = PdfPipelineOptions()
        opts.do_ocr = False
        _fast_docling_converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=opts)
            }
        )
    return _fast_docling_converter


def _get_bitmap_ocr_converter() -> DocumentConverter:
    """
    Bitmap OCR converter: keeps native selectable text while running EasyOCR
    on embedded diagrams, architecture boxes, and chart images (bitmap_area_threshold=0.03).
    """
    global _bitmap_ocr_docling_converter
    if _bitmap_ocr_docling_converter is None:
        opts = PdfPipelineOptions()
        opts.do_ocr = True
        opts.ocr_options = EasyOcrOptions(
            lang=["en", "vi"],
            bitmap_area_threshold=0.03,
            force_full_page_ocr=False
        )
        _bitmap_ocr_docling_converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=opts)
            }
        )
    return _bitmap_ocr_docling_converter


def _get_full_ocr_converter() -> DocumentConverter:
    """Full OCR converter: full-page rasterization for pure scanned PDF files."""
    global _full_ocr_docling_converter
    if _full_ocr_docling_converter is None:
        opts = PdfPipelineOptions()
        opts.do_ocr = True
        opts.ocr_options = EasyOcrOptions(
            lang=["en", "vi"],
            force_full_page_ocr=True
        )
        _full_ocr_docling_converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=opts)
            }
        )
    return _full_ocr_docling_converter


def _get_converter_for_profile(profile: str) -> DocumentConverter:
    """Returns the dedicated singleton converter corresponding to the classified PDF profile."""
    if profile == PdfProfile.SLIDE_VISUAL:
        return _get_bitmap_ocr_converter()
    elif profile == PdfProfile.SCANNED:
        return _get_full_ocr_converter()
    return _get_fast_converter()


def _free_memory() -> None:
    """Forces garbage collection and clears CUDA cache if GPU acceleration is active."""
    gc.collect()
    if torch is not None and hasattr(torch, "cuda") and torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass


def _detect_pdf_profile(temp_file_path: str, file_name: str, max_check_pages: int = 15) -> str:
    """
    Intelligent multi-criteria PDF profile classifier.
    Examines page aspect ratio (Landscape vs Portrait), selectable text density,
    embedded image presence, and filename heuristics.

    Returns one of: PdfProfile.DIGITAL_BOOK, PdfProfile.SLIDE_VISUAL, PdfProfile.SCANNED.
    """
    lower_name = (file_name or "").lower()
    has_slide_keyword = any(kw in lower_name for kw in SLIDE_KEYWORDS)

    try:
        if not pypdf:
            return PdfProfile.SLIDE_VISUAL if has_slide_keyword else PdfProfile.DIGITAL_BOOK

        reader = pypdf.PdfReader(temp_file_path)
        total_pages = len(reader.pages)
        if total_pages == 0:
            return PdfProfile.SCANNED

        # Sample pages across beginning, middle, and end of the document
        step = max(1, total_pages // max_check_pages)
        sample_indices = list(range(0, total_pages, step))[:max_check_pages]

        extracted_chars_total = 0
        landscape_pages_count = 0
        pages_with_images_count = 0

        for idx in sample_indices:
            page = reader.pages[idx]

            # 1. Aspect Ratio Detection (Landscape check: 16:9 ~ 1.77, 4:3 ~ 1.33)
            try:
                mbox = page.mediabox
                w, h = float(mbox.width), float(mbox.height)
                if h > 0 and (w / h) >= 1.15:
                    landscape_pages_count += 1
            except Exception:
                pass

            # 2. Text Density Extraction
            txt = (page.extract_text() or "").strip()
            extracted_chars_total += len(txt)

            # 3. Embedded Image Detection
            try:
                if len(page.images) > 0:
                    pages_with_images_count += 1
                else:
                    # Fallback check on XObject dictionary
                    resources = page.get("/Resources")
                    if resources and isinstance(resources, dict):
                        xobjects = resources.get("/XObject")
                        if xobjects and isinstance(xobjects, dict):
                            for obj in xobjects.values():
                                if hasattr(obj, "get") and obj.get("/Subtype") == "/Image":
                                    pages_with_images_count += 1
                                    break
            except Exception:
                pass

        sample_size = max(1, len(sample_indices))
        avg_chars_per_page = extracted_chars_total / sample_size
        landscape_ratio = landscape_pages_count / sample_size
        image_page_ratio = pages_with_images_count / sample_size

        logger.info(
            f"PDF Profile inspection for '{file_name}': total_pages={total_pages}, "
            f"avg_chars={avg_chars_per_page:.1f}, landscape_ratio={landscape_ratio:.2f}, "
            f"image_ratio={image_page_ratio:.2f}, keyword_match={has_slide_keyword}"
        )

        # A. Scanned Check: Virtually no digital text across sampled pages
        if extracted_chars_total < 40 and (image_page_ratio > 0.4 or total_pages <= 3):
            return PdfProfile.SCANNED

        # B. Slide / Visual Check:
        #    1. Majority landscape orientation (Powerpoint / Keynote decks)
        #    2. Filename keyword match combined with low-to-medium text density or images
        #    3. High image presence combined with low text density (< 350 chars/page)
        if landscape_ratio >= 0.5:
            return PdfProfile.SLIDE_VISUAL

        if has_slide_keyword and (image_page_ratio > 0.15 or avg_chars_per_page < 550):
            return PdfProfile.SLIDE_VISUAL

        if image_page_ratio >= 0.4 and avg_chars_per_page < 350:
            return PdfProfile.SLIDE_VISUAL

        # C. Default: Digital Book / Standard Document
        return PdfProfile.DIGITAL_BOOK

    except Exception as e:
        logger.warning(f"Error inspecting PDF profile for '{file_name}' ({e}), defaulting to DIGITAL_BOOK")
        return PdfProfile.SLIDE_VISUAL if has_slide_keyword else PdfProfile.DIGITAL_BOOK


def _fallback_pdf_extraction(temp_file_path: str, start_page: int = 1, end_page: Optional[int] = None) -> str:
    """
    Fallback text extraction using pypdf for a given 1-indexed page range [start_page, end_page].
    """
    try:
        if not pypdf:
            return ""
        reader = pypdf.PdfReader(temp_file_path)
        total_pages = len(reader.pages)
        if total_pages == 0:
            return ""

        actual_end = min(total_pages, end_page) if end_page else total_pages
        text_parts = []
        for i in range(start_page - 1, actual_end):
            page = reader.pages[i]
            txt = page.extract_text()
            if txt and txt.strip():
                text_parts.append(f"## Page {i + 1}\n\n{txt.strip()}")
        if text_parts:
            return "\n\n".join(text_parts)
    except Exception as err:
        logger.warning(f"pypdf fallback extraction failed for pages {start_page}-{end_page}: {err}")
    return ""


def _run_docling_conversion_batch(
    temp_file_path: str,
    profile: str = PdfProfile.DIGITAL_BOOK,
    uow=None,
    task_id: Optional[UUID] = None
) -> str:
    """
    Converts a PDF file using Docling with the optimal profile converter and batch sizing.
    Reports incremental progress to the database, supports batch-level graceful degradation,
    and runs garbage collection between batches to prevent memory exhaustion (OOM).
    """
    converter = _get_converter_for_profile(profile)
    batch_size = BATCH_SIZE_BY_PROFILE.get(profile, 40)

    total_pages = 1
    try:
        if pypdf:
            reader = pypdf.PdfReader(temp_file_path)
            total_pages = max(1, len(reader.pages))
    except Exception as e:
        logger.warning(f"Could not determine total pages with pypdf: {e}")

    # Single-pass conversion for short documents
    if total_pages <= batch_size:
        logger.info(f"Processing PDF ({total_pages} pages, profile={profile}) in single pass")
        res = converter.convert(temp_file_path)
        if uow and task_id:
            try:
                uow.ingestion_tasks.update_task_progress(task_id, IngestionTaskStatus.PARSING, 40.0)
                uow.commit()
            except Exception as prog_err:
                logger.debug(f"Failed to update single-pass parse progress: {prog_err}")
        return res.export_to_markdown() if hasattr(res, "export_to_markdown") else res.document.export_to_markdown()

    # Multi-batch conversion for larger documents
    logger.info(f"Processing PDF ({total_pages} pages, profile={profile}) in batches of {batch_size} pages")
    markdown_sections = []

    for start_page in range(1, total_pages + 1, batch_size):
        end_page = min(start_page + batch_size - 1, total_pages)
        logger.info(f"Converting PDF batch: pages {start_page} to {end_page} of {total_pages} (profile={profile})")

        batch_md = None
        try:
            res = converter.convert(temp_file_path, page_range=(start_page, end_page))
            batch_md = res.export_to_markdown() if hasattr(res, "export_to_markdown") else res.document.export_to_markdown()
        except Exception as batch_err:
            logger.warning(
                f"Docling batch failed for pages {start_page}-{end_page}: {batch_err}. "
                f"Falling back gracefully to pypdf for this batch."
            )
            batch_md = _fallback_pdf_extraction(temp_file_path, start_page=start_page, end_page=end_page)

        if batch_md and batch_md.strip():
            markdown_sections.append(batch_md.strip())

        # Real-time incremental progress update in DB: Parse phase is [10.0% -> 40.0%]
        if uow and task_id:
            try:
                batch_pct = 10.0 + (end_page / total_pages) * 30.0
                uow.ingestion_tasks.update_task_progress(
                    task_id,
                    IngestionTaskStatus.PARSING,
                    round(batch_pct, 1)
                )
                uow.commit()
            except Exception as prog_err:
                logger.debug(f"Failed to update incremental parse progress: {prog_err}")

        # Explicit memory cleanup after each batch
        _free_memory()

    return "\n\n".join(markdown_sections)


def _run_docling_generic_conversion(temp_file_path: str) -> str:
    """Converts non-PDF formats (e.g., DOCX) using Docling fast converter."""
    converter = _get_fast_converter()
    res = converter.convert(temp_file_path)
    return res.export_to_markdown() if hasattr(res, "export_to_markdown") else res.document.export_to_markdown()


@track_step_duration("parse")
async def parse_handler(
    uow,
    document_id: UUID,
    project_id: UUID,
    pipeline_state,
    task_id: Optional[UUID] = None
) -> Dict[str, Any]:
    """
    Tier 5 Ingestion Pipeline Handler for document parsing.
    Supports intelligent PDF profiling (Digital Book / Slide Visual / Scanned),
    bitmap diagram OCR, adaptive batch sizing, and an automated Quality Gate with
    self-healing escalation feedback loops.
    """
    document = uow.documents.get(document_id)

    if not document:
        raise ValueError(f"Document {document_id} not found")

    markdown_content = None
    assessment: Optional[QualityAssessment] = None
    attempt_history = []

    file_content = document.file_content
    if document.is_compressed and file_content:
        try:
            file_content = decompress_data(file_content)
            logger.info(f"Decompressed file content for {document.file_name}")
        except Exception as e:
            logger.error(f"Decompression failed for {document.file_name}: {str(e)}")
            markdown_content = f"# {document.file_name}\n\n[Error decompressing file: {str(e)}]"
            document.markdown_content = markdown_content
            uow.commit()
            return {}

    file_size_bytes = len(file_content) if file_content else 0
    file_ext = os.path.splitext(document.file_name)[1].lower()

    if file_ext in ('.txt', '.md'):
        if file_content:
            try:
                markdown_content = file_content.decode('utf-8')
            except UnicodeDecodeError:
                markdown_content = file_content.decode('latin-1')

            # Evaluate quality for text files
            assessment = evaluate_parse_quality(
                markdown_content=markdown_content or "",
                total_pages=1,
                file_size_bytes=file_size_bytes,
                current_profile="TEXT"
            )

    elif file_ext in ('.pdf', '.docx'):
        if file_content:
            temp_file_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=file_ext
                ) as temp_file:
                    temp_file.write(file_content)
                    temp_file_path = temp_file.name

                if file_ext == '.pdf':
                    # Determine total pages
                    total_pages = 1
                    try:
                        if pypdf:
                            reader = pypdf.PdfReader(temp_file_path)
                            total_pages = max(1, len(reader.pages))
                    except Exception as pg_err:
                        logger.warning(f"Could not count total pages for '{document.file_name}': {pg_err}")

                    # Multi-criteria Intelligent PDF Profiler
                    initial_profile = await asyncio.to_thread(_detect_pdf_profile, temp_file_path, document.file_name)
                    logger.info(f"Document {document.file_name} initial profile: '{initial_profile}'")

                    # Self-Healing Escalation Feedback Loop (up to 3 attempts)
                    current_profile = initial_profile
                    max_attempts = 3

                    for attempt in range(max_attempts):
                        logger.info(
                            f"Parse attempt {attempt + 1}/{max_attempts} for '{document.file_name}' "
                            f"using profile '{current_profile}'"
                        )

                        markdown_content = await asyncio.to_thread(
                            _run_docling_conversion_batch,
                            temp_file_path,
                            current_profile,
                            uow,
                            task_id
                        )

                        # Quality Gate verification
                        assessment = evaluate_parse_quality(
                            markdown_content=markdown_content or "",
                            total_pages=total_pages,
                            file_size_bytes=file_size_bytes,
                            current_profile=current_profile
                        )

                        attempt_history.append({
                            "attempt": attempt + 1,
                            "profile": current_profile,
                            "score": assessment.quality_score,
                            "action": assessment.escalation_action,
                            "chars": assessment.total_chars,
                            "density": assessment.text_density,
                        })

                        if assessment.is_acceptable:
                            logger.info(
                                f"Quality Gate PASSED on attempt {attempt + 1} for '{document.file_name}' "
                                f"(score={assessment.quality_score:.2f}, chars={assessment.total_chars})"
                            )
                            break

                        # Process self-healing escalation directives
                        if assessment.escalation_action == EscalationAction.ESCALATE_TO_SLIDE_OCR and current_profile != PdfProfile.SLIDE_VISUAL:
                            logger.warning(
                                f"Quality Gate triggered ESCALATE_TO_SLIDE_OCR for '{document.file_name}'. "
                                f"Escalating to Bitmap Diagram OCR..."
                            )
                            current_profile = PdfProfile.SLIDE_VISUAL
                            continue
                        elif assessment.escalation_action == EscalationAction.ESCALATE_TO_FULL_OCR and current_profile != PdfProfile.SCANNED:
                            logger.warning(
                                f"Quality Gate triggered ESCALATE_TO_FULL_OCR for '{document.file_name}'. "
                                f"Escalating to Full Page OCR..."
                            )
                            current_profile = PdfProfile.SCANNED
                            continue
                        elif assessment.escalation_action == EscalationAction.FALLBACK_PYPDF:
                            logger.warning(
                                f"Quality Gate triggered FALLBACK_PYPDF for '{document.file_name}'. "
                                f"Switching to direct pypdf text extraction..."
                            )
                            fallback_text = await asyncio.to_thread(_fallback_pdf_extraction, temp_file_path)
                            if fallback_text and len(fallback_text.strip()) > len(markdown_content or ""):
                                markdown_content = fallback_text
                                assessment = evaluate_parse_quality(
                                    markdown_content=markdown_content,
                                    total_pages=total_pages,
                                    file_size_bytes=file_size_bytes,
                                    current_profile="PYPDF_FALLBACK"
                                )
                            break
                        else:
                            logger.info(
                                f"No further escalation path for '{document.file_name}'. "
                                f"Proceeding with best extraction result."
                            )
                            break
                else:
                    # Generic format (e.g. DOCX)
                    markdown_content = await asyncio.to_thread(
                        _run_docling_generic_conversion,
                        temp_file_path
                    )
                    assessment = evaluate_parse_quality(
                        markdown_content=markdown_content or "",
                        total_pages=1,
                        file_size_bytes=file_size_bytes,
                        current_profile="DOCX"
                    )

                logger.info(f"Successfully parsed {document.file_name} ({len(markdown_content or '')} chars)")

            except Exception as e:
                logger.error(f"Docling parsing failed for {document.file_name}: {str(e)}")
                if file_ext == '.pdf':
                    fallback_text = await asyncio.to_thread(_fallback_pdf_extraction, temp_file_path)
                    if fallback_text:
                        markdown_content = fallback_text
                        assessment = evaluate_parse_quality(
                            markdown_content=markdown_content,
                            total_pages=1,
                            file_size_bytes=file_size_bytes,
                            current_profile="PYPDF_FALLBACK"
                        )
                        logger.info(f"Used pypdf fallback extraction after exception for {document.file_name} ({len(markdown_content)} chars)")
                    else:
                        markdown_content = f"# {document.file_name}\n\n[Error parsing file: {str(e)}]"
                else:
                    markdown_content = f"# {document.file_name}\n\n[Error parsing file: {str(e)}]"

            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.unlink(temp_file_path)
                    except Exception as clean_err:
                        logger.warning(f"Failed to delete temp file {temp_file_path}: {str(clean_err)}")
                _free_memory()
    else:
        markdown_content = f"# {document.file_name}\n\n[Unsupported file type]"

    document.markdown_content = markdown_content

    # Save Quality Assessment and Profiling metadata to document.processing_metadata
    meta = document.processing_metadata or {}
    if not isinstance(meta, dict):
        meta = {}

    if assessment:
        meta["quality_score"] = assessment.quality_score
        meta["text_density"] = assessment.text_density
        meta["valid_char_ratio"] = assessment.valid_char_ratio
        meta["quality_warnings"] = assessment.warnings
        meta["is_quality_acceptable"] = assessment.is_acceptable
        meta["escalation_history"] = attempt_history
        if not assessment.is_acceptable:
            document.has_partial_failures = True

    meta["final_parse_profile"] = current_profile if file_ext == '.pdf' else 'GENERIC'
    document.processing_metadata = meta

    uow.commit()

    logger.info(
        f"Parsed document {document_id} to markdown ({len(markdown_content or '')} chars, "
        f"quality_score={meta.get('quality_score', 'N/A')})"
    )

    return {}