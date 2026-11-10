"""Static workflow contracts use the immutable original as the native oracle."""

import subprocess
import unittest

from helper_support import INTAKE, ROOT, original
import yaml


class WorkflowTests(unittest.TestCase):
    def load(self, name):
        return yaml.load((ROOT / ".github/workflows" / name).read_text(),
                         Loader=yaml.BaseLoader)

    def test_exact_two_independent_manual_entries_and_immutable_checkouts(self):
        paths = sorted((ROOT / ".github/workflows").glob("*.yml"))
        self.assertEqual([path.name for path in paths], ["bump-version.yml", "release.yml"])
        bump, build = self.load("bump-version.yml"), self.load("release.yml")
        self.assertEqual(bump["name"], "Bump version")
        self.assertEqual(build["name"], "Build")
        self.assertEqual(build["on"], {"workflow_dispatch": ""})
        mode = bump["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(mode), {"mode"})
        self.assertEqual(mode["mode"], {
            "type": "choice", "description": "Semantic version bump",
            "required": "true", "default": "patch",
            "options": ["patch", "minor", "major"],
        })
        for workflow in (bump, build):
            for job in workflow["jobs"].values():
                for step in job["steps"]:
                    if step.get("uses", "").startswith("actions/checkout@"):
                        self.assertEqual(step["with"]["ref"], "${{ github.sha }}")
        self.assertEqual(build["concurrency"], {
            "group": "release-publication", "cancel-in-progress": "false"})
        self.assertNotIn("github.ref", str(build["concurrency"]))

    def test_native_topology_configuration_and_original_cmd_are_preserved(self):
        build = self.load("release.yml")
        before = yaml.load(original(".github/workflows/release.yml"), Loader=yaml.BaseLoader)
        self.assertEqual(set(build["jobs"]), set(before["jobs"]))
        for name in build["jobs"]:
            self.assertEqual(build["jobs"][name]["runs-on"], before["jobs"][name]["runs-on"])
            self.assertEqual(build["jobs"][name].get("needs"), before["jobs"][name].get("needs"))
        for key in ("PRODUCT_NAME", "BASE_DIR", "MACOS_DEPLOYMENT_TARGET"):
            self.assertEqual(build["env"][key], before["env"][key])
        windows = build["jobs"]["build-windows"]["steps"]
        command = next(step for step in windows if step.get("name") == "build x64")
        old_command = next(step for step in before["jobs"]["build-windows"]["steps"]
                           if step.get("name") == "build x64")
        self.assertEqual(command["shell"], old_command["shell"])
        self.assertEqual(command["run"], old_command["run"])
        mac = build["jobs"]["build-macos"]["steps"]
        preflight = next(i for i, step in enumerate(mac) if "preflight" in step.get("run", ""))
        credentials = next(i for i, step in enumerate(mac) if step.get("name") ==
                           "import Developer ID certificate")
        self.assertLess(preflight, credentials)
        self.assertEqual(mac[-1]["name"], "Revalidate retained outputs and publish")
        self.assertIn("release.py publish", mac[-1]["run"])

    def test_no_intake_gitlinks_or_automatic_native_ci(self):
        tree = subprocess.check_output(["git", "ls-tree", "-r", "HEAD"], cwd=ROOT, text=True)
        self.assertFalse(any(row.startswith("160000 ") for row in tree.splitlines()))
        for name in ("bump-version.yml", "release.yml"):
            original_workflow = yaml.load(original(".github/workflows/" + name),
                                          Loader=yaml.BaseLoader)
            triggers = original_workflow["on"]
            self.assertNotIn("pull_request", triggers)
            self.assertNotIn("pull_request_target", triggers)
            if "push" in triggers:
                self.assertEqual(triggers["push"], {"tags": ["v*.*.*"]})

    def test_native_inputs_and_every_prebuilt_destination_are_unchanged(self):
        fixed = ("COM4D.vcxproj", "COM4D.sln", "Info.plist",
                 "manifest.json", "constants.xlf", ".gitignore")
        paths = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", INTAKE, "--", "test/Plugins"],
            cwd=ROOT, text=True,
        ).splitlines()
        self.assertTrue(paths)
        for path in (*fixed, *paths):
            with self.subTest(path=path):
                self.assertEqual((ROOT / path).read_bytes(), original(path))
                before = subprocess.check_output(
                    ["git", "ls-tree", INTAKE, "--", path], cwd=ROOT, text=True,
                ).split()[0]
                current = subprocess.check_output(
                    ["git", "ls-files", "--stage", "--", path], cwd=ROOT, text=True,
                ).split()[0]
                self.assertEqual(current, before)
