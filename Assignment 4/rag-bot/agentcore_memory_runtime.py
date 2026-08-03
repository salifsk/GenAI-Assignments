"""AgentCore Runtime agent with persistent AgentCore Memory.

Invoke with:
  {
    "prompt": "My UAT release is called Phoenix.",
    "actor_id": "trainer-user-1",
    "session_id": "training-session-00000000000000001"
  }

Reuse the same actor_id and session_id to continue a conversation. AgentCore
Runtime context IDs are used automatically when they are available.
"""

import logging
import os
from typing import Any

from bedrock_agentcore.memory import MemoryClient
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain.agents import create_agent
from langchain_aws import ChatBedrockConverse


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
MODEL_ID = os.getenv("MODEL_ID", "amazon.nova-lite-v1:0")
MEMORY_ARN = os.getenv(
    "AGENTCORE_MEMORY_ARN",
    "arn:aws:bedrock-agentcore:us-east-1:197701154184:memory/memory_new-rpiQUC5mLU",
)
MEMORY_ID = MEMORY_ARN.rsplit("/", 1)[-1]
HISTORY_TURNS = int(os.getenv("MEMORY_HISTORY_TURNS", "20"))

memory_client = MemoryClient(region_name=AWS_REGION)
model = ChatBedrockConverse(
    model_id=MODEL_ID,
    region_name=AWS_REGION,
    temperature=0.1,
    max_tokens=900,
)
agent = create_agent(
    model=model,
    tools=[],
    name="agentcore_memory_agent",
    system_prompt=(
        "You are a helpful UAT assistant with AgentCore Memory. The memory context contains "
        "information previously supplied by the same actor, so you may recall it for that "
        "actor. Use explicit user statements in the memory context as facts. If values "
        "conflict, prefer the newest statement. Never invent information absent from memory."
    ),
)


def _context_value(context: Any, name: str) -> str:
    value = getattr(context, name, None) if context is not None else None
    return str(value).strip() if value else ""


def _message_text(message: dict[str, Any]) -> str:
    """Extract text defensively from the SDK's event message representation."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        text = content.get("text", "")
        return str(text) if text else ""
    return ""


def _langchain_history(turns: list[list[dict[str, Any]]]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    # AgentCore returns the latest turn first. LangChain chat history must be
    # supplied chronologically so that newer facts correctly supersede older ones.
    for turn in reversed(turns):
        for message in turn:
            role = str(message.get("role", message.get("type", ""))).upper()
            text = _message_text(message).strip()
            if text and role in {"USER", "ASSISTANT"}:
                history.append(
                    {"role": "user" if role == "USER" else "assistant", "content": text}
                )
    return history


def _user_memory_context(history: list[dict[str, str]]) -> str:
    """Build reliable memory context without persisting earlier model mistakes."""
    user_statements = [
        message["content"] for message in history if message.get("role") == "user"
    ]
    if not user_statements:
        return "No previous user statements are stored for this conversation."
    return "\n".join(
        f"{index}. {statement}" for index, statement in enumerate(user_statements, start=1)
    )


def _last_content(result: dict[str, Any]) -> str:
    content = result["messages"][-1].content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Load short-term memory, invoke the agent, and save the completed turn."""
    prompt = str(payload.get("prompt", "")).strip() if isinstance(payload, dict) else ""
    if not prompt:
        return {"error": "Payload must contain a non-empty 'prompt'."}

    actor_id = (
        _context_value(context, "actor_id")
        or str(payload.get("actor_id", "default-user")).strip()
    )
    session_id = (
        _context_value(context, "session_id")
        or str(payload.get("session_id", "")).strip()
    )
    if not session_id:
        return {
            "error": "Provide session_id in the payload when Runtime context has no session ID."
        }

    try:
        turns = memory_client.get_last_k_turns(
            memory_id=MEMORY_ID,
            actor_id=actor_id,
            session_id=session_id,
            k=HISTORY_TURNS,
        )
        history = _langchain_history(turns)
        memory_context = _user_memory_context(history)
        messages = [
            {
                "role": "user",
                "content": (
                    "Here are this actor's stored user statements, ordered oldest to newest. "
                    "Use them as conversation memory; newer statements override older ones.\n\n"
                    f"<memory>\n{memory_context}\n</memory>\n\n"
                    f"Current request: {prompt}"
                ),
            }
        ]

        result = agent.invoke({"messages": messages})
        answer = _last_content(result)

        memory_client.create_event(
            memory_id=MEMORY_ID,
            actor_id=actor_id,
            session_id=session_id,
            messages=[(prompt, "USER"), (answer, "ASSISTANT")],
        )
        return {
            "result": answer,
            "memory_id": MEMORY_ID,
            "actor_id": actor_id,
            "session_id": session_id,
            "history_turns_loaded": len(turns),
            "model_id": MODEL_ID,
        }
    except Exception as error:
        logger.exception("AgentCore Memory invocation failed")
        return {"error": type(error).__name__, "message": str(error)}


if __name__ == "__main__":
    app.run()
