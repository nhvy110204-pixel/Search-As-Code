import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


class EscalationAction:
    """Escalation directives issued by Quality Gate upon detecting sub-optimal extraction."""
    NONE = "NONE"
    ESCALATE_TO_SLIDE_OCR = "ESCALATE_TO_SLIDE_OCR"   # Upgrade to Bitmap Diagram OCR
    ESCALATE_TO_FULL_OCR = "ESCALATE_TO_FULL_OCR"     # Upgrade to Full Page OCR rasterization
    FALLBACK_PYPDF = "FALLBACK_PYPDF"                 # Fallback to direct pypdf text extraction
    REJECT = "REJECT"                                 # Corrupt or unparseable document


# Regex recognizing valid Latin, Vietnamese, standard punctuation, math/code symbols, and whitespace
VALID_CHAR_PATTERN = re.compile(
    r"[\w\s\.,;:!\?\-\(\)\[\]\{\}\"\'\/\\@#\$%\^&\*\+=<>~`|_\u00C0-\u1EF9\u2010-\u2026]",
    re.UNICODE
)


@dataclass
class QualityAssessment:
    """
    Quality Gate Assessment Report for extracted document content.
    Contains quantitative metrics, composite quality score, diagnostic warnings,
    and recommended escalation action for self-healing loops.
    """
    is_acceptable: bool
    quality_score: float              # Normalized composite quality score (0.0 - 1.0)
    text_density: float               # Average characters extracted per page
    valid_char_ratio: float           # Ratio of meaningful/printable characters (0.0 - 1.0)
    warnings: List[str] = field(default_factory=list)
    escalation_action: str = EscalationAction.NONE
    size_to_text_ratio: float = 0.0   # File size (bytes) per extracted character
    total_pages: int = 1
    total_chars: int = 0

    def to_dict(self) -> dict:
        return {
            "is_acceptable": self.is_acceptable,
            "quality_score": round(self.quality_score, 2),
            "text_density": round(self.text_density, 1),
            "valid_char_ratio": round(self.valid_char_ratio, 3),
            "warnings": self.warnings,
            "escalation_action": self.escalation_action,
            "size_to_text_ratio": round(self.size_to_text_ratio, 1),
            "total_pages": self.total_pages,
            "total_chars": self.total_chars,
        }


