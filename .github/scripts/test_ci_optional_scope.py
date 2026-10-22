"""Fail-open test cases for the non-required GitHub Actions scope selector."""
import importlib.util
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'ci_optional_scope', Path(__file__).with_name('ci_optional_scope.py'))
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)

class ScopeTest(TestCase):
    def test_only_unrelated_workflows_or_audit_scripts_are_small(self):
        for paths in (
            ['.github/workflows/wine.yaml'],
            ['.github/workflows/codecov.yml'],
            ['.github/workflows/iroh-patchbay.yml'],
            ['.github/workflows/ci-impact-graph.yml'],
            ['.github/scripts/ci_impact_graph.py'],
            ['.github/scripts/test_ci_impact_graph.py'],
            ['.github/workflows/docs.yaml', '.github/scripts/ci_impact_graph.py'],
        ):
            with self.subTest(paths=paths):
                self.assertFalse(selector.full_matrix_needed(paths))

    def test_code_dependencies_ci_config_and_unknown_files_need_full(self):
        for paths in (
            [], ['Cargo.lock'], ['Cargo.toml'],
            ['noq-proto/src/connection/mod.rs'],
            ['noq/src/lib.rs', '.github/workflows/wine.yaml'],
            ['README.md'],
            ['.github/workflows/ci.yml'],
            ['.github/workflows/tests.yaml'],
            ['.github/workflows/rust-android-run-tests-on-emulator.sh'],
            ['.github/scripts/ci_optional_scope.py'],
            ['.github/scripts/test_ci_optional_scope.py'],
            ['.github/scripts/unknown.sh'],
            ['.github/workflows/nested/ci.yml'],
        ):
            with self.subTest(paths=paths):
                self.assertTrue(selector.full_matrix_needed(paths))

    def test_untrusted_or_missing_merge_parent_fails_open(self):
        with patch.dict('os.environ', {'GITHUB_EVENT_NAME': 'push', 'PR_BASE_SHA': 'base'}):
            self.assertIsNone(selector.changed_paths_from_pr_merge())
        with patch.dict('os.environ', {'GITHUB_EVENT_NAME': 'pull_request', 'PR_BASE_SHA': 'base'}):
            with patch.object(selector.subprocess, 'check_output', return_value=b'head wrong branch\n'):
                self.assertIsNone(selector.changed_paths_from_pr_merge())
            with patch.object(selector.subprocess, 'check_output', return_value=b'head base\n'):
                self.assertIsNone(selector.changed_paths_from_pr_merge())

    def test_synthetic_merge_diff_handles_deletions_and_changed_file_set(self):
        with patch.dict('os.environ', {'GITHUB_EVENT_NAME': 'pull_request', 'PR_BASE_SHA': 'base'}):
            with patch.object(selector.subprocess, 'check_output', side_effect=[
                b'head base pr\n', b'.github/workflows/wine.yaml\0noq/src/lib.rs\0'
            ]) as call:
                self.assertEqual(selector.changed_paths_from_pr_merge(), [
                    '.github/workflows/wine.yaml', 'noq/src/lib.rs'
                ])
                self.assertIn('--no-renames', call.call_args.args[0])

if __name__ == '__main__':
    main()
