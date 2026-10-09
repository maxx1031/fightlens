import unittest
from engagement import Engagement


def people(separation=400, wrist_shift=0):
    result = {}
    for name, x in (("A", 0), ("B", separation)):
        points = [[x, 0, 1] for _ in range(17)]
        for j, xy in {
            5: (0, 0),
            6: (10, 0),
            7: (0, 50),
            8: (10, 50),
            9: (10 + wrist_shift, 10),
            10: (20 + wrist_shift, 10),
            11: (0, 100),
            12: (10, 100),
            15: (0, 180),
            16: (10, 180),
        }.items():
            points[j] = [x + xy[0], xy[1], 1]
        result[name] = {"kpts": points}
    return result


class CausalEngagementTests(unittest.TestCase):
    def test_future_attack_does_not_rewrite_prior_clear_point(self):
        rule = Engagement()
        before = rule.update(0, people(), "stable")
        self.assertEqual(before["engaged"], 0)
        after = rule.update(1, people(50), "stable")
        self.assertEqual(after["engaged"], 1)
        self.assertEqual(before["engaged"], 0)

    def test_actual_time_delta_makes_speed_independent_of_sampling_rate(self):
        speeds = []
        for dt in (0.1, 0.2):
            rule = Engagement()
            rule.update(0, people(), "stable")
            speeds.append(
                rule.update(dt, people(wrist_shift=dt * 100), "stable")["limb_speed"]
            )
        self.assertAlmostEqual(speeds[0], speeds[1], places=6)

    def test_missing_pose_is_gap_and_clears_derivative_history(self):
        rule = Engagement()
        rule.update(0, people(), "stable")
        missing = people()
        missing["A"]["kpts"][11][2] = 0
        self.assertIsNone(rule.update(0.1, missing, "stable")["engaged"])
        self.assertIsNone(rule.update(0.2, people(), "stable")["limb_speed"])

    def test_uncertain_identity_cannot_attribute_engagement(self):
        self.assertEqual(
            Engagement().update(0, people(50), "uncertain")["state"], "UNKNOWN"
        )

    def test_exchange_end_waits_one_second_without_delaying_start(self):
        rule = Engagement()
        self.assertEqual(rule.update(0, people(50), "stable")["engaged"], 1)
        self.assertEqual(rule.update(0.9, people(), "stable")["engaged"], 1)
        self.assertEqual(rule.update(1.01, people(), "stable")["engaged"], 0)


if __name__ == "__main__":
    unittest.main()