def evaluate_parse_quality(
    markdown_content: str,
    total_pages: int = 1,
    file_size_bytes: int = 0,
    current_profile: str = "DIGITAL_BOOK"
) -> QualityAssessment:
    """
    Evaluates the quality of extracted text using 3 core quantitative metrics:
    1. Text Density (Chars / Page)
    2. Valid Character Ratio (Gibberish / Unicode / Replacement character check)
    3. Size-to-Text Ratio (Byte size vs extracted text length)

    Returns a QualityAssessment with composite score and escalation recommendation.
    """
    clean_text = (markdown_content or "").strip()
    total_chars = len(clean_text)
    pages = max(1, total_pages)
    text_density = total_chars / pages
    file_size_mb = file_size_bytes / (1024 * 1024) if file_size_bytes > 0 else 0.0

    warnings: List[str] = []

    # 1. Total Emptiness Check
    if total_chars == 0:
        warnings.append("Văn bản bóc tách hoàn toàn rỗng.")
        if current_profile == "DIGITAL_BOOK":
            action = EscalationAction.ESCALATE_TO_SLIDE_OCR
        elif current_profile == "SLIDE_VISUAL":
            action = EscalationAction.ESCALATE_TO_FULL_OCR
        elif current_profile == "SCANNED":
            action = EscalationAction.FALLBACK_PYPDF
        else:
            action = EscalationAction.REJECT

        return QualityAssessment(
            is_acceptable=False,
            quality_score=0.0,
            text_density=0.0,
            valid_char_ratio=0.0,
            warnings=warnings,
            escalation_action=action,
            size_to_text_ratio=float(file_size_bytes),
            total_pages=pages,
            total_chars=0
        )

    # 2. Valid Character Ratio & Gibberish / Unicode Check
    # Check for Unicode Replacement Character \ufffd or malformed binary sequences
    replacement_char_count = clean_text.count("\ufffd")
    valid_chars_count = len(VALID_CHAR_PATTERN.findall(clean_text))
    valid_char_ratio = valid_chars_count / total_chars if total_chars > 0 else 0.0
    replacement_ratio = replacement_char_count / total_chars if total_chars > 0 else 0.0

    if replacement_ratio > 0.03:
        warnings.append(f"Phát hiện lỗi mã hóa font ({replacement_char_count} ký tự replacement \\ufffd).")

    if valid_char_ratio < 0.75:
        warnings.append(f"Tỷ lệ ký tự hợp lệ thấp ({valid_char_ratio:.1%}), văn bản có thể chứa mã rác/nhị phân.")

    # 3. Size-to-Text Ratio
    size_to_text_ratio = file_size_bytes / max(1, total_chars)
    if file_size_mb >= 3.0 and total_chars < 300:
        warnings.append(
            f"Dung lượng tệp lớn ({file_size_mb:.1f}MB) nhưng chỉ trích xuất được {total_chars} ký tự "
            f"(nghi ngờ tài liệu chứa nhiều sơ đồ/hình ảnh chưa được quét OCR)."
        )

    # 4. Text Density Thresholds per Profile
    if current_profile == "DIGITAL_BOOK" and text_density < 120.0:
        warnings.append(f"Mật độ chữ thấp cho tài liệu dạng sách ({text_density:.1f} ký tự/trang).")
    elif current_profile == "SLIDE_VISUAL" and text_density < 30.0:
        warnings.append(f"Mật độ chữ thấp cho slide bài giảng ({text_density:.1f} ký tự/trang).")
    elif current_profile == "SCANNED" and text_density < 40.0:
        warnings.append(f"Mật độ nhận diện OCR thấp ({text_density:.1f} ký tự/trang).")

    # 5. Determine Escalation Action
    escalation_action = EscalationAction.NONE

    if valid_char_ratio < 0.65 or replacement_ratio > 0.10:
        # Heavily corrupted font mapping -> Fallback to raw pypdf extraction
        escalation_action = EscalationAction.FALLBACK_PYPDF
    elif file_size_mb >= 3.0 and total_chars < 300:
        if current_profile == "DIGITAL_BOOK":
            escalation_action = EscalationAction.ESCALATE_TO_SLIDE_OCR
        elif current_profile == "SLIDE_VISUAL":
            escalation_action = EscalationAction.ESCALATE_TO_FULL_OCR
    elif current_profile == "DIGITAL_BOOK" and text_density < 100.0:
        escalation_action = EscalationAction.ESCALATE_TO_SLIDE_OCR
    elif current_profile == "SLIDE_VISUAL" and text_density < 25.0 and total_chars < 150:
        escalation_action = EscalationAction.ESCALATE_TO_FULL_OCR

    # 6. Calculate Composite Quality Score (0.0 - 1.0)
    density_target = 150.0 if current_profile == "DIGITAL_BOOK" else 60.0
    density_factor = min(1.0, text_density / density_target)
    validity_factor = valid_char_ratio * (1.0 - min(1.0, replacement_ratio * 5.0))

    composite_score = round(0.5 * validity_factor + 0.5 * density_factor, 2)

    # Acceptance threshold
    is_acceptable = (
        composite_score >= 0.40
        and valid_char_ratio >= 0.70
        and total_chars >= 40
        and escalation_action == EscalationAction.NONE
    )

    logger.debug(
        f"Quality Gate evaluated: score={composite_score}, is_acceptable={is_acceptable}, "
        f"density={text_density:.1f}, valid_ratio={valid_char_ratio:.2f}, action={escalation_action}"
    )

    return QualityAssessment(
        is_acceptable=is_acceptable,
        quality_score=composite_score,
        text_density=text_density,
        valid_char_ratio=valid_char_ratio,
        warnings=warnings,
        escalation_action=escalation_action,
        size_to_text_ratio=size_to_text_ratio,
        total_pages=pages,
        total_chars=total_chars,
    )
