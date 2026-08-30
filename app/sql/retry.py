"""
Auto-Retry Engine — feeds SQL errors back to the LLM for self-correction.

When a generated SQL query fails execution:
  1. Captures the database error message
  2. Sends the error + original question + schema back to the LLM service
  3. Asks for a corrected query (up to max_retry_attempts)
  4. Re-validates and re-executes the corrected query

The whole loop is asynchronous: LLM calls are awaited and the blocking database
driver is dispatched to a worker thread, so a slow retry never stalls the
FastAPI event loop for other in-flight requests.
"""

import asyncio
from dataclasses import dataclass, field

from loguru import logger

from app.config import settings
from app.llm.service import llm_service
from app.sql.validator import validate_sql, ValidationResult
from app.sql.executor import execute_query, ExecutionResult


@dataclass
class RetryAttempt:
    """Record of a single retry attempt."""
    attempt_number: int
    original_sql: str
    error_message: str
    corrected_sql: str
    validation_result: ValidationResult | None = None
    execution_result: ExecutionResult | None = None
    succeeded: bool = False


@dataclass
class RetryResult:
    """Result of the retry pipeline."""
    final_result: ExecutionResult | None = None
    final_sql: str = ""
    attempts: list[RetryAttempt] = field(default_factory=list)
    total_retries: int = 0
    succeeded: bool = False


async def retry_failed_query(
    original_sql: str,
    original_error: str,
    question: str,
    schema_context: str,
    known_tables: set[str] | None = None,
) -> RetryResult:
    """
    Attempt to fix a failed SQL query using the LLM service.

    Args:
        original_sql: The SQL that failed
        original_error: The error message from execution
        question: The original user question
        schema_context: The schema context string
        known_tables: Set of valid table names for validation

    Returns:
        RetryResult with the final outcome and retry history
    """
    result = RetryResult()
    current_sql = original_sql
    current_error = original_error

    max_retries = settings.max_retry_attempts

    for attempt_num in range(1, max_retries + 1):
        logger.info(
            f"🔄 Retry attempt {attempt_num}/{max_retries}: "
            f"Error was: {current_error[:100]}..."
        )

        attempt = RetryAttempt(
            attempt_number=attempt_num,
            original_sql=current_sql,
            error_message=current_error,
            corrected_sql="",
        )

        # Ask the LLM service to fix the query
        try:
            generation = await llm_service.correct_sql(
                schema_context=schema_context,
                question=question,
                failed_sql=current_sql,
                error_message=current_error,
            )
            corrected_sql = generation.sql
        except Exception as e:
            logger.error(f"LLM error during retry: {e}")
            attempt.corrected_sql = ""
            result.attempts.append(attempt)
            break

        attempt.corrected_sql = corrected_sql

        # Validate the corrected SQL
        validation = validate_sql(corrected_sql, known_tables)
        attempt.validation_result = validation

        if not validation.is_valid:
            logger.warning(
                f"  Retry {attempt_num}: Validation failed: {validation.errors}"
            )
            current_sql = corrected_sql
            current_error = f"Validation error: {'; '.join(validation.errors)}"
            result.attempts.append(attempt)
            continue

        # Execute the corrected SQL off the event loop (blocking DB driver)
        exec_result = await asyncio.to_thread(execute_query, validation.sql)
        attempt.execution_result = exec_result

        if exec_result.success:
            logger.info(
                f"✅ Retry {attempt_num} succeeded! "
                f"{exec_result.row_count} rows returned"
            )
            attempt.succeeded = True
            result.final_result = exec_result
            result.final_sql = validation.sql
            result.succeeded = True
            result.attempts.append(attempt)
            result.total_retries = attempt_num
            return result

        # Still failing — try again
        current_sql = validation.sql
        current_error = exec_result.error or "Unknown execution error"
        result.attempts.append(attempt)

    result.total_retries = len(result.attempts)
    logger.warning(
        f"❌ All {max_retries} retry attempts failed for: '{question[:60]}...'"
    )
    return result
