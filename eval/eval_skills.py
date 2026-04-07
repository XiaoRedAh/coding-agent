"""
Module evaluation: Skills system (skills/loader.py)
Cost: $0 | LLM required: No
Run: python eval/eval_skills.py
"""
import sys
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("MODEL_ID", "test-model")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from skills.loader import SkillLoader


@dataclass
class EvalResult:
    category: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    details: list = field(default_factory=list)

    @property
    def accuracy(self):
        return self.passed / self.total if self.total else 0.0

    def record(self, success, desc, expected="", actual=""):
        self.total += 1
        if success:
            self.passed += 1
        else:
            self.failed += 1
            self.details.append(f"  FAIL: {desc} (expected={expected}, actual={actual})")


# ──────────────────────────────────────────────
#  Helper: create temp skill files
# ──────────────────────────────────────────────

def _create_skill(base_dir: Path, skill_name: str, frontmatter: dict, body: str):
    """Create a SKILL.md file under base_dir/<skill_name>/SKILL.md."""
    skill_dir = base_dir / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for k, v in frontmatter.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append(body)
    (skill_dir / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")
    return skill_dir


# ──────────────────────────────────────────────
#  1. Scanning correctness
# ──────────────────────────────────────────────

def evaluate_scanning() -> EvalResult:
    r = EvalResult("Skill Scanning")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        # Create skills in a single directory
        _create_skill(base, "commit", {"name": "commit", "description": "Create git commits"}, "Commit body")
        _create_skill(base, "review", {"name": "review", "description": "Review code changes"}, "Review body")
        _create_skill(base, "deploy", {"name": "deploy", "description": "Deploy to production"}, "Deploy body")

        loader = SkillLoader(base)

        # 1.1 All skills discovered
        names = loader.list_names()
        r.record(len(names) == 3, "discovers 3 skills", "3", str(len(names)))
        r.record("commit" in names, "finds commit skill", "commit in list", str(names))
        r.record("review" in names, "finds review skill", "review in list", str(names))

    return r


def evaluate_multi_directory() -> EvalResult:
    r = EvalResult("Multi-directory Scanning & Dedup")

    with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
        dir1 = Path(td1)
        dir2 = Path(td2)

        # Same skill name in both directories
        _create_skill(dir1, "commit", {"name": "commit", "description": "High priority"}, "Body from dir1")
        _create_skill(dir2, "commit", {"name": "commit", "description": "Low priority"}, "Body from dir2")
        _create_skill(dir2, "unique", {"name": "unique", "description": "Only in dir2"}, "Unique body")

        # dir1 has higher priority (listed first)
        loader = SkillLoader(dir1, dir2)

        # 2.1 Dedup: first directory wins
        names = loader.list_names()
        r.record(names.count("commit") == 1, "commit not duplicated", "1", str(names.count("commit")))

        # 2.2 High-priority description wins
        meta = loader.get_skill_meta("commit")
        r.record(meta.get("description") == "High priority", "first dir wins", "High priority", meta.get("description", ""))

        # 2.3 Unique skill from second dir still found
        r.record("unique" in names, "unique skill from dir2 found", "unique in list", str(names))

        # 2.4 Total count
        r.record(len(names) == 2, "total 2 unique skills", "2", str(len(names)))

    return r


# ──────────────────────────────────────────────
#  2. Argument substitution
# ──────────────────────────────────────────────

def evaluate_substitution() -> EvalResult:
    r = EvalResult("Argument Substitution")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _create_skill(base, "greet", {"name": "greet", "description": "Greeting skill"},
                       "Hello $ARGUMENTS! First: $ARG_1, Second: $ARG_2. Dir: ${SKILL_DIR}")

        loader = SkillLoader(base)

        # 3.1 $ARGUMENTS substitution
        out = loader.load("greet", "Alice Bob")
        r.record("Hello Alice Bob!" in out, "$ARGUMENTS replaced", "Alice Bob", out[:100])

        # 3.2 $ARG_1 and $ARG_2
        r.record("First: Alice" in out, "$ARG_1 replaced", "Alice", out[:150])
        r.record("Second: Bob" in out, "$ARG_2 replaced", "Bob", out[:150])

        # 3.3 ${SKILL_DIR} substitution
        skill_dir_str = str(base / "greet")
        r.record(skill_dir_str.replace("\\", "/") in out.replace("\\", "/"),
                 "${SKILL_DIR} replaced", skill_dir_str, out[:200])

        # 3.4 XML wrapper
        r.record('<skill name="greet">' in out, "XML wrapper present", "<skill>", out[:50])
        r.record("</skill>" in out, "XML closing tag", "</skill>", out[-20:])

        # 3.5 Unknown skill error
        out_err = loader.load("nonexistent")
        r.record("Error" in out_err or "Unknown" in out_err, "unknown skill error", "Error", out_err[:60])

    return r


# ──────────────────────────────────────────────
#  3. Description truncation
# ──────────────────────────────────────────────

def evaluate_description_truncation() -> EvalResult:
    r = EvalResult("Description Truncation")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        long_desc = "A" * 300
        _create_skill(base, "long", {"name": "long", "description": long_desc}, "Body")
        _create_skill(base, "short", {"name": "short", "description": "Brief"}, "Body")

        loader = SkillLoader(base)
        desc_output = loader.descriptions()

        # 4.1 Long description truncated to 250 chars
        # The line for "long" should end with "..."
        for line in desc_output.split("\n"):
            if "long:" in line:
                desc_part = line.split("long:", 1)[1].strip()
                r.record(len(desc_part) <= 250, "long desc <= 250 chars", "<=250", str(len(desc_part)))
                r.record(desc_part.endswith("..."), "long desc ends with ...", "...", desc_part[-5:])
                break
        else:
            r.record(False, "long skill found in descriptions", "found", "not found")

        # 4.2 Short description not truncated
        r.record("Brief" in desc_output, "short desc intact", "Brief", desc_output[:200])

    return r


# ──────────────────────────────────────────────
#  4. Progressive disclosure format
# ──────────────────────────────────────────────

def evaluate_progressive_disclosure() -> EvalResult:
    r = EvalResult("Progressive Disclosure")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _create_skill(base, "alpha", {"name": "alpha", "description": "Alpha skill"}, "Alpha body")
        _create_skill(base, "beta", {"name": "beta", "description": "Beta skill"}, "Beta body")

        loader = SkillLoader(base)
        desc = loader.descriptions()

        # 5.1 Format: "  - name: description"
        r.record("  - alpha: Alpha skill" in desc, "format matches '  - name: desc'", "  - alpha: Alpha skill", desc[:100])
        r.record("  - beta: Beta skill" in desc, "beta format correct", "  - beta: Beta skill", desc[:200])

        # 5.2 Body NOT in descriptions (progressive disclosure)
        r.record("Alpha body" not in desc, "body not in descriptions", "absent", "present" if "Alpha body" in desc else "absent")

    # 5.3 Empty skills directory
    with tempfile.TemporaryDirectory() as td2:
        loader2 = SkillLoader(Path(td2))
        desc2 = loader2.descriptions()
        r.record("no skills" in desc2.lower(), "empty dir says no skills", "(no skills)", desc2[:40])

    return r


# ──────────────────────────────────────────────
#  5. Frontmatter parsing edge cases
# ──────────────────────────────────────────────

def evaluate_frontmatter_parsing() -> EvalResult:
    r = EvalResult("Frontmatter Parsing")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        # 6.1 No frontmatter — use directory name as skill name
        no_fm_dir = base / "nofm"
        no_fm_dir.mkdir()
        (no_fm_dir / "SKILL.md").write_text("Just body content, no frontmatter.", encoding="utf-8")

        loader = SkillLoader(base)
        r.record("nofm" in loader.list_names(), "no frontmatter uses dir name", "nofm", str(loader.list_names()))

        # 6.2 Load no-frontmatter skill
        out = loader.load("nofm")
        r.record("Just body content" in out, "no-fm body loaded", "Just body content", out[:80])

    return r


# ──────────────────────────────────────────────
#  Report generation
# ──────────────────────────────────────────────

def run_full_evaluation():
    evaluators = [
        ("Scanning", evaluate_scanning),
        ("Multi-directory", evaluate_multi_directory),
        ("Substitution", evaluate_substitution),
        ("Description Truncation", evaluate_description_truncation),
        ("Progressive Disclosure", evaluate_progressive_disclosure),
        ("Frontmatter Parsing", evaluate_frontmatter_parsing),
    ]

    results = []
    for name, fn in evaluators:
        try:
            results.append(fn())
        except Exception as e:
            er = EvalResult(name)
            er.record(False, f"evaluator crashed: {e}")
            results.append(er)

    total_cases = sum(r.total for r in results)
    total_passed = sum(r.passed for r in results)
    total_failed = sum(r.failed for r in results)

    print("=" * 70)
    print("  Skills System Evaluation Report")
    print("=" * 70)
    print()

    for r in results:
        status = "PASS" if r.failed == 0 else "FAIL"
        print(f"[{status}] {r.category}: {r.passed}/{r.total} ({r.accuracy:.1%})")
        for detail in r.details:
            print(detail)

    print()
    print("-" * 70)
    overall = total_passed / total_cases if total_cases else 0
    print(f"  Total: {total_passed}/{total_cases} ({overall:.1%})")
    print(f"  Passed: {total_passed}  Failed: {total_failed}")
    print(f"  Test cases: {total_cases}")
    print(f"  API calls: 0  |  Cost: $0")
    print("-" * 70)

    return total_failed == 0


# ──────────────────────────────────────────────
#  pytest compatible
# ──────────────────────────────────────────────

def test_scanning():
    r = evaluate_scanning()
    assert r.accuracy >= 0.90, f"Scanning accuracy {r.accuracy:.1%} < 90%"

def test_multi_directory():
    r = evaluate_multi_directory()
    assert r.accuracy >= 0.90, f"Multi-directory accuracy {r.accuracy:.1%} < 90%"

def test_substitution():
    r = evaluate_substitution()
    assert r.accuracy >= 0.90, f"Substitution accuracy {r.accuracy:.1%} < 90%"

def test_description_truncation():
    r = evaluate_description_truncation()
    assert r.accuracy >= 0.90, f"Truncation accuracy {r.accuracy:.1%} < 90%"

def test_progressive_disclosure():
    r = evaluate_progressive_disclosure()
    assert r.accuracy >= 0.90, f"Progressive disclosure accuracy {r.accuracy:.1%} < 90%"

def test_frontmatter_parsing():
    r = evaluate_frontmatter_parsing()
    assert r.accuracy >= 0.90, f"Frontmatter parsing accuracy {r.accuracy:.1%} < 90%"


if __name__ == "__main__":
    success = run_full_evaluation()
    sys.exit(0 if success else 1)
