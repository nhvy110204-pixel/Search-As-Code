import os
import logging
import tempfile
import asyncio
from uuid import UUID
from typing import Dict, Any
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, EasyOcrOptions
from app.core.compression import decompress_data
from app.observability.metrics import track_step_duration

logger = logging.getLogger(__name__)

pdf_pipeline_options = PdfPipelineOptions()
pdf_pipeline_options.do_ocr = True
pdf_pipeline_options.ocr_options = EasyOcrOptions(lang=["en", "vi"])

_docling_converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_pipeline_options)
    }
)


def _run_docling_conversion(temp_file_path: str) -> str:
    result = _docling_converter.convert(temp_file_path)
    if hasattr(result, "export_to_markdown"):
        return result.export_to_markdown()
    return result.document.export_to_markdown()


@track_step_duration("parse")
async def parse_handler(
    uow,
    document_id: UUID,
    project_id: UUID,
    pipeline_state
) -> Dict[str, Any]:
    document = uow.documents.get(document_id)
    
    if not document:
        raise ValueError(f"Document {document_id} not found")
    
    markdown_content = None
    
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
    
    if document.file_name.endswith(('.txt', '.md')):
        if file_content:
            try:
                markdown_content = file_content.decode('utf-8')
            except UnicodeDecodeError:
                markdown_content = file_content.decode('latin-1')
                
    elif document.file_name.endswith(('.pdf', '.docx')):
        if file_content:
            temp_file_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=os.path.splitext(document.file_name)[1]
                ) as temp_file:
                    temp_file.write(file_content)
                    temp_file_path = temp_file.name
                
                markdown_content = await asyncio.to_thread(
                    _run_docling_conversion, 
                    temp_file_path
                )
                
                logger.info(f"Successfully parsed {document.file_name} with Docling via background thread")
                
            except Exception as e:
                logger.error(f"Docling parsing failed for {document.file_name}: {str(e)}")
                markdown_content = f"# {document.file_name}\n\n[Error parsing file: {str(e)}]"
                
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.unlink(temp_file_path)
                    except Exception as clean_err:
                        logger.warning(f"Failed to delete temp file {temp_file_path}: {str(clean_err)}")
    else:
        markdown_content = f"# {document.file_name}\n\n[Unsupported file type]"

    document.markdown_content = markdown_content
    uow.commit()
    
    logger.info(f"Parsed document {document_id} to markdown ({len(markdown_content)} chars)")
    
    return {}