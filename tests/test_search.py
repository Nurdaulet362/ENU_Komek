import unittest

from app.search import SearchEngine


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.engine = SearchEngine([
            {'id':'a','title':'Возвращение с академической мобильности','role':'student','pages':[{'page':1,'text':'Для возвращения с академической мобильности загрузите скан-копию транскрипта стороннего вуза. Нажмите кнопку Сохранить и Подать заявку.'}]},
            {'id':'b','title':'Тестирование преподавателя','role':'staff','pages':[{'page':1,'text':'Преподаватель создает тестирование и назначает тест студентам.'}]},
        ])

    def test_cites_actual_document_and_page(self):
        hits = self.engine.search('Какие документы нужны для возвращения с мобильности?')
        self.assertEqual(hits[0]['document_id'], 'a')
        self.assertEqual(hits[0]['page'], 1)
        self.assertIn('транскрипта', hits[0]['text'])

    def test_unknown_question_has_no_answer(self):
        self.assertEqual(self.engine.search('Как приготовить борщ с картошкой?'), [])

    def test_kazakh_query_finds_russian_source(self):
        self.assertEqual(self.engine.search('Академиялық ұтқырлықтан оралу үшін қандай құжат керек?')[0]['document_id'], 'a')

    def test_staff_materials_are_excluded_for_students(self):
        self.assertEqual(self.engine.search('Как преподаватель создает тестирование?', role='student'), [])
        self.assertEqual(self.engine.search('Как преподаватель создает тестирование?', role='all')[0]['document_id'], 'b')

    def test_empty_input(self):
        self.assertEqual(self.engine.search('   '), [])


if __name__ == '__main__':
    unittest.main()
