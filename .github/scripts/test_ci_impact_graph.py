"""Offline regression tests for the read-only CI impact graph."""
# CI-only probe: verify reduced Windows default on #24 base uses hosted tools.
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('ci_impact_graph.py')
spec = importlib.util.spec_from_file_location('ci_impact_graph', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CIImpactGraphTest(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        (root / 'Cargo.toml').write_text('[workspace]\nmembers = ["base", "middle", "app", "tool"]\n')
        crates = {
            'base': '[package]\nname="base"\nversion="0.1.0"\n',
            'middle': '[package]\nname="middle"\nversion="0.1.0"\n[dependencies]\ncore={package="base",path="../base"}\n',
            'app': '[package]\nname="app"\nversion="0.1.0"\n[dependencies]\nmid={path="../middle"}\n',
            'tool': '[package]\nname="tool"\nversion="0.1.0"\n[dev-dependencies]\nb={path="../base"}\n',
        }
        for name, body in crates.items():
            (root / name / 'src').mkdir(parents=True)
            (root / name / 'Cargo.toml').write_text(body)
            (root / name / 'src' / 'lib.rs').write_text('pub fn ok() {}\n')
        wf = root / '.github' / 'workflows'
        wf.mkdir(parents=True)
        (wf / 'ci.yml').write_text(
            'name: CI\non:\n  pull_request:\n  push:\njobs:\n'
            '  test:\n    runs-on: ubuntu-latest\n')
        (wf / 'docs.yml').write_text(
            'on:\n  pull_request:\n    paths:\n      - "**/*.md"\njobs:\n'
            '  docs:\n    runs-on: ubuntu-latest\n')
        return directory, root

    def test_runtime_and_test_only_reverse_edges(self):
        tmp, root = self.fixture()
        with tmp:
            packages, deps, _ = mod.workspace(root)
            self.assertEqual(len(packages), 4)
            self.assertEqual(deps['middle'], {'base': 'runtime'})
            self.assertEqual(deps['tool'], {'base': 'test-only'})
            self.assertEqual(mod.dependents({'base'}, deps), {
                'app': 'runtime', 'base': 'runtime',
                'middle': 'runtime', 'tool': 'test-only'})

    def test_longest_member_prefix(self):
        self.assertEqual(mod.file_package('alpha/bench/src/lib.rs', {
            'alpha': 'alpha', 'bench': 'alpha/bench'}), 'bench')

    def test_workflow_classification_no_unsafe_skip(self):
        tmp, root = self.fixture()
        with tmp:
            files = mod.pr_workflows(root)
            self.assertEqual({x['workflow']: x['scope'] for x in files}, {
                '.github/workflows/ci.yml': 'unfiltered',
                '.github/workflows/docs.yml': 'conditional-paths'})
            result = mod.report(root, 10, 2,
                                ['base/src/lib.rs', 'Cargo.lock'], [])
            self.assertFalse(result['selected_files']['base/src/lib.rs']['requires_full_gate'])
            self.assertTrue(result['selected_files']['Cargo.lock']['requires_full_gate'])
            self.assertIn('REPORT ONLY', result['safety'])

    def test_inherited_workspace_path_uses_workspace_root(self):
        tmp, root = self.fixture()
        with tmp:
            (root / 'Cargo.toml').write_text(
                '[workspace]\nmembers = ["base", "middle", "app", "tool"]\n'
                '[workspace.dependencies]\nshared = {path = "base", package = "base"}\n')
            (root / 'middle' / 'Cargo.toml').write_text(
                '[package]\nname = "middle"\nversion = "0.1.0"\n'
                '[dependencies]\nshared = {workspace = true}\n')
            _, deps, _ = mod.workspace(root)
            self.assertEqual(deps['middle'], {'base': 'runtime'})
            self.assertEqual(mod.dependents({'base'}, deps)['app'], 'runtime')

    def test_test_only_path_can_upgrade_to_runtime(self):
        dependencies = {
            'base': {},
            'test_bridge': {'base': 'test-only'},
            'runtime_bridge': {'base': 'runtime'},
            'leaf': {'test_bridge': 'runtime', 'runtime_bridge': 'runtime'},
            'downstream': {'leaf': 'runtime'},
        }
        self.assertEqual(mod.dependents({'base'}, dependencies), {
            'base': 'runtime',
            'test_bridge': 'test-only',
            'runtime_bridge': 'runtime',
            'leaf': 'runtime',
            'downstream': 'runtime',
        })

    def test_target_specific_dependency_not_ignored(self):
        tmp, root = self.fixture()
        with tmp:
            path = root / 'app' / 'Cargo.toml'
            path.write_text(
                '[package]\nname="app"\nversion="0.1.0"\n'
                "[target.'cfg(windows)'.dev-dependencies]\n"
                'mock={path="../base"}\n')
            _, deps, _ = mod.workspace(root)
            self.assertEqual(deps['app'], {'base': 'test-only'})


if __name__ == '__main__':
    unittest.main()
