import tempfile
import unittest
import zipfile
from pathlib import Path

from app.documents import extract, role_for


class DocumentTests(unittest.TestCase):
    def test_policy_is_for_students_even_if_title_mentions_staff(self):
        self.assertEqual(role_for('Политика академической честности преподавателей, сотрудников, обучающихся'), 'student')

    def test_employee_guide_is_staff(self):
        self.assertEqual(role_for('Инструкция для сотрудника ОВПО'), 'staff')

    def test_docx_preserves_text_and_labels_sections(self):
        xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Студент подает заявление</w:t></w:r></w:p></w:body></w:document>'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sample.docx'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('word/document.xml', xml)
            self.assertEqual(extract(path), [{'page':1, 'text':'Студент подает заявление', 'location':'section'}])
