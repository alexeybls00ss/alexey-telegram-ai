import html
import unittest

def app_module():
    import main
    return main


class ReportFormattingTests(unittest.TestCase):
    def test_markdown_to_telegram_html(self):
        result=app_module().report_to_html("### Главное\n**Важный факт**\n- пункт")
        self.assertIn("<b>Главное</b>",result)
        self.assertIn("<b>Важный факт</b>",result)
        self.assertIn("• пункт",result)
        self.assertNotIn("###",result)
        self.assertNotIn("**",result)

    def test_html_escaping(self):
        result=app_module().report_to_html("**Текст** <script>alert(1)</script> & другое")
        self.assertIn("<b>Текст</b>",result)
        self.assertIn("&lt;script&gt;",result)
        self.assertIn("&amp; другое",result)

    def test_progress_format(self):
        row={"kind":"day","target":"2026-11-21","status":"running",
             "stage":"Обработка", "processed":2,"total":3,"part":1,"parts":2,
             "estimated_usd":0.0012,"error":None}
        result=app_module().analysis_status_text(row)
        self.assertIn("2/3",result)
        self.assertIn("1/2",result)
        self.assertIn("0.0012",result)


if __name__=="__main__":
    unittest.main()
