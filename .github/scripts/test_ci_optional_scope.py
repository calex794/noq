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


    def test_trusted_main_push_uses_before_sha(self):
        before = '1' * 40
        head = '2' * 40
        env = {
            'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/main',
            'PUSH_BEFORE_SHA': before, 'GITHUB_SHA': head,
        }
        with patch.dict('os.environ', env, clear=True):
            with patch.object(selector.subprocess, 'check_output',
                              side_effect=[head.encode() + b'\n', b'',
                                           b'.github/workflows/docs.yaml\0']) as mocked:
                paths = selector.changed_paths_from_main_push()
                self.assertEqual(paths, ['.github/workflows/docs.yaml'])
                self.assertFalse(selector.full_matrix_needed(paths))
                self.assertEqual(mocked.call_args_list[1].args[0],
                                 ['git', 'merge-base', '--is-ancestor', before, 'HEAD'])
                self.assertEqual(mocked.call_args_list[2].args[0],
                                 ['git', 'diff', '--no-renames', '--name-only',
                                  '-z', before, 'HEAD'])

    def test_push_code_change_preserves_full_matrix(self):
        before = 'a' * 40
        head = 'b' * 40
        env = {
            'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/main',
            'PUSH_BEFORE_SHA': before, 'GITHUB_SHA': head,
        }
        with patch.dict('os.environ', env, clear=True):
            with patch.object(selector.subprocess, 'check_output',
                              side_effect=[head.encode() + b'\n', b'',
                                           b'.github/workflows/docs.yaml\0noq/src/lib.rs\0']):
                self.assertTrue(selector.full_matrix_needed(
                    selector.changed_paths_from_main_push()))

    def test_main_push_guard_rejects_wrong_context(self):
        base = {
            'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/main',
            'PUSH_BEFORE_SHA': 'a' * 40, 'GITHUB_SHA': 'b' * 40,
        }
        invalid = [
            {'GITHUB_EVENT_NAME': 'workflow_dispatch'},
            {'GITHUB_REF': 'refs/heads/other'},
            {'PUSH_BEFORE_SHA': '0' * 40},
            {'PUSH_BEFORE_SHA': ''},
            {'PUSH_BEFORE_SHA': 'not-a-sha'},
            {'GITHUB_SHA': ''},
            {'GITHUB_SHA': 'a' * 40},
        ]
        for patch_env in invalid:
            with self.subTest(patch_env=patch_env):
                with patch.dict('os.environ', {**base, **patch_env}, clear=True):
                    with patch.object(selector.subprocess, 'check_output') as mocked:
                        self.assertIsNone(selector.changed_paths_from_main_push())
                        self.assertTrue(selector.full_matrix_needed(None))
                        mocked.assert_not_called()

    def test_main_push_must_match_head_and_be_ancestor(self):
        base = {
            'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/main',
            'PUSH_BEFORE_SHA': '1' * 40, 'GITHUB_SHA': '2' * 40,
        }
        with patch.dict('os.environ', base, clear=True):
            with patch.object(selector.subprocess, 'check_output',
                              return_value=b'wrong checkout\n'):
                self.assertIsNone(selector.changed_paths_from_main_push())
            import subprocess
            with patch.object(selector.subprocess, 'check_output',
                              side_effect=[b'2' * 40 + b'\n',
                                           subprocess.CalledProcessError(1, 'git')]):
                self.assertIsNone(selector.changed_paths_from_main_push())

    def test_main_push_missing_diff_does_not_select_small_matrix(self):
        before = '1' * 40
        head = '2' * 40
        env = {
            'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/main',
            'PUSH_BEFORE_SHA': before, 'GITHUB_SHA': head,
        }
        with patch.dict('os.environ', env, clear=True):
            with patch.object(selector.subprocess, 'check_output',
                              side_effect=[head.encode() + b'\n', b'', b'']):
                self.assertTrue(selector.full_matrix_needed(
                    selector.changed_paths_from_main_push()))

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
