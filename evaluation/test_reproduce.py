import shutil
import subprocess
import sys

import pytest

from evaluation.reproduce import ROOT, reproduce


def test_published_metrics_reproduce_without_native_module_or_private_corpus():
    result = reproduce()
    assert result["verified"]
    assert result["results"]["test"]["bm25"]["ndcg@10"] == pytest.approx(0.6534857052535918)
    # Isolated mode deliberately removes PYTHONPATH (including native bindings).
    command = f"import sys; sys.path.insert(0, {str(ROOT.parent)!r}); from evaluation.reproduce import reproduce; assert reproduce()['verified']"
    proc = subprocess.run([sys.executable, "-I", "-c", command], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("name", ["frozen/runs.jsonl", "frozen/queries.jsonl", "relevance_ai_test.csv", "ai_test_report.json"])
def test_reproduction_rejects_changed_artifacts(tmp_path, name):
    for item in ROOT.glob("ai_*.json"):
        shutil.copy(item, tmp_path / item.name)
    for item in ROOT.glob("relevance_ai_*.csv"):
        shutil.copy(item, tmp_path / item.name)
    shutil.copy(ROOT / "queries.jsonl", tmp_path / "queries.jsonl")
    shutil.copytree(ROOT / "frozen", tmp_path / "frozen")
    with (tmp_path / name).open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="changed"):
        reproduce(tmp_path)
