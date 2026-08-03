"""AgentCore Runtime hosting a LangChain multi-agent UAT RAG assistant.

Architecture:
  Main supervisor agent
    -> UAT retrieval agent tool
    -> Test coverage agent tool
    -> Defect triage agent tool

All agents are created with ``langchain.agents.create_agent``. Retrieval is
grounded in PDF files stored under ``uat_documents``.
"""

import logging
import math
import os
import re
from collections import Counter
from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_aws import ChatBedrockConverse
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from document_sources import resolve_document_paths


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
MODEL_ID = os.getenv("MODEL_ID", "amazon.nova-lite-v1:0")
DOCUMENT_DIRECTORY = Path(
    os.getenv("UAT_DOCUMENT_DIRECTORY", Path(__file__).parent / "uat_documents")
)

model = ChatBedrockConverse(
    model_id=MODEL_ID,
    region_name=AWS_REGION,
    temperature=0.1,
    max_tokens=900,
)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _load_chunks() -> list[dict]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=120)
    chunks: list[dict] = []
    pdf_paths = resolve_document_paths(
        DOCUMENT_DIRECTORY,
        s3_bucket=os.getenv("S3_BUCKET") or os.getenv("AWS_S3_BUCKET"),
        s3_prefix=os.getenv("S3_PREFIX") or os.getenv("AWS_S3_PREFIX"),
    )
    for pdf_path in pdf_paths:
        for document in PyPDFLoader(str(pdf_path)).load():
            for split in splitter.split_documents([document]):
                text = split.page_content.strip()
                if text:
                    chunks.append(
                        {
                            "text": text,
                            "source": pdf_path.name,
                            "page": int(split.metadata.get("page", 0)) + 1,
                            "terms": Counter(_tokens(text)),
                        }
                    )
    source_label = "S3" if os.getenv("S3_BUCKET") or os.getenv("AWS_S3_BUCKET") else str(DOCUMENT_DIRECTORY)
    logger.info("Loaded %s UAT chunks from %s", len(chunks), source_label)
    return chunks


UAT_CHUNKS = _load_chunks()


def _search(query: str, limit: int = 5) -> list[dict]:
    query_terms = Counter(_tokens(query))
    if not query_terms or not UAT_CHUNKS:
        return []

    ranked = []
    for chunk in UAT_CHUNKS:
        overlap = sum(
            min(query_count, chunk["terms"].get(term, 0))
            for term, query_count in query_terms.items()
        )
        if overlap:
            length_penalty = math.sqrt(max(len(chunk["terms"]), 1))
            ranked.append((overlap / length_penalty, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in ranked[: max(1, min(limit, 8))]]


@tool
def search_uat_documents(query: str, limit: int = 5) -> str:
    """Search approved UAT PDFs for test cases, requirements, results, defects, and sign-off criteria."""
    results = _search(query, limit)
    if not results:
        return "No matching evidence was found in the UAT document corpus."
    return "\n\n".join(
        f"[Source: {item['source']}, page {item['page']}]\n{item['text']}"
        for item in results
    )


def _last_content(result) -> str:
    content = result["messages"][-1].content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


retrieval_agent = create_agent(
    model=model,
    tools=[search_uat_documents],
    name="uat_retrieval_agent",
    system_prompt=(
        "You are a UAT document retrieval specialist. Always search the UAT PDFs before "
        "answering. Return only claims supported by retrieved text and cite every claim "
        "using [Source: filename, page N]. If evidence is missing, say so explicitly."
    ),
)

coverage_agent = create_agent(
    model=model,
    tools=[search_uat_documents],
    name="uat_coverage_agent",
    system_prompt=(
        "You are a senior UAT test analyst. Search the UAT PDFs, then evaluate scenario "
        "coverage, acceptance criteria, dependencies, evidence, and missing tests. Cite "
        "document evidence with [Source: filename, page N]."
    ),
)

defect_agent = create_agent(
    model=model,
    tools=[search_uat_documents],
    name="uat_defect_agent",
    system_prompt=(
        "You are a UAT defect triage specialist. Search the UAT PDFs, then assess severity, "
        "business impact, reproducibility, workarounds, retest status, and release risk. "
        "Do not invent defect records. Cite document evidence."
    ),
)


@tool("ask_uat_retrieval_agent")
def ask_uat_retrieval_agent(question: str) -> str:
    """Delegate evidence-based questions about UAT requirements, cases, outcomes, and sign-off."""
    result = retrieval_agent.invoke(
        {"messages": [{"role": "user", "content": question}]}
    )
    return _last_content(result)


@tool("ask_uat_coverage_agent")
def ask_uat_coverage_agent(question: str) -> str:
    """Delegate test-coverage, acceptance-criteria, gap-analysis, and readiness assessments."""
    result = coverage_agent.invoke(
        {"messages": [{"role": "user", "content": question}]}
    )
    return _last_content(result)


@tool("ask_uat_defect_agent")
def ask_uat_defect_agent(question: str) -> str:
    """Delegate defect triage, severity, business impact, retest, and release-risk questions."""
    result = defect_agent.invoke(
        {"messages": [{"role": "user", "content": question}]}
    )
    return _last_content(result)


supervisor_agent = create_agent(
    model=model,
    tools=[
        ask_uat_retrieval_agent,
        ask_uat_coverage_agent,
        ask_uat_defect_agent,
    ],
    name="uat_supervisor_agent",
    system_prompt=(
        "You are the main UAT RAG supervisor. Answer only from the UAT PDF corpus. "
        "Delegate factual retrieval to ask_uat_retrieval_agent, coverage/readiness analysis "
        "to ask_uat_coverage_agent, and defect/release-risk analysis to "
        "ask_uat_defect_agent. You may call multiple specialists. Preserve their source "
        "citations in the final answer. If the documents do not contain enough evidence, "
        "state that clearly rather than relying on general knowledge."
    ),
)


@app.entrypoint
def invoke(payload, context=None):
    """AgentCore entry point. Expected payload: {"prompt": "..."}."""
    prompt = str(payload.get("prompt", "")).strip() if isinstance(payload, dict) else ""
    if not prompt:
        return {"error": "Payload must contain a non-empty 'prompt'."}
    if not UAT_CHUNKS:
        return {"error": f"No PDF documents were found under {DOCUMENT_DIRECTORY}."}

    try:
        result = supervisor_agent.invoke(
            {"messages": [{"role": "user", "content": prompt}]}
        )
        return {
            "result": _last_content(result),
            "model_id": MODEL_ID,
            "region": AWS_REGION,
            "document_count": len(resolve_document_paths(
                DOCUMENT_DIRECTORY,
                s3_bucket=os.getenv("S3_BUCKET") or os.getenv("AWS_S3_BUCKET"),
                s3_prefix=os.getenv("S3_PREFIX") or os.getenv("AWS_S3_PREFIX"),
            )),
        }
    except Exception:
        logger.exception("UAT multi-agent RAG execution failed")
        return {"error": "The UAT multi-agent RAG workflow failed."}


if __name__ == "__main__":
    app.run()

