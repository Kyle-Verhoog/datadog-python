"""LLM Observability example.

Run with::

    DD_API_KEY=... OPENAI_API_KEY=... python examples/llmobs.py

Set ``DD_LLMOBS_AGENTLESS_ENABLED=1`` (or ``llmobs_agentless_enabled=True``)
if you don't have a Datadog agent running locally — traces will be sent
directly to Datadog.
"""
from datadog import DDClient, DDConfig


ddcfg = DDConfig(
    service="llmobs-demo",
    env="dev",
    version="0.0.1",
    llmobs_enabled=True,
    # If you don't run a local agent, also pass:
    # llmobs_agentless_enabled=True,
)
ddclient = DDClient(config=ddcfg)


@ddclient.workflow(name="rag.answer")
def answer(question: str) -> str:
    docs = retrieve(question)
    return generate(question, docs)


@ddclient.retrieval(name="vector_search")
def retrieve(question: str):
    # Pretend this hits a vector DB.
    docs = [{"id": "doc-1", "text": "Scranton is in Pennsylvania."}]
    ddclient.annotate(
        input_data=question,
        output_data=docs,
        metadata={"k": 1},
    )
    return docs


@ddclient.llm(model_name="gpt-4o-mini", model_provider="openai", name="answer.generate")
def generate(question: str, docs):
    # The openai integration auto-instruments client.chat.completions.create
    # when LLM Obs is enabled with llmobs_integrations_enabled=True (default).
    from openai import OpenAI

    resp = OpenAI().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Answer using the provided docs."},
            {"role": "user", "content": f"Q: {question}\nDocs: {docs}"},
        ],
    )
    return resp.choices[0].message.content


if __name__ == "__main__":
    print(answer("Where is Scranton?"))
    ddclient.flush()
