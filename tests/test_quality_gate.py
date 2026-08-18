import os
import sys
import unittest

# Ensure backend root is in Python module path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.rag.ingestion.quality_gate import (
    QualityAssessment,
    evaluate_parse_quality,
    EscalationAction,
)


class TestQualityGate(unittest.TestCase):
    """Unit test suite for Quality Gate metrics, evaluation, and escalation logic."""

    def test_evaluate_acceptable_document(self):
        """Standard high-density clean text should easily pass the Quality Gate."""
        content = """
        # System Overview
        The Search-as-Code (SaC) engine translates natural language queries into executable Python code.
        The execution sandbox provides isolated environment with zero network access and deterministic timeouts.
        This provides high accuracy and grounded citations.
        """ * 10

        assessment = evaluate_parse_quality(
            markdown_content=content,
            total_pages=2,
            file_size_bytes=50000,
            current_profile="DIGITAL_BOOK"
        )

        self.assertTrue(assessment.is_acceptable)
        self.assertGreater(assessment.quality_score, 0.70)
        self.assertGreater(assessment.text_density, 500)
        self.assertGreater(assessment.valid_char_ratio, 0.95)
        self.assertEqual(assessment.escalation_action, EscalationAction.NONE)

    def test_evaluate_empty_document_escalation(self):
        """Empty text should trigger immediate escalation from DIGITAL_BOOK to SLIDE_VISUAL."""
        assessment = evaluate_parse_quality(
            markdown_content="",
            total_pages=5,
            file_size_bytes=2000000,
            current_profile="DIGITAL_BOOK"
        )

        self.assertFalse(assessment.is_acceptable)
        self.assertEqual(assessment.quality_score, 0.0)
        self.assertEqual(assessment.total_chars, 0)
        self.assertEqual(assessment.escalation_action, EscalationAction.ESCALATE_TO_SLIDE_OCR)
        self.assertIn("Văn bản bóc tách hoàn toàn rỗng.", assessment.warnings)

    def test_evaluate_slide_visual_empty_escalates_to_full_ocr(self):
        """Empty text in SLIDE_VISUAL should escalate to FULL_OCR."""
        assessment = evaluate_parse_quality(
            markdown_content="   ",
            total_pages=10,
            file_size_bytes=5000000,
            current_profile="SLIDE_VISUAL"
        )

        self.assertFalse(assessment.is_acceptable)
        self.assertEqual(assessment.escalation_action, EscalationAction.ESCALATE_TO_FULL_OCR)

    def test_evaluate_font_corruption_triggers_fallback(self):
        """Severe font encoding errors with \\ufffd should trigger FALLBACK_PYPDF."""
        corrupted_content = "Document header \ufffd\ufffd\ufffd\ufffd\ufffd \ufffd\ufffd\ufffd invalid font mapping" * 20

        assessment = evaluate_parse_quality(
            markdown_content=corrupted_content,
            total_pages=1,
            file_size_bytes=100000,
            current_profile="DIGITAL_BOOK"
        )

        self.assertFalse(assessment.is_acceptable)
        self.assertEqual(assessment.escalation_action, EscalationAction.FALLBACK_PYPDF)
        self.assertTrue(any("lỗi mã hóa font" in w for w in assessment.warnings))

    def test_evaluate_heavy_file_with_scant_text(self):
        """Heavy file (10MB) with only 80 chars should warn about missing diagram OCR."""
        scant_content = "Slide 1 Title: Architecture"

        assessment = evaluate_parse_quality(
            markdown_content=scant_content,
            total_pages=10,
            file_size_bytes=10 * 1024 * 1024, # 10MB
            current_profile="DIGITAL_BOOK"
        )

        self.assertFalse(assessment.is_acceptable)
        self.assertEqual(assessment.escalation_action, EscalationAction.ESCALATE_TO_SLIDE_OCR)
        self.assertTrue(any("Dung lượng tệp lớn" in w for w in assessment.warnings))

    def test_quality_assessment_to_dict(self):
        """QualityAssessment must serialize cleanly to a dictionary."""
        assessment = QualityAssessment(
            is_acceptable=True,
            quality_score=0.88,
            text_density=350.5,
            valid_char_ratio=0.98,
            warnings=["Minor warning"],
            escalation_action=EscalationAction.NONE,
            size_to_text_ratio=120.4,
            total_pages=2,
            total_chars=701
        )

        d = assessment.to_dict()
        self.assertEqual(d["is_acceptable"], True)
        self.assertEqual(d["quality_score"], 0.88)
        self.assertEqual(d["text_density"], 350.5)
        self.assertEqual(d["warnings"], ["Minor warning"])


if __name__ == "__main__":
    unittest.main()
