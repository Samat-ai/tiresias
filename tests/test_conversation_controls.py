import pytest

from tiresias.agent.conversation_controls import clean_request, language_command


@pytest.mark.parametrize('text',['Uh.','Um, um-','А-а-а...','Я га-','Я вижу-','Ага.',
    'Да, да, я вижу.','Да. Да, да, всё-таки да.','[noise]','(coughing)','...',
    'Well, this is not a job.','20. Can you 20?'])
def test_noise_and_fragments_are_not_requests(text):
    assert clean_request(text,busy=True) is None


@pytest.mark.parametrize('text',['Stop.','Check this.','Where are they?','What do you see?',
    'Что ты видишь?','Я правильно нашёл его?','Find my AirPods.','Quiet.',
    'Say that again.','Try again.','Help me find my keys.','I need to find Pepsi.'])
def test_real_questions_and_controls_survive_noise_gate(text):
    assert clean_request(text,busy=True)


def test_idle_product_name_is_allowed_but_busy_ambiguous_fragment_is_not():
    assert clean_request('Pepsi',busy=False)=='Pepsi'
    assert clean_request('Pepsi',busy=True) is None
    assert clean_request('Um, how many cans?',busy=True)=='how many cans?'
    assert clean_request('А-а-а, найди мне AirPods.',busy=True)=='найди мне AirPods.'


@pytest.mark.parametrize('text,code',[('Speak Russian.','ru'),('Switch to English.','en'),
    ('Please speak in Russian.','ru'),('Говори по-русски.','ru'),('Отвечай на английском.','en')])
def test_language_changes_only_from_an_explicit_command(text,code):
    assert language_command(text)==code


@pytest.mark.parametrize('text',['Что ты видишь?','This label is Russian.','English breakfast tea',
    'He said speak Russian.','Read the words "speak Russian" on this label.'])
def test_mentions_and_foreign_speech_do_not_change_language(text):
    assert language_command(text) is None
