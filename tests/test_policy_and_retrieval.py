import pytest

from mcp_assistant import config
from mcp_assistant.memory import MemoryStore
from mcp_assistant.models import ToolInfo
from mcp_assistant.policy import Decision, Policy
from mcp_assistant.retrieval import BM25, KnowledgeIndex, chunk_text, cosine, rrf, tokenize

POLICY = config.ROOT / "config" / "policy.yaml"


def tool(name, read_only=False, destructive=True, server="x"):
    return ToolInfo(server=server, name=name, description="", input_schema={}, read_only=read_only, destructive=destructive)


def test_policy_profiles():
    ro, std, adm = (Policy.load(POLICY, p) for p in ("readonly", "standard", "admin"))
    read, write, destroy = tool("r", True, False), tool("w", False, False), tool("d", False, True)
    assert ro.decide(read)[0] is Decision.ALLOW and ro.decide(write)[0] is Decision.DENY
    assert std.decide(read)[0] is Decision.ALLOW and std.decide(write)[0] is Decision.APPROVE
    assert adm.decide(write)[0] is Decision.ALLOW and adm.decide(destroy)[0] is Decision.APPROVE


def test_policy_rules_and_exposure():
    std = Policy.load(POLICY, "standard")
    assert std.decide(tool("remember", False, False, "memory"))[0] is Decision.ALLOW
    assert std.decide(tool("forget", False, True, "memory"))[0] is Decision.APPROVE
    assert std.decide(tool("delete_everything", False, True, "files"))[0] is Decision.DENY
    assert not std.exposed(tool("delete_everything", False, True, "files"))
    # unannotated third-party tools follow MCP spec defaults (not read-only, destructive) -> approval
    assert std.decide(ToolInfo("ext", "mystery", "", {}))[0] is Decision.APPROVE


def test_unknown_profile():
    with pytest.raises(ValueError):
        Policy.load(POLICY, "nope")


def test_rate_limit():
    p = Policy.load(POLICY, "standard")
    p.limits.rate_limit_per_minute = 3
    assert [p.rate_ok() for _ in range(5)] == [True, True, True, False, False]


def test_bm25_ranks_relevant_doc_first():
    docs = ["refund within 30 days of invoice", "onboarding laptop and ID card", "gst rate eighteen percent"]
    scores = BM25([tokenize(d) for d in docs]).scores(tokenize("refund days"))
    assert scores.index(max(scores)) == 0


def test_chunking_and_rrf():
    text = "\n\n".join(f"paragraph {i} " + "word " * 80 for i in range(10))
    chunks = chunk_text(text, size=500, overlap=50)
    assert len(chunks) > 3 and all(len(c) <= 700 for c in chunks)
    fused = dict(rrf([[0, 1, 2], [2, 0, 1]]))
    assert fused[0] > fused[1] and fused[2] > fused[1]
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0) and cosine([1, 0], [0, 1]) == 0


class FakeEmbedder:
    """Deterministic 'embedding': counts of a few concept words, so dense retrieval is testable offline."""
    vocab = ["refund", "laptop", "tax"]

    def _v(self, t):
        t = t.lower()
        return [float(t.count(w)) + 0.01 for w in self.vocab]

    def embed_documents(self, texts):
        return [self._v(t) for t in texts]

    def embed_query(self, text):
        return self._v(text)


def test_hybrid_index(tmp_path):
    idx = KnowledgeIndex(tmp_path / "i.json")
    emb = FakeEmbedder()
    idx.add_document("a.md", "Refund policy: refunds within 30 days.", 1.0, emb)
    idx.add_document("b.md", "Your laptop arrives on day one.", 1.0, emb)
    hits = idx.search("how do refunds work", k=2, embedder=emb)
    assert hits[0]["source"] == "a.md" and hits[0]["mode"] == "hybrid"
    lexical = idx.search("laptop", k=1)
    assert lexical[0]["source"] == "b.md" and lexical[0]["mode"] == "lexical"
    idx.save()
    assert len(KnowledgeIndex(tmp_path / "i.json").chunks) == 2


def test_memory_store(tmp_path):
    m = MemoryStore(tmp_path / "m.json")
    a = m.add("User prefers amounts in INR lakhs", ["format"])
    m.add("Finance review is every Monday")
    assert m.search("amounts lakhs")[0]["id"] == a["id"]
    assert MemoryStore(tmp_path / "m.json").items  # persisted
    assert m.forget(a["id"]) and not m.forget("nope")
