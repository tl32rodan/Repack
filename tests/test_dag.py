"""Tests for DAG builder and topological sort."""

import unittest

from kitdag.core.dag import CyclicDependencyError, DAGBuilder
from kitdag.core.target import KitTarget


class TestDAGBuilder(unittest.TestCase):

    def test_no_dependencies(self):
        dag = DAGBuilder()
        targets = [
            KitTarget("A", pvt="ALL"),
            KitTarget("B", pvt="ALL"),
        ]
        dag.add_targets(targets)
        dag.build_edges({})

        order = dag.topological_sort()
        self.assertEqual(set(order), {"A::ALL", "B::ALL"})

    def test_simple_dependency(self):
        dag = DAGBuilder()
        targets = [
            KitTarget("A", pvt="ALL"),
            KitTarget("B", pvt="ALL"),
        ]
        dag.add_targets(targets)
        dag.build_edges({"B": ["A"]})

        order = dag.topological_sort()
        self.assertLess(order.index("A::ALL"), order.index("B::ALL"))

    def test_pvt_matching_corner_to_corner(self):
        """Corner-based kits: same PVT should link."""
        dag = DAGBuilder()
        targets = [
            KitTarget("A", pvt="ss_100c"),
            KitTarget("A", pvt="ff_0c"),
            KitTarget("B", pvt="ss_100c"),
            KitTarget("B", pvt="ff_0c"),
        ]
        dag.add_targets(targets)
        dag.build_edges({"B": ["A"]})

        # B::ss_100c depends on A::ss_100c, NOT on A::ff_0c
        deps = dag.get_dependencies("B::ss_100c")
        self.assertIn("A::ss_100c", deps)
        self.assertNotIn("A::ff_0c", deps)

    def test_pvt_matching_all_to_corner(self):
        """Non-corner upstream, corner downstream."""
        dag = DAGBuilder()
        targets = [
            KitTarget("A", pvt="ALL"),
            KitTarget("B", pvt="ss_100c"),
            KitTarget("B", pvt="ff_0c"),
        ]
        dag.add_targets(targets)
        dag.build_edges({"B": ["A"]})

        # Both B targets depend on A::ALL
        self.assertIn("A::ALL", dag.get_dependencies("B::ss_100c"))
        self.assertIn("A::ALL", dag.get_dependencies("B::ff_0c"))

    def test_pvt_matching_corner_to_all(self):
        """Corner upstream, non-corner downstream."""
        dag = DAGBuilder()
        targets = [
            KitTarget("A", pvt="ss_100c"),
            KitTarget("A", pvt="ff_0c"),
            KitTarget("B", pvt="ALL"),
        ]
        dag.add_targets(targets)
        dag.build_edges({"B": ["A"]})

        # B::ALL depends on all A targets
        deps = dag.get_dependencies("B::ALL")
        self.assertIn("A::ss_100c", deps)
        self.assertIn("A::ff_0c", deps)

    def test_cycle_detection(self):
        dag = DAGBuilder()
        targets = [
            KitTarget("A", pvt="ALL"),
            KitTarget("B", pvt="ALL"),
        ]
        dag.add_targets(targets)
        dag.build_edges({"A": ["B"], "B": ["A"]})

        with self.assertRaises(CyclicDependencyError):
            dag.topological_sort()

    def test_execution_stages(self):
        """Targets in same stage have no inter-dependencies."""
        dag = DAGBuilder()
        targets = [
            KitTarget("A", pvt="ALL"),
            KitTarget("B", pvt="ALL"),
            KitTarget("C", pvt="ALL"),
        ]
        dag.add_targets(targets)
        dag.build_edges({"C": ["A", "B"]})

        stages = dag.get_execution_stages()
        self.assertEqual(len(stages), 2)
        # A and B should be in stage 0
        self.assertIn("A::ALL", stages[0])
        self.assertIn("B::ALL", stages[0])
        # C in stage 1
        self.assertIn("C::ALL", stages[1])

    def test_diamond_dependency(self):
        """A -> B, A -> C, B -> D, C -> D."""
        dag = DAGBuilder()
        targets = [
            KitTarget("A", pvt="ALL"),
            KitTarget("B", pvt="ALL"),
            KitTarget("C", pvt="ALL"),
            KitTarget("D", pvt="ALL"),
        ]
        dag.add_targets(targets)
        dag.build_edges({
            "B": ["A"],
            "C": ["A"],
            "D": ["B", "C"],
        })

        order = dag.topological_sort()
        self.assertLess(order.index("A::ALL"), order.index("B::ALL"))
        self.assertLess(order.index("A::ALL"), order.index("C::ALL"))
        self.assertLess(order.index("B::ALL"), order.index("D::ALL"))
        self.assertLess(order.index("C::ALL"), order.index("D::ALL"))


if __name__ == "__main__":
    unittest.main()
