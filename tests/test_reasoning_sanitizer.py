"""
Reasoning-leakage tests.

These are the regression tests for the single most important safety property of
the migration: nothing the model thinks may reach the browser. Each case feeds a
shape of reasoning output that ``openai/gpt-oss-20b`` (or a future reasoning
model) can plausibly emit and asserts that only the final answer survives.
"""

import pytest

from app.llm.sanitizer import contains_reasoning_markers, strip_reasoning

FINAL_ANSWER = "SELECT SUM(total_amount) AS revenue FROM fact_sales LIMIT 1"


class TestBalancedTags:
    def test_think_block_is_removed(self):
        raw = f"<think>The user wants revenue. I should sum total_amount.</think>\n{FINAL_ANSWER}"
        result = strip_reasoning(raw)
        assert result.text == FINAL_ANSWER
        assert result.was_modified
        assert "user wants revenue" not in result.text

    @pytest.mark.parametrize(
        "tag",
        ["think", "thinking", "reasoning", "analysis", "reflection", "scratchpad"],
    )
    def test_every_known_tag_is_removed(self, tag):
        raw = f"<{tag}>hidden deliberation</{tag}>{FINAL_ANSWER}"
        assert strip_reasoning(raw).text == FINAL_ANSWER

    def test_tag_matching_is_case_insensitive(self):
        raw = f"<THINK>deliberation</Think>\n{FINAL_ANSWER}"
        assert strip_reasoning(raw).text == FINAL_ANSWER

    def test_multiple_blocks_are_all_removed(self):
        raw = (
            "<think>first thought</think>"
            "SELECT 1"
            "<think>second thought</think>"
        )
        cleaned = strip_reasoning(raw).text
        assert cleaned == "SELECT 1"
        assert "thought" not in cleaned

    def test_multiline_block_is_removed(self):
        raw = "<thinking>\nline one\nline two\nline three\n</thinking>\n\n" + FINAL_ANSWER
        assert strip_reasoning(raw).text == FINAL_ANSWER


class TestTruncatedAndOrphanTags:
    def test_unterminated_open_tag_drops_the_tail(self):
        raw = f"{FINAL_ANSWER}\n<think>I am still deliberating and got cut off"
        cleaned = strip_reasoning(raw).text
        assert cleaned == FINAL_ANSWER
        assert "deliberating" not in cleaned

    def test_orphan_close_tag_drops_the_head(self):
        raw = f"I considered several joins.</think>\n{FINAL_ANSWER}"
        cleaned = strip_reasoning(raw).text
        assert cleaned == FINAL_ANSWER
        assert "considered" not in cleaned

    def test_reasoning_only_response_becomes_empty(self):
        raw = "<think>Only deliberation here, no answer was produced.</think>"
        result = strip_reasoning(raw)
        assert result.text == ""
        assert result.was_modified


class TestHarmonyChannels:
    def test_final_channel_is_extracted(self):
        raw = (
            "<|start|>assistant<|channel|>analysis<|message|>The schema has "
            "fact_sales, so I will sum total_amount.<|end|>"
            f"<|start|>assistant<|channel|>final<|message|>{FINAL_ANSWER}<|return|>"
        )
        cleaned = strip_reasoning(raw).text
        assert cleaned == FINAL_ANSWER
        assert "schema has" not in cleaned

    def test_analysis_channel_without_final_is_dropped(self):
        raw = "<|channel|>analysis<|message|>internal notes only<|end|>"
        assert strip_reasoning(raw).text == ""

    def test_detokenised_assistantfinal_marker(self):
        raw = f"analysisWe need the revenue total.assistantfinal{FINAL_ANSWER}"
        cleaned = strip_reasoning(raw).text
        assert cleaned == FINAL_ANSWER
        assert "We need" not in cleaned

    def test_stray_control_tokens_are_stripped(self):
        raw = f"<|start|>{FINAL_ANSWER}<|end|>"
        assert strip_reasoning(raw).text == FINAL_ANSWER


class TestCleanInput:
    def test_clean_answer_is_untouched(self):
        result = strip_reasoning(FINAL_ANSWER)
        assert result.text == FINAL_ANSWER
        assert not result.was_modified

    def test_empty_input(self):
        assert strip_reasoning("").text == ""
        assert strip_reasoning(None).text == ""

    def test_prose_answer_survives(self):
        insight = "Revenue grew 12% year over year, driven by the West region."
        assert strip_reasoning(insight).text == insight

    def test_sql_with_comparison_operators_is_not_mistaken_for_a_tag(self):
        sql = "SELECT * FROM t WHERE a < 5 AND b > 3 LIMIT 10"
        assert strip_reasoning(sql).text == sql


class TestMarkerDetection:
    def test_detects_tags(self):
        assert contains_reasoning_markers("<think>x</think>")

    def test_detects_harmony_tokens(self):
        assert contains_reasoning_markers("<|channel|>final<|message|>hi")

    def test_clean_text_has_no_markers(self):
        assert not contains_reasoning_markers(FINAL_ANSWER)

    def test_sanitized_output_never_retains_markers(self):
        samples = [
            f"<think>a</think>{FINAL_ANSWER}",
            f"<|channel|>analysis<|message|>a<|end|><|channel|>final<|message|>{FINAL_ANSWER}",
            f"analysis reasoning assistantfinal {FINAL_ANSWER}",
            f"{FINAL_ANSWER}<think>truncated",
        ]
        for sample in samples:
            assert not contains_reasoning_markers(strip_reasoning(sample).text)
