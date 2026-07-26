import os
import pathlib
import time
from typing import TypedDict

from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
if not GROQ_API_KEY:
    raise EnvironmentError(
        "GROQ_API_KEY is not set. Set it in your environment or in a .env file."
    )

MODEL_CATALOG = {
    "llama-3.3-70b-versatile": {
        "input_cost_per_million": 0.59,
        "output_cost_per_million": 0.79,
    },
    "llama-3.1-8b-instant": {
        "input_cost_per_million": 0.05,
        "output_cost_per_million": 0.08,
    },
    "openai/gpt-oss-20b": {
        "input_cost_per_million": 0.20,
        "output_cost_per_million": 0.20,
    },
}

AGENT_SPECS = {
    "requirements_analyst": {
        "title": "REQUIREMENTS ANALYST",
        "system_prompt": "You are a senior QA requirements analyst. Identify actors, business rules, acceptance criteria, risks, dependencies, and ambiguous requirements. Be concise and do not invent missing facts.",
        "task_template": "Analyze this requirement for testing:\n\n{requirement}",
        "output_key": "analysis",
        "quality_keywords": ["actors", "business rules", "acceptance criteria", "risks", "dependencies"],
    },
    "test_designer": {
        "title": "TEST DESIGNER",
        "system_prompt": "You are a senior test designer. Produce a compact Markdown table with ID, scenario, preconditions, steps, expected result, test type, and priority. Cover positive, negative, boundary, security, and failure paths.",
        "task_template": "Requirement:\n{requirement}\n\nRequirements analysis:\n{analysis}\n\nDesign executable test cases.",
        "output_key": "test_cases",
        "quality_keywords": ["id", "scenario", "preconditions", "steps", "expected result", "priority"],
    },
    "security_reviewer": {
        "title": "SECURITY REVIEWER",
        "system_prompt": "You are a senior security reviewer. Evaluate the requirement and test cases for authentication, authorization, data protection, replay resistance, expiry, and generic error handling. Provide concise security findings and remediation recommendations.",
        "task_template": "Requirement:\n{requirement}\n\nRequirements analysis:\n{analysis}\n\nProposed test cases:\n{test_cases}\n\nReview these artifacts for security gaps and recommendations.",
        "output_key": "security_review",
        "quality_keywords": ["authentication", "authorization", "data protection", "replay", "expiry", "error"],
    },
    "qa_reviewer": {
        "title": "QA REVIEWER",
        "system_prompt": "You are a critical QA lead. Review the proposed tests for requirement coverage, missing edge cases, duplication, testability, business risk, and whether security findings were addressed. Finish with APPROVE or REVISE and a short reason.",
        "task_template": "Requirement:\n{requirement}\n\nAnalysis:\n{analysis}\n\nProposed tests:\n{test_cases}\n\nSecurity review:\n{security_review}",
        "output_key": "review",
        "quality_keywords": ["approve", "revise", "coverage", "edge", "testability"],
    },
}


class QAAgentState(TypedDict):
    requirement: str
    analysis: str
    test_cases: str
    security_review: str
    review: str


def safe_text(value: str) -> str:
    return str(value).encode("cp1252", errors="replace").decode("cp1252")


def build_model(model_name: str) -> ChatGroq:
    return ChatGroq(
        model=model_name,
        temperature=0.2,
        max_tokens=1500,
        max_retries=2,
    )


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


def estimate_cost(model_name: str, prompt_text: str, response_text: str) -> float:
    model_info = MODEL_CATALOG[model_name]
    prompt_tokens = estimate_tokens(prompt_text)
    response_tokens = estimate_tokens(response_text)
    input_cost = prompt_tokens * model_info["input_cost_per_million"] / 1_000_000
    output_cost = response_tokens * model_info["output_cost_per_million"] / 1_000_000
    return round(input_cost + output_cost, 6)


def score_quality(agent_name: str, response_text: str) -> float:
    response = safe_text(response_text).lower()
    keywords = AGENT_SPECS[agent_name]["quality_keywords"]
    hits = sum(1 for keyword in keywords if keyword in response)
    return round(hits / max(len(keywords), 1), 3)


