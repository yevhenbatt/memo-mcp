import os
import unittest


class ConfigurationTemplateTests(unittest.TestCase):
    def test_example_has_no_production_hostname(self):
        with open('.env.example', encoding='utf-8') as handle:
            template = handle.read()
        self.assertIn('mcp.example.com', template)
        self.assertNotIn('memoriq.lol', template)

    def test_production_files_are_ignored(self):
        with open('.gitignore', encoding='utf-8') as handle:
            ignored = handle.read()
        self.assertIn('.env', ignored)
        self.assertNotIn('compose.yml', ignored)

    def test_docker_build_excludes_local_secrets_and_git_history(self):
        with open('.dockerignore', encoding='utf-8') as handle:
            ignored = handle.read()
        self.assertIn('.env', ignored)
        self.assertIn('.git', ignored)


if __name__ == '__main__':
    unittest.main()
