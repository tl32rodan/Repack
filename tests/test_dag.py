"""Tests for DAG builder and topological sort (kit-level)."""

import unittest

from kitdag.core.dag import CyclicDependencyError, DAGBuilder
from kitdag.core.target import KitTarget


class TestDAGBuilder(unittest.TestCase):

    def test_no_dependencies(self):
        dag = DAGBuilder()
        targets = [KitTarget("A"), KitTarget("B")]
        dag.add_targets(targets)
        dag.build_edges({})

        order = dag.topological_sort()
        self.assertEqual(set(order), {"A", "B"})

    def test_simple_dependency(self):
        dag = DAGBuilder()
        targets = [KitTarget("A"), KitTarget("B")]
        dag.add_targets(targets)
        dag.build_edges({"B": ["A"]})

        order = dag.topological_sort()
        self.assertLess(order.index("A"), order.index("B"))

    def test_chain_dependency(self):
        """A -> B -> C"""
        dag = DAGBuilder()
        targets = [KitTarget("A"), KitTarget("B"), KitTarget("C")]
        dag.add_targets(targets)
        dag.build_edges({"B": ["A"], "C": ["B"]})

        order = dag.topological_sort()
        self.assertLess(order.index("A"), order.index("B"))
        self.assertLess(order.index("B"), order.index("C"))

    def test_cycle_detection(self):
        dag = DAGBuilder()
        targets = [KitTarget("A"), KitTarget("B")]
        dag.add_targets(targets)
        dag.build_edges({"A": ["B"], "B": ["A"]})

        with self.assertRaises(CyclicDependencyError):
            dag.topological_sort()

    def test_execution_stages(self):
        """Targets in same stage have no inter-dependencies."""
        dag = DAGBuilder()
        targets = [KitTarget("A"), KitTarget("B"), KitTarget("C")]
        dag.add_targets(targets)
        dag.build_edges({"C": ["A", "B"]})

        stages = dag.get_execution_stages()
        self.assertEqual(len(stages), 2)
        self.assertIn("A", stages[0])
        self.assertIn("B", stages[0])
        self.assertIn("C", stages[1])

    def test_diamond_dependency(self):
        """A -> B, A -> C, B -> D, C -> D."""
        dag = DAGBuilder()
        targets = [KitTarget("A"), KitTarget("B"), KitTarget("C"), KitTarget("D")]
        dag.add_targets(targets)
        dag.build_edges({
            "B": ["A"],
            "C": ["A"],
            "D": ["B", "C"],
        })

        order = dag.topological_sort()
        self.assertLess(order.index("A"), order.index("B"))
        self.assertLess(order.index("A"), order.index("C"))
        self.assertLess(order.index("B"), order.index("D"))
        self.assertLess(order.index("C"), order.index("D"))

    def test_get_dependencies(self):
        dag = DAGBuilder()
        targets = [KitTarget("A"), KitTarget("B"), KitTarget("C")]
        dag.add_targets(targets)
        dag.build_edges({"C": ["A", "B"]})

        deps = dag.get_dependencies("C")
        self.assertEqual(deps, {"A", "B"})

    def test_get_dependents(self):
        dag = DAGBuilder()
        targets = [KitTarget("A"), KitTarget("B")]
        dag.add_targets(targets)
        dag.build_edges({"B": ["A"]})

        dependents = dag.get_dependents("A")
        self.assertIn("B", dependents)

    def test_unknown_dependency_ignored(self):
        """Dependencies on non-existent kits are silently ignored."""
        dag = DAGBuilder()
        targets = [KitTarget("A")]
        dag.add_targets(targets)
        dag.build_edges({"A": ["nonexistent"]})

        order = dag.topological_sort()
        self.assertEqual(order, ["A"])


if __name__ == "__main__":
    unittest.main()
