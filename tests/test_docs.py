import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(REPO_ROOT, "docs")

def test_flow_doc_exists():
    path = os.path.join(DOCS, "01_flow_and_audit_events.md")
    assert os.path.exists(path), "docs/01_flow_and_audit_events.md missing"

def test_flow_doc_has_event_catalogue():
    path = os.path.join(DOCS, "01_flow_and_audit_events.md")
    with open(path) as f:
        content = f.read()
    assert "graph_construction" in content
    assert "node_verified" in content
    assert "figure_computed" in content
    assert "reconciliation" in content
    assert "config_loaded" in content
    assert "report_exported" in content
    assert "retention_class" in content

def test_architecture_doc_exists():
    path = os.path.join(DOCS, "02_architecture.md")
    assert os.path.exists(path)

def test_architecture_doc_has_required_sections():
    path = os.path.join(DOCS, "02_architecture.md")
    with open(path) as f:
        content = f.read()
    for section in ["Ingestion", "Graph", "Compute", "Audit", "Reconcile"]:
        assert section in content, f"Section '{section}' missing from architecture doc"

def test_rfc_doc_exists():
    path = os.path.join(DOCS, "03_rfc.md")
    assert os.path.exists(path)

def test_rfc_doc_has_llm_boundary_section():
    path = os.path.join(DOCS, "03_rfc.md")
    with open(path) as f:
        content = f.read()
    assert "LLM" in content
    assert "firewall" in content or "Firewall" in content
    assert "containment" in content or "Containment" in content
