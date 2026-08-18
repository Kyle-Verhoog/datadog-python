"""LLM Observability evaluations.

Two halves, and they need different credentials:

  * submitting evaluation metrics against spans your app produced needs only
    an api key (plus an agent, or agentless mode)::

        DD_API_KEY=... python examples/evals.py

  * datasets and experiments talk to the Datadog API directly and also need
    an app key::

        DD_API_KEY=... DD_APP_KEY=... python examples/evals.py
"""

import os

from datadog import DDClient, DDConfig
from datadog.llmobs import BaseEvaluator, EvaluatorContext, EvaluatorResult
from datadog.llmobs import StringCheckEvaluator

ddcfg = DDConfig(
    service="evals-demo",
    env="dev",
    version="0.0.1",
    llmobs_enabled=True,
    llmobs_project_name="evals-demo",
    # llmobs_app_key="...",       # or DD_APP_KEY, needed below the fold
    # llmobs_agentless_enabled=True,
)
ddclient = DDClient(config=ddcfg)


# -- evaluating spans as they happen ---------------------------------------
# metric_type is inferred from the value and the evaluation attaches to the
# span currently being traced, so scoring a workflow is a one-liner.


@ddclient.workflow(name="rag.answer")
def answer(question: str) -> str:
    output = "Scranton is in Pennsylvania."
    ddclient.annotate(input_data=question, output_data=output)

    ddclient.submit_evaluation("relevance", 0.92)  # score
    ddclient.submit_evaluation("tone", "formal")  # categorical
    ddclient.submit_evaluation(  # boolean, with the reasoning behind it
        "grounded",
        True,
        assessment="pass",
        reasoning="every claim appears in the retrieved docs",
        tags={"evaluator": "self"},
    )
    return output


# A span from another process can be joined after the fact by handing back
# the dict export_span() produced, or by a tag the span carries:
#
#   ddclient.submit_evaluation("thumbs_up", True, span=exported)
#   ddclient.submit_evaluation(
#       "thumbs_up", True, span_with_tag_value={"tag_key": "request_id",
#                                               "tag_value": "abc123"}
#   )


# -- experiments -----------------------------------------------------------
# An experiment runs a task over every record of a dataset and scores the
# results with evaluators. Evaluators are plain callables or BaseEvaluator
# subclasses; ddtrace ships a handful of built-ins.


class AnswerLength(BaseEvaluator):
    def __init__(self, limit: int = 80):
        super().__init__(name="answer_length")
        self.limit = limit

    def evaluate(self, context: EvaluatorContext):
        length = len(str(context.output_data))
        return EvaluatorResult(
            value=length,
            assessment="pass" if length <= self.limit else "fail",
            reasoning="%d characters (limit %d)" % (length, self.limit),
        )


def task(input_data, config):
    return "%s is in Pennsylvania." % input_data["city"]


def run_experiment():
    dataset = ddclient.create_dataset(
        name="cities",
        description="where are these places",
        records=[
            {
                "input_data": {"city": "Scranton"},
                "expected_output": "Scranton is in Pennsylvania.",
            },
            {
                "input_data": {"city": "Bethlehem"},
                "expected_output": "Bethlehem is in Pennsylvania.",
            },
        ],
    )

    result = ddclient.run_experiment(
        name="city-lookup",
        task=task,
        dataset=dataset,
        evaluators=[AnswerLength(), StringCheckEvaluator(operation="eq")],
    )
    return result


if __name__ == "__main__":
    print(answer("Where is Scranton?"))

    if os.getenv("DD_APP_KEY"):
        print(run_experiment())
    else:
        print("set DD_APP_KEY to also run the experiment half of this example")

    ddclient.flush()
