"""Tests for DAG builder with scope-based tasks."""

import unittest

from kitdag.core.dag import CyclicDependencyError, DAGBuilder
from kitdag.core.task import Task


class TestDAGBuilder(unittest.TestCase):

    def test_no_dependencies(self):
        dag = DAGBuilder()
        tasks = [Task("A"), Task("B")]
        dag.add_tasks(tasks)
        order = dag.topological_sort()
        self.assertEqual(set(order), {"A", "B"})

    def test_simple_dependency(self):
        dag = DAGBuilder()
        tasks = [Task("A"), Task("B")]
        dag.add_tasks(tasks)
        dag.set_edges({"B": {"A"}})
        order = dag.topological_sort()
        self.assertLess(order.index("A"), order.index("B"))

    def test_chain(self):
        dag = DAGBuilder()
        tasks = [Task("A"), Task("B"), Task("C")]
        dag.add_tasks(tasks)
        dag.set_edges({"B": {"A"}, "C": {"B"}})
        order = dag.topological_sort()
        self.assertLess(order.index("A"), order.index("B"))
        self.assertLess(order.index("B"), order.index("C"))

    def test_cycle_detection(self):
        dag = DAGBuilder()
        tasks = [Task("A"), Task("B")]
        dag.add_tasks(tasks)
        dag.set_edges({"A": {"B"}, "B": {"A"}})
        with self.assertRaises(CyclicDependencyError):
            dag.topological_sort()

    def test_execution_stages(self):
        dag = DAGBuilder()
        tasks = [Task("A"), Task("B"), Task("C")]
        dag.add_tasks(tasks)
        dag.set_edges({"C": {"A", "B"}})
        stages = dag.get_execution_stages()
        self.assertEqual(len(stages), 2)
        self.assertIn("A", stages[0])
        self.assertIn("B", stages[0])
        self.assertIn("C", stages[1])

    def test_scoped_tasks(self):
        dag = DAGBuilder()
        t1 = Task("extract", scope={"lib": "a", "branch": "ss"})
        t2 = Task("char", scope={"lib": "a", "branch": "ss"})
        dag.add_tasks([t1, t2])
        dag.set_edges({t2.id: {t1.id}})
        order = dag.topological_sort()
        self.assertLess(order.index(t1.id), order.index(t2.id))

    def test_get_dependencies(self):
        dag = DAGBuilder()
        tasks = [Task("A"), Task("B"), Task("C")]
        dag.add_tasks(tasks)
        dag.set_edges({"C": {"A", "B"}})
        self.assertEqual(dag.get_dependencies("C"), {"A", "B"})

    def test_get_dependents(self):
        dag = DAGBuilder()
        tasks = [Task("A"), Task("B")]
        dag.add_tasks(tasks)
        dag.set_edges({"B": {"A"}})
        self.assertIn("B", dag.get_dependents("A"))


if __name__ == "__main__":
    unittest.main()
