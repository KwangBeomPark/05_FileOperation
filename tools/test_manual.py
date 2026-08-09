import os
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.ui.manual_content import MANUAL_CONTENT, TOPIC_ORDER, manual_topic, manual_topics
from src.ui.manual_dialog import ManualDialog


class ManualContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_all_languages_have_the_same_topics_and_sections(self):
        expected_sections = {"title", "summary", "steps", "tips", "cautions"}
        for language in ("en", "ko", "pl"):
            self.assertEqual(tuple(MANUAL_CONTENT[language]), TOPIC_ORDER)
            for topic in MANUAL_CONTENT[language].values():
                self.assertEqual(set(topic), expected_sections)
                self.assertTrue(topic["steps"])
                self.assertTrue(topic["tips"])
                self.assertTrue(topic["cautions"])

    def test_non_korean_manuals_do_not_leak_hangul(self):
        hangul = re.compile(r"[가-힣]")
        for language in ("en", "pl"):
            leaked = []
            for topic_id, topic in manual_topics(language):
                values = [topic["title"], topic["summary"], *topic["steps"], *topic["tips"], *topic["cautions"]]
                if any(hangul.search(str(value)) for value in values):
                    leaked.append(topic_id)
            self.assertEqual(leaked, [], language)

    def test_korean_manual_explains_scheduling_and_preview_safety(self):
        self.assertIn("알림 영역", manual_topic("getting_started", "ko")["cautions"][0])
        self.assertIn("미리보기", " ".join(manual_topic("sync", "ko")["steps"]))
        self.assertIn("Original Backup", " ".join(manual_topic("bypass", "ko")["tips"]))

    def test_korean_manual_uses_beginner_facing_terms(self):
        rendered = " ".join(
            str(value)
            for _topic_id, topic in manual_topics("ko")
            for value in (topic["title"], topic["summary"], *topic["steps"], *topic["tips"], *topic["cautions"])
        )
        self.assertNotIn("우회 변환", rendered)
        self.assertNotIn("Playwright", rendered)
        self.assertIn("브라우저 구성 요소", rendered)

    def test_manual_dialog_opens_requested_localized_topic(self):
        dialog = ManualDialog("ko", "sync")
        self.assertEqual(dialog.topic_list.currentItem().data(256), "sync")
        self.assertIn("폴더 동기화", dialog.content.toPlainText())
        self.assertIn("사용 순서", dialog.content.toPlainText())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
