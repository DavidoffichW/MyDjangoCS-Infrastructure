from __future__ import annotations

import ast
from pathlib import Path

from django.test import SimpleTestCase


class ArchitectureBoundaryTests(SimpleTestCase):
    @staticmethod
    def _absolute_import_roots(root: Path) -> list[tuple[Path, int, set[str]]]:
        imports = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = {node.module.split(".")[0]}
                else:
                    continue
                imports.append((path, node.lineno, names))
        return imports

    def test_foundation_does_not_import_django_or_application_modules(self):
        root = Path(__file__).resolve().parents[2] / "foundation"
        forbidden = {
            "django",
            "django_htmx",
            "infrastructure",
            "reliability_lab",
            "services",
            "web_infra",
            "workflows",
        }
        violations = []
        for path, line, names in self._absolute_import_roots(root):
            if names & forbidden:
                violations.append(f"{path.relative_to(root)}:{line}")
        self.assertEqual(violations, [])

    def test_infrastructure_does_not_depend_on_service_or_web_delivery(self):
        root = Path(__file__).resolve().parents[2] / "infrastructure"
        forbidden = {"frontend", "services", "web_infra"}
        violations = [
            f"{path.relative_to(root)}:{line}"
            for path, line, names in self._absolute_import_roots(root)
            if names & forbidden
        ]
        self.assertEqual(violations, [])

    def test_services_do_not_depend_on_web_delivery(self):
        root = Path(__file__).resolve().parents[2] / "services"
        forbidden = {"frontend", "web_infra"}
        violations = [
            f"{path.relative_to(root)}:{line}"
            for path, line, names in self._absolute_import_roots(root)
            if names & forbidden
        ]
        self.assertEqual(violations, [])

    def test_removed_broad_modules_do_not_reappear(self):
        root = Path(__file__).resolve().parents[2]
        removed = [
            root / "deterministic_lab",
            root / "workflows" / "forms.py",
            root / "workflows" / "models.py",
            root / "workflows" / "services.py",
            root / "workflows" / "scientific_services.py",
            root / "workflows" / "views.py",
        ]
        self.assertFalse(any(path.exists() and path.is_file() for path in removed))

    def test_reorganized_layers_have_no_static_import_cycles(self):
        root = Path(__file__).resolve().parents[2]
        source_roots = ["foundation", "infrastructure", "services", "web_infra"]
        modules: dict[str, tuple[Path, bool]] = {}
        for source_root in source_roots:
            for path in (root / source_root).rglob("*.py"):
                relative = path.relative_to(root).with_suffix("")
                is_package = relative.name == "__init__"
                parts = relative.parts[:-1] if is_package else relative.parts
                modules[".".join(parts)] = (path, is_package)

        graph = {module: set() for module in modules}
        for module, (path, is_package) in modules.items():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            package = module.split(".") if is_package else module.split(".")[:-1]
            for node in ast.walk(tree):
                candidates: list[str] = []
                if isinstance(node, ast.Import):
                    candidates.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        base = package[: len(package) - (node.level - 1)]
                        if node.module:
                            candidates.append(".".join([*base, *node.module.split(".")]))
                        else:
                            candidates.extend(".".join([*base, alias.name]) for alias in node.names)
                    elif node.module:
                        candidates.append(node.module)
                for candidate in candidates:
                    if candidate in modules and candidate != module:
                        graph[module].add(candidate)

        active: list[str] = []
        visited: set[str] = set()

        def visit(module: str) -> None:
            if module in active:
                cycle = " -> ".join([*active[active.index(module) :], module])
                self.fail(f"Static import cycle detected: {cycle}")
            if module in visited:
                return
            active.append(module)
            for dependency in sorted(graph[module]):
                visit(dependency)
            active.pop()
            visited.add(module)

        for module in sorted(graph):
            visit(module)
