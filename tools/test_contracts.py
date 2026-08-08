import unittest

from src.core.task_contracts import (
    BypassFileConfig,
    BypassRunConfig,
    EmlRunConfig,
    EmlTaskConfig,
    PdfRunConfig,
    RunPlan,
    SourceDisposition,
    SyncGroupConfig,
    SyncRunConfig,
    TaskStep,
)


class ContractTests(unittest.TestCase):
    def test_run_plan_preserves_fixed_step_order(self):
        plan = RunPlan({
            TaskStep.BYPASS: BypassRunConfig([], SourceDisposition.BACKUP),
            TaskStep.PDF: PdfRunConfig(["a.pdf"], "out"),
            TaskStep.SYNC: SyncRunConfig([SyncGroupConfig("g", ["a", "b"])]),
        })

        self.assertEqual(plan.active_steps, [TaskStep.SYNC, TaskStep.PDF, TaskStep.BYPASS])

    def test_legacy_dict_shapes_are_stable(self):
        eml = EmlRunConfig([EmlTaskConfig("daily", "in", "out")], width=1200)
        bypass = BypassRunConfig(
            [BypassFileConfig("a.xlsx", "a.xlsb", ".xlsb", True, SourceDisposition.KEEP)],
            SourceDisposition.KEEP,
        )

        self.assertEqual(eml.to_legacy_dict()["tasks"][0]["name"], "daily")
        self.assertEqual(eml.to_legacy_dict()["width"], 1200)
        self.assertEqual(bypass.to_legacy_dict()["tasks"][0]["ext"], ".xlsb")
        self.assertFalse(bypass.to_legacy_dict()["delete_original"])
        self.assertEqual(bypass.to_legacy_dict()["source_disposition"], "keep")


if __name__ == "__main__":
    unittest.main()
