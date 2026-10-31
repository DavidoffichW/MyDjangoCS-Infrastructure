from __future__ import annotations

import ast
from pathlib import Path

from django.test import SimpleTestCase


class ArchitectureBoundaryTests(SimpleTestCase):
    def test_foundation_does_not_import_django_or_application_modules(self):
        root = Path(__file__).resolve().parents[2] / "deterministic_lab"
        forbidden = {"django", "django_htmx", "reliability_lab", "workflows"}
        violations = []
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = {node.module.split(".")[0]}
                else:
                    continue
                if names & forbidden:
                    violations.append(f"{path.name}:{node.lineno}")
        self.assertEqual(violations, [])
