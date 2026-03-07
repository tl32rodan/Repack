"""Tests for pipeline configuration loading and template expansion."""

import os
import tempfile
import unittest

from kitdag.pipeline import PipelineConfig, StepConfig, load_pipeline, _expand_vars


class TestExpandVars(unittest.TestCase):

    def test_simple_expansion(self):
        result = _expand_vars("{output_root}/liberty", {"output_root": "/data/out"})
        self.assertEqual(result, "/data/out/liberty")

    def test_multiple_vars(self):
        result = _expand_vars(
            "{output_root}/{name}.log",
            {"output_root": "/data", "name": "test"},
        )
        self.assertEqual(result, "/data/test.log")

    def test_unknown_var_kept(self):
        result = _expand_vars("{unknown}/path", {"output_root": "/data"})
        self.assertEqual(result, "{unknown}/path")

    def test_no_vars(self):
        result = _expand_vars("/absolute/path", {"output_root": "/data"})
        self.assertEqual(result, "/absolute/path")


class TestLoadPipeline(unittest.TestCase):

    def _write_yaml(self, content: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w") as f:
            f.write(content)
        return path

    def test_basic_load(self):
        path = self._write_yaml("""
output_root: /data/output
executor: local
max_workers: 2

steps:
  kitA:
    run: kitA
    in:
      ref_dir: /data/source
      library_name: test_lib
    out:
      output_dir: /data/output/kitA
      log: /data/output/kitA/kitA.log
    dependencies: []
""")
        pipeline = load_pipeline(path)
        os.unlink(path)

        self.assertEqual(pipeline.output_root, "/data/output")
        self.assertEqual(pipeline.executor, "local")
        self.assertEqual(pipeline.max_workers, 2)
        self.assertIn("kitA", pipeline.steps)

        step = pipeline.steps["kitA"]
        self.assertEqual(step.run, "kitA")
        self.assertEqual(step.inputs["library_name"], "test_lib")
        self.assertEqual(step.output_dir, "/data/output/kitA")
        self.assertEqual(step.dependencies, [])

    def test_template_expansion_in_out(self):
        path = self._write_yaml("""
output_root: /data/output

steps:
  kitA:
    run: kitA
    in:
      library_name: test
    out:
      output_dir: "{output_root}/kitA"
      log: "{output_root}/kitA/kitA.log"
    dependencies: []
""")
        pipeline = load_pipeline(path)
        os.unlink(path)

        step = pipeline.steps["kitA"]
        self.assertEqual(step.output_dir, "/data/output/kitA")
        self.assertEqual(step.log_path, "/data/output/kitA/kitA.log")

    def test_template_expansion_in_inputs(self):
        path = self._write_yaml("""
output_root: /data/output

steps:
  kitB:
    run: kitB
    in:
      lib_dir: "{output_root}/kitA"
      library_name: test
    out:
      output_dir: "{output_root}/kitB"
      log: "{output_root}/kitB/kitB.log"
    dependencies: [kitA]
""")
        pipeline = load_pipeline(path)
        os.unlink(path)

        step = pipeline.steps["kitB"]
        self.assertEqual(step.inputs["lib_dir"], "/data/output/kitA")
        self.assertEqual(step.dependencies, ["kitA"])

    def test_run_defaults_to_step_name(self):
        path = self._write_yaml("""
steps:
  liberty:
    in:
      ref_dir: /data
    out:
      output_dir: /out/liberty
      log: /out/liberty.log
    dependencies: []
""")
        pipeline = load_pipeline(path)
        os.unlink(path)

        self.assertEqual(pipeline.steps["liberty"].run, "liberty")


if __name__ == "__main__":
    unittest.main()