def evaluate_model(agent_name: str, model_name: str, state: QAAgentState) -> dict:
    spec = AGENT_SPECS[agent_name]
    task = spec["task_template"].format(
        requirement=state["requirement"],
        analysis=state["analysis"],
        test_cases=state["test_cases"],
        security_review=state["security_review"],
        review=state["review"],
    )

    start_time = time.perf_counter()
    try:
        response = build_model(model_name).invoke([
            ("system", spec["system_prompt"]),
            ("human", task),
        ])
        content = safe_text(getattr(response, "content", ""))
        latency = round(time.perf_counter() - start_time, 3)
        quality = score_quality(agent_name, content)
        cost = estimate_cost(model_name, task, content)
        return {
            "model_name": model_name,
            "content": content,
            "quality": quality,
            "cost": cost,
            "latency": latency,
            "error": None,
        }
    except Exception as exc:
        return {
            "model_name": model_name,
            "content": "",
            "quality": 0.0,
            "cost": 0.0,
            "latency": round(time.perf_counter() - start_time, 3),
            "error": str(exc),
        }


def compare_models(agent_name: str, state: QAAgentState) -> tuple[list[dict], dict]:
    results = [evaluate_model(agent_name, model_name, state) for model_name in MODEL_CATALOG]
    valid_results = [result for result in results if not result["error"]]
    if not valid_results:
        raise RuntimeError(f"All model evaluations failed for {agent_name}.")

    max_cost = max(result["cost"] for result in valid_results)
    max_latency = max(result["latency"] for result in valid_results)

    for result in results:
        if result["error"]:
            result["overall_score"] = -1.0
            continue
        normalized_cost = min(result["cost"] / max(max_cost, 1e-9), 1.0)
        normalized_latency = min(result["latency"] / max(max_latency, 1e-9), 1.0)
        result["overall_score"] = round(
            0.5 * result["quality"] + 0.25 * (1 - normalized_cost) + 0.25 * (1 - normalized_latency),
            3,
        )

    best_result = max(results, key=lambda item: item["overall_score"])
    return results, best_result


def print_comparison(agent_name: str, results: list[dict]) -> None:
    spec = AGENT_SPECS[agent_name]
    print(f"\n{'=' * 20} {spec['title']} MODEL COMPARISON {'=' * 20}\n")
    print("Model | Quality | Cost ($) | Latency (s) | Score")
    print("-" * 70)
    for result in sorted(results, key=lambda item: item["overall_score"], reverse=True):
        if result["error"]:
            print(f"{result['model_name']} | ERROR | - | - | -")
        else:
            print(
                f"{result['model_name']} | {result['quality']:.3f} | {result['cost']:.6f} | {result['latency']:.3f} | {result['overall_score']:.3f}"
            )


def run_agent_pipeline(requirement_text: str) -> dict:
    state: QAAgentState = {
        "requirement": requirement_text,
        "analysis": "",
        "test_cases": "",
        "security_review": "",
        "review": "",
    }

    for agent_name in ["requirements_analyst", "test_designer", "security_reviewer", "qa_reviewer"]:
        results, best_result = compare_models(agent_name, state)
        print_comparison(agent_name, results)
        print(f"Selected model for {AGENT_SPECS[agent_name]['title']}: {best_result['model_name']}")
        state[AGENT_SPECS[agent_name]["output_key"]] = best_result["content"]

    return state


def main() -> None:
    requirements_path = pathlib.Path(__file__).parent / "requirements_doc.md"
    if not requirements_path.exists():
        raise FileNotFoundError(f"Requirement document not found: {requirements_path}")

    requirement_text = requirements_path.read_text(encoding="utf-8").strip()
    if not requirement_text:
        raise ValueError("Requirement document is empty.")

    print(f"Loaded requirement from {requirements_path}:\n\n{requirement_text}\n")

    result = run_agent_pipeline(requirement_text)

    sections = [
        ("REQUIREMENTS ANALYST", "analysis"),
        ("TEST DESIGNER", "test_cases"),
        ("SECURITY REVIEWER", "security_review"),
        ("QA REVIEWER", "review"),
    ]

    for heading, key in sections:
        print(f"\n{'=' * 20} {heading} {'=' * 20}\n")
        print(safe_text(result[key]))


if __name__ == "__main__":
    main()
