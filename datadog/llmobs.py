"""Types for writing evaluators, datasets and experiments.

Everything here is re-exported from ddtrace so that user code annotating an
evaluator or building dataset records has a single import surface::

    from datadog.llmobs import EvaluatorContext, EvaluatorResult, LLMJudge

This module is deliberately not imported by ``datadog/__init__.py``: pulling
in ``ddtrace.llmobs`` has a cost, and a client with LLM Obs turned off should
not pay it.
"""

from ddtrace.llmobs import BaseAsyncEvaluator
from ddtrace.llmobs import BaseAsyncSummaryEvaluator
from ddtrace.llmobs import BaseEvaluator
from ddtrace.llmobs import BaseSummaryEvaluator
from ddtrace.llmobs import BooleanStructuredOutput
from ddtrace.llmobs import CategoricalStructuredOutput
from ddtrace.llmobs import Dataset
from ddtrace.llmobs import DatasetRecord
from ddtrace.llmobs import EvaluatorContext
from ddtrace.llmobs import EvaluatorResult
from ddtrace.llmobs import LLMJudge
from ddtrace.llmobs import MultiEvaluatorResult
from ddtrace.llmobs import Prompt
from ddtrace.llmobs import RemoteEvaluator
from ddtrace.llmobs import RemoteEvaluatorError
from ddtrace.llmobs import ScoreStructuredOutput
from ddtrace.llmobs import SummaryEvaluatorContext
from ddtrace.llmobs.evaluators import JSONEvaluator
from ddtrace.llmobs.evaluators import LengthEvaluator
from ddtrace.llmobs.evaluators import RegexMatchEvaluator
from ddtrace.llmobs.evaluators import SemanticSimilarityEvaluator
from ddtrace.llmobs.evaluators import StringCheckEvaluator

__all__ = [
    # writing your own evaluator
    "BaseEvaluator",
    "BaseAsyncEvaluator",
    "BaseSummaryEvaluator",
    "BaseAsyncSummaryEvaluator",
    "EvaluatorContext",
    "EvaluatorResult",
    "MultiEvaluatorResult",
    "SummaryEvaluatorContext",
    # llm-as-a-judge
    "LLMJudge",
    "BooleanStructuredOutput",
    "CategoricalStructuredOutput",
    "ScoreStructuredOutput",
    "RemoteEvaluator",
    "RemoteEvaluatorError",
    # built-in evaluators
    "JSONEvaluator",
    "LengthEvaluator",
    "RegexMatchEvaluator",
    "SemanticSimilarityEvaluator",
    "StringCheckEvaluator",
    # datasets
    "Dataset",
    "DatasetRecord",
    "Prompt",
]
