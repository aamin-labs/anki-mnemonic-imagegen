from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "consolidate_context_tags.py"
    spec = spec_from_file_location("consolidate_context_tags", script_path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_exact_agent_eval_mapping():
    mod = load_module()
    assert mod.classify_context("Agent Evals") == "Agents, Evaluation"


def test_langgraph_variant_collapses():
    mod = load_module()
    assert mod.classify_context("LangGraph,Persistence") == "LangGraph"


def test_semantic_caching_keeps_two_axes():
    mod = load_module()
    assert mod.classify_context("Semantic caching") == "RAG, Inference"


def test_html_context_normalizes():
    mod = load_module()
    assert mod.classify_context("RAG<br>") == "RAG"


def test_git_stays_git():
    mod = load_module()
    assert mod.classify_context("Git") == "Git"
